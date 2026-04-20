from __future__ import annotations

import asyncio
import json
from pathlib import Path

import click
import httpx
import structlog

from config import Settings
from nlm_ingest.schemas import Transcript
from nlm_ingest.state import (
    PHASE_ORDER,
    attempt_retry,
    get_all_status,
    init_db,
    register_notebook,
    set_phase_status,
    validate_retry,
)

log = structlog.get_logger()


def _get_settings() -> Settings:
    return Settings()


def _get_db():
    settings = _get_settings()
    db_path = Path(settings.nlm_data_dir) / "state.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return init_db(db_path)


async def _check_voxtral(url: str) -> bool:
    """Healthcheck: try real audio transcription, fallback to /models."""
    try:
        async with httpx.AsyncClient() as client:
            import io

            from pydub import AudioSegment
            silence = AudioSegment.silent(duration=1000)
            buf = io.BytesIO()
            silence.export(buf, format="wav")
            buf.seek(0)

            resp = await client.post(
                f"{url}/audio/transcriptions",
                files={"file": ("test.wav", buf.read(), "audio/wav")},
                data={"model": "voxtral", "response_format": "json"},
                timeout=30.0,
            )
            if resp.status_code == 200:
                return True

            resp = await client.get(f"{url}/models", timeout=10.0)
            return resp.status_code == 200
    except Exception:
        return False


@click.group()
def cli():
    """NotebookLM → ODIN Knowledge Ingestion Pipeline."""
    pass


@cli.command()
def status():
    """Show status matrix: Notebook x Phase x Status."""
    db = _get_db()
    matrix = get_all_status(db)
    db.close()

    if not matrix:
        click.echo("No notebooks registered yet.")
        return

    click.echo(f"{'Notebook':<35} {'export':<12} {'transcribe':<12} {'extract':<12} {'ingest':<12}")
    click.echo("-" * 83)
    for row in matrix:
        click.echo(
            f"{row.get('title', row['notebook_id'])[:34]:<35} "
            f"{row.get('export', '-'):<12} "
            f"{row.get('transcribe', '-'):<12} "
            f"{row.get('extract', '-'):<12} "
            f"{row.get('ingest', '-'):<12}"
        )


@cli.command()
def healthcheck():
    """Check if Voxtral is reachable and responding."""
    settings = _get_settings()
    ok = asyncio.run(_check_voxtral(settings.voxtral_url))
    if ok:
        click.echo("Voxtral: OK")
    else:
        click.echo("Voxtral: FAIL — is vllm-voxtral running?")
        raise SystemExit(1)


@cli.command()
@click.option("--id", "notebook_id", default=None, help="Process single notebook by ID")
def export(notebook_id: str | None):
    """Phase 1: Export notebooks from NotebookLM."""
    settings = _get_settings()
    data_dir = Path(settings.nlm_data_dir)

    async def _run():
        from nlm_ingest.export import export_all
        results = await export_all(data_dir, notebook_id=notebook_id)
        db = _get_db()
        for r in results:
            register_notebook(db, r["notebook_id"], r["title"], r["source_name"])
            set_phase_status(db, r["notebook_id"], "export", "completed")
        db.close()
        click.echo(f"Exported {len(results)} notebooks.")

    asyncio.run(_run())


@cli.command()
@click.option("--id", "notebook_id", default=None, help="Transcribe single notebook by ID")
def transcribe(notebook_id: str | None):
    """Phase 2: Transcribe audio via Voxtral."""
    settings = _get_settings()
    data_dir = Path(settings.nlm_data_dir)

    async def _run():
        from nlm_ingest.transcribe import transcribe as do_transcribe
        db = _get_db()
        matrix = get_all_status(db)
        targets = [
            r for r in matrix
            if r.get("export") == "completed"
            and r.get("transcribe") in ("pending", "failed", "running")
            and (notebook_id is None or r["notebook_id"] == notebook_id)
        ]

        async with httpx.AsyncClient() as client:
            for row in targets:
                nid = row["notebook_id"]
                # Try mp4 first (NotebookLM default), then mp3
                audio_path = data_dir / "notebooks" / nid / "podcast.mp4"
                if not audio_path.exists():
                    audio_path = data_dir / "notebooks" / nid / "podcast.mp3"
                if not audio_path.exists():
                    click.echo(f"SKIP {nid}: no audio file")
                    continue

                set_phase_status(db, nid, "transcribe", "running")
                try:
                    result = await do_transcribe(
                        notebook_id=nid,
                        audio_path=audio_path,
                        client=client,
                        voxtral_url=settings.voxtral_url,
                        voxtral_model=settings.voxtral_model,
                    )
                    out_path = data_dir / "transcripts" / f"{nid}.json"
                    out_path.parent.mkdir(parents=True, exist_ok=True)
                    out_path.write_text(result.model_dump_json(indent=2))
                    set_phase_status(db, nid, "transcribe", "completed")
                    segs = len(result.segments)
                    click.echo(f"OK {nid}: {result.duration_seconds:.0f}s, {segs} segments")
                except Exception as e:
                    set_phase_status(db, nid, "transcribe", "failed", error=str(e))
                    click.echo(f"FAIL {nid}: {e}")

        db.close()

    asyncio.run(_run())


@cli.command()
@click.option("--id", "notebook_id", default=None, help="Extract from single notebook by ID")
def extract(notebook_id: str | None):
    """Phase 3: Extract entities/claims via Qwen + Claude."""
    settings = _get_settings()
    data_dir = Path(settings.nlm_data_dir)

    async def _run():
        from nlm_ingest.extract import extract_with_qwen, review_with_claude
        db = _get_db()
        matrix = get_all_status(db)
        targets = [
            r for r in matrix
            if r.get("transcribe") == "completed"
            and r.get("extract") in ("pending", "failed", "running")
            and (notebook_id is None or r["notebook_id"] == notebook_id)
        ]

        claude_client = None
        try:
            import anthropic
            claude_client = anthropic.AsyncAnthropic()
        except Exception:
            log.warning("anthropic_not_available", msg="Claude review disabled")

        async with httpx.AsyncClient() as client:
            for row in targets:
                nid = row["notebook_id"]
                transcript_path = data_dir / "transcripts" / f"{nid}.json"
                if not transcript_path.exists():
                    click.echo(f"SKIP {nid}: no transcript")
                    continue

                set_phase_status(db, nid, "extract", "running")
                try:
                    transcript = Transcript.model_validate_json(transcript_path.read_text())
                    meta_path = data_dir / "notebooks" / nid / "metadata.json"
                    metadata = json.loads(meta_path.read_text()) if meta_path.exists() else {}

                    extraction = await extract_with_qwen(
                        transcript=transcript,
                        metadata=metadata,
                        client=client,
                        vllm_url=settings.ingestion_vllm_url,
                        vllm_model=settings.ingestion_vllm_model,
                    )

                    if claude_client:
                        extraction = await review_with_claude(
                            extraction=extraction,
                            transcript=transcript,
                            claude_client=claude_client,
                            claude_model=settings.claude_model,
                        )

                    out_path = data_dir / "extractions" / f"{nid}.json"
                    out_path.parent.mkdir(parents=True, exist_ok=True)
                    out_path.write_text(extraction.model_dump_json(indent=2))
                    set_phase_status(db, nid, "extract", "completed")
                    click.echo(
                        f"OK {nid}: {len(extraction.entities)} entities, "
                        f"{len(extraction.claims)} claims, "
                        f"{len(extraction.relations)} relations"
                    )
                except Exception as e:
                    set_phase_status(db, nid, "extract", "failed", error=str(e))
                    click.echo(f"FAIL {nid}: {e}")

        db.close()

    asyncio.run(_run())


@cli.command()
@click.option("--id", "notebook_id", default=None, help="Ingest single notebook by ID")
def ingest(notebook_id: str | None):
    """Phase 4: Write extraction results to Neo4j."""
    settings = _get_settings()
    data_dir = Path(settings.nlm_data_dir)

    async def _run():
        from nlm_ingest.ingest_neo4j import ingest_extraction
        from nlm_ingest.schemas import Extraction
        db = _get_db()
        matrix = get_all_status(db)
        targets = [
            r for r in matrix
            if r.get("extract") == "completed"
            and r.get("ingest") in ("pending", "failed", "running")
            and (notebook_id is None or r["notebook_id"] == notebook_id)
        ]

        async with httpx.AsyncClient() as client:
            for row in targets:
                nid = row["notebook_id"]
                extraction_path = data_dir / "extractions" / f"{nid}.json"
                if not extraction_path.exists():
                    click.echo(f"SKIP {nid}: no extraction")
                    continue

                set_phase_status(db, nid, "ingest", "running")
                try:
                    extraction = Extraction.model_validate_json(extraction_path.read_text())
                    source_name = row.get("source", "unknown")

                    await ingest_extraction(
                        extraction=extraction,
                        source_name=source_name,
                        client=client,
                        neo4j_url=settings.neo4j_url,
                        neo4j_user=settings.neo4j_user,
                        neo4j_password=settings.neo4j_password,
                    )
                    set_phase_status(db, nid, "ingest", "completed")
                    click.echo(f"OK {nid}: ingested to Neo4j")
                except Exception as e:
                    set_phase_status(db, nid, "ingest", "failed", error=str(e))
                    click.echo(f"FAIL {nid}: {e}")

        db.close()

    asyncio.run(_run())


@cli.command()
@click.option("--id", "notebook_id", default=None, help="Run all phases for single notebook")
def run(notebook_id: str | None):
    """Run all 4 phases sequentially."""
    ctx = click.get_current_context()
    ctx.invoke(export, notebook_id=notebook_id)
    ctx.invoke(transcribe, notebook_id=notebook_id)
    ctx.invoke(extract, notebook_id=notebook_id)
    ctx.invoke(ingest, notebook_id=notebook_id)


@cli.command()
@click.option("--id", "notebook_id", required=True, help="Notebook ID")
@click.option("--phase", required=True, type=click.Choice(PHASE_ORDER), help="Phase to retry")
def retry(notebook_id: str, phase: str):
    """Retry a failed phase (with prerequisite gating)."""
    db = _get_db()
    try:
        validate_retry(db, notebook_id, phase)
    except ValueError as e:
        raise click.UsageError(str(e)) from e

    affected = attempt_retry(db, notebook_id, phase)
    db.close()

    if affected == 0:
        click.echo(f"Nothing to retry: '{phase}' for {notebook_id} is not in 'failed' state.")
        return

    click.echo(f"Retrying '{phase}' for {notebook_id}...")
    ctx = click.get_current_context()
    phase_commands = {
        "export": export, "transcribe": transcribe,
        "extract": extract, "ingest": ingest,
    }
    ctx.invoke(phase_commands[phase], notebook_id=notebook_id)
