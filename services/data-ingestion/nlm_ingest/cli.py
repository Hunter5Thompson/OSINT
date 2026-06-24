from __future__ import annotations

import asyncio
import json
from pathlib import Path

import click
import httpx
import structlog

from config import Settings
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
    db = init_db(db_path)
    from nlm_ingest.migrate import migrate_local
    # Idempotent but O(extraction-files) per call (globs extractions/); acceptable at
    # current scale — called once per command, not in a loop.
    migrate_local(db, Path(settings.nlm_data_dir))
    return db


def _sources_needing_extract(data_dir, sources):
    """Sources without a valid, provenance-consistent extractions/{nid}.{source_id}.json."""
    from nlm_ingest.state import valid_extraction_exists
    return [s for s in sources if not valid_extraction_exists(data_dir, s)]


def _extraction_files_for(data_dir, notebook_id):
    """All extractions/{nid}.*.json of a notebook (multi-source)."""
    return sorted((data_dir / "extractions").glob(f"{notebook_id}.*.json"))


async def _ingest_one_notebook(
    files, *, expected_notebook_id, neo4j_write, qdrant_write
) -> bool:
    """Write each extraction file to Neo4j + Qdrant (injected writers).

    Aggregation (P1#4/P2#8): return True only on full success; one source
    failing -> False (phase stays 'failed', retryable).

    Provenance (P1#3b): the filename is the trusted key. For each
    ``{expected_notebook_id}.{source_id}.json`` we verify the validated
    Extraction's notebook_id/source_id match the filename; on mismatch we
    log a warning, mark the notebook not-ok, and SKIP writing that file (never
    ingest under a foreign id)."""
    from nlm_ingest.schemas import Extraction
    from nlm_ingest.sources import source_kind_for
    ok = True
    prefix = f"{expected_notebook_id}."
    for f in files:
        try:
            extraction = Extraction.model_validate_json(f.read_text())
            # Derive expected source_id from the filename (nid is known, so the
            # split is unambiguous): strip "{nid}." prefix and ".json" suffix.
            name = f.name
            expected_source_id = name[len(prefix):] if name.startswith(prefix) else name
            if expected_source_id.endswith(".json"):
                expected_source_id = expected_source_id[: -len(".json")]
            # Derive the expected source_kind from the filename's source_id, the same
            # way sources.load_sources does (shared helper: only "transcript" is a
            # transcript).
            expected_source_kind = source_kind_for(expected_source_id)
            if (
                extraction.notebook_id != expected_notebook_id
                or extraction.source_id != expected_source_id
                or extraction.source_kind != expected_source_kind
            ):
                log.warning(
                    "nlm_ingest_provenance_mismatch",
                    file=str(f),
                    expected_notebook_id=expected_notebook_id,
                    expected_source_id=expected_source_id,
                    expected_source_kind=expected_source_kind,
                    got_notebook_id=extraction.notebook_id,
                    got_source_id=extraction.source_id,
                    got_source_kind=extraction.source_kind,
                )
                ok = False
                continue
            await neo4j_write(extraction)
            await qdrant_write(extraction)
        except Exception:
            # Log diagnostics so a retrying operator can see why a source failed;
            # keep returning bool (caller marks the phase 'failed'/retryable).
            log.warning("nlm_ingest_source_failed", file=str(f), exc_info=True)
            ok = False
    return ok


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
        from nlm_ingest.state import reconcile_phases
        results = await export_all(data_dir, notebook_id=notebook_id)
        db = _get_db()
        try:
            for r in results:
                nid = r["notebook_id"]
                # Guard 1: register + export-status writes. A failure here keeps the
                # existing batch-isolation behavior (echo FAIL, skip this notebook).
                try:
                    register_notebook(db, nid, r["title"], r["source_name"])
                    export_status = (
                        "failed"
                        if (r["audio_status"] == "failed" or r["report_status"] == "failed")
                        else "completed"
                    )
                    set_phase_status(db, nid, "export", export_status)
                    if r["audio_status"] == "absent":
                        set_phase_status(db, nid, "transcribe", "skipped")
                except Exception as e:
                    click.echo(f"FAIL {nid}: {e}")
                    continue

                # Guard 2: reconcile is its OWN try/except. reconcile_phases ->
                # load_sources can RAISE on a corrupt/provenance-mismatched
                # transcript. If it does, we must NOT leave a stale extract/ingest=
                # completed (a NEW report would silently vanish). Force a retryable
                # state instead. The recovery writes are best-effort local sqlite —
                # a failure in them must not abort the whole batch.
                try:
                    reconcile_phases(
                        db,
                        data_dir,
                        nid,
                        audio_status=r["audio_status"],
                        report_status=r["report_status"],
                    )
                except Exception as e:
                    click.echo(f"FAIL {nid} reconcile: {e}")
                    try:
                        set_phase_status(db, nid, "extract", "failed")
                        set_phase_status(db, nid, "ingest", "pending")
                        # Audio present -> the transcript is repairable by re-running
                        # transcribe, so reopen that phase too.
                        if r["audio_status"] in ("downloaded", "failed"):
                            set_phase_status(db, nid, "transcribe", "pending")
                    except Exception as e2:
                        click.echo(f"FAIL {nid} reconcile-recovery: {e2}")
                    continue
        finally:
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
        from nlm_ingest.sources import load_sources
        db = _get_db()
        try:
            matrix = get_all_status(db)
            candidates = [
                r for r in matrix
                if r.get("extract") in ("pending", "failed", "running")
                and (notebook_id is None or r["notebook_id"] == notebook_id)
            ]

            claude_client = None
            try:
                import anthropic
                claude_client = anthropic.AsyncAnthropic()
            except Exception:
                log.warning("anthropic_not_available", msg="Claude review disabled")

            async with httpx.AsyncClient() as client:
                for row in candidates:
                    nid = row["notebook_id"]
                    # Per-notebook setup boundary: a corrupt transcript / bad
                    # provenance makes load_sources raise — isolate it to THIS
                    # notebook (extract=failed) instead of aborting the batch.
                    try:
                        sources = load_sources(data_dir, nid)
                    except Exception as e:
                        click.echo(f"FAIL {nid}: {e}")
                        set_phase_status(db, nid, "extract", "failed", error=str(e))
                        continue
                    if not sources:
                        click.echo(f"SKIP {nid}: no sources")
                        continue

                    set_phase_status(db, nid, "extract", "running")
                    meta_path = data_dir / "notebooks" / nid / "metadata.json"
                    try:
                        metadata = json.loads(meta_path.read_text()) if meta_path.exists() else {}
                    except Exception as e:
                        click.echo(f"FAIL {nid}: bad metadata.json: {e}")
                        set_phase_status(db, nid, "extract", "failed")
                        continue
                    ok = True
                    for source in _sources_needing_extract(data_dir, sources):
                        try:
                            extraction = await extract_with_qwen(
                                source=source,
                                metadata=metadata,
                                client=client,
                                vllm_url=settings.ingestion_vllm_url,
                                vllm_model=settings.ingestion_vllm_model,
                                timeout=settings.nlm_ingestion_vllm_timeout,
                                max_tokens=settings.ingestion_max_tokens,
                            )
                            if claude_client:
                                extraction = await review_with_claude(
                                    extraction=extraction,
                                    source=source,
                                    claude_client=claude_client,
                                    claude_model=settings.claude_model,
                                )
                            out = data_dir / "extractions" / f"{nid}.{source.source_id}.json"
                            out.parent.mkdir(parents=True, exist_ok=True)
                            out.write_text(extraction.model_dump_json(indent=2))
                            click.echo(
                                f"OK {nid}/{source.source_id}: "
                                f"{len(extraction.entities)} entities, "
                                f"{len(extraction.claims)} claims, "
                                f"{len(extraction.relations)} relations"
                            )
                        except Exception as e:
                            ok = False
                            click.echo(f"FAIL {nid}/{source.source_id}: {e}")
                    set_phase_status(db, nid, "extract", "completed" if ok else "failed")
        finally:
            db.close()

    asyncio.run(_run())


@cli.command()
@click.option("--id", "notebook_id", default=None, help="Ingest single notebook by ID")
def ingest(notebook_id: str | None):
    """Phase 4: Write extraction results to Neo4j + Qdrant (all sources)."""
    settings = _get_settings()
    data_dir = Path(settings.nlm_data_dir)

    async def _run():
        from qdrant_client import QdrantClient

        from nlm_ingest.ingest_neo4j import ingest_extraction
        from nlm_ingest.ingest_qdrant import (
            build_claim_points,
            ensure_collection,
            ingest_to_qdrant,
        )
        db = _get_db()
        qdrant = QdrantClient(url=settings.qdrant_url)
        try:
            await ensure_collection(
                qdrant,
                settings.qdrant_collection,
                settings.embedding_dimensions,
                enable_hybrid=settings.enable_hybrid,
            )
            # extract MUST be completed (P1#4): else a stale extraction file would be
            # ingested and ingest finished prematurely when a new report was added.
            targets = [
                r for r in get_all_status(db)
                if r.get("ingest") in ("pending", "failed", "running")
                and r.get("extract") == "completed"
                and (notebook_id is None or r["notebook_id"] == notebook_id)
            ]

            async with httpx.AsyncClient(timeout=60.0) as client:
                async def _embed(text: str) -> list[float]:
                    resp = await client.post(
                        f"{settings.tei_embed_url}/embed",
                        json={"inputs": text, "truncate": True},
                    )
                    resp.raise_for_status()
                    d = resp.json()
                    return d[0] if isinstance(d[0], list) else d

                for row in targets:
                    nid = row["notebook_id"]
                    files = _extraction_files_for(data_dir, nid)
                    if not files:
                        click.echo(f"SKIP {nid}: no extraction")
                        continue

                    set_phase_status(db, nid, "ingest", "running")
                    try:
                        source_name = row.get("source") or "unknown"
                        title = row.get("title") or "untitled"

                        # Bind row-scoped names as defaults (no loop-var late binding).
                        async def _neo4j_write(extraction, _source=source_name):
                            await ingest_extraction(
                                extraction=extraction,
                                source_name=_source,
                                client=client,
                                neo4j_url=settings.neo4j_http_url,
                                neo4j_user=settings.neo4j_user,
                                neo4j_password=settings.neo4j_password,
                            )

                        async def _qdrant_write(extraction, _source=source_name, _title=title):
                            points = []
                            for c in extraction.claims:
                                # skip embed for rejected claims; build_claim_points filters again
                                if c.confidence <= 0.0:
                                    continue
                                vec = await _embed(c.statement)
                                points += build_claim_points(
                                    extraction.model_copy(update={"claims": [c]}),
                                    notebook_title=_title,
                                    embed=lambda _t, _v=vec: _v,
                                    source_name=_source,
                                )
                            await ingest_to_qdrant(qdrant, settings.qdrant_collection, points)

                        ok = await _ingest_one_notebook(
                            files,
                            expected_notebook_id=nid,
                            neo4j_write=_neo4j_write,
                            qdrant_write=_qdrant_write,
                        )
                        set_phase_status(db, nid, "ingest", "completed" if ok else "failed")
                        click.echo(
                            f"{'OK' if ok else 'FAIL'} {nid}: "
                            f"{len(files)} source(s) -> Neo4j + Qdrant"
                        )
                    except Exception as e:
                        set_phase_status(db, nid, "ingest", "failed", error=str(e))
                        click.echo(f"FAIL {nid}: {e}")
        finally:
            # Always release both clients even if ensure_collection raises.
            qdrant.close()
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


def preview_relations(data_dir) -> dict:
    """Pure, read-only aggregator: count canonical/candidate outcomes across all extractions.

    Iterates all extractions/{nid}.*.json files in data_dir, parses each to
    Extraction, runs validate_relations, and returns aggregate counts.  No DB
    writes.  Module-level so tests can import it directly.
    """
    from collections import Counter

    from nlm_ingest.relation_validator import validate_relations
    from nlm_ingest.schemas import Extraction

    canon: Counter[str] = Counter()
    gates: Counter[str] = Counter()
    unresolved = 0
    for fp in sorted(Path(data_dir, "extractions").glob("*.json")):
        ex = Extraction.model_validate(json.loads(fp.read_text()))
        res = validate_relations(ex)
        for c in res.canonical:
            canon[c.rel_type] += 1
        for cand in res.candidates:
            gates[cand.failed_gate] += 1
            if cand.failed_gate == "entity_type_unresolved":
                unresolved += 1
    return {
        "canonical_by_type": dict(canon),
        "candidates_by_gate": dict(gates),
        "unresolved": unresolved,
    }


@cli.command(name="relations-preview")
@click.option("--report", is_flag=True, help="write relation_validation_preview.json")
def relations_preview(report: bool) -> None:
    """Validate relations read-only; print canonical/candidate counts (no writes)."""
    settings = _get_settings()
    data_dir = Path(settings.nlm_data_dir)
    out = preview_relations(data_dir)
    click.echo(json.dumps(out, indent=2, ensure_ascii=False))
    if report:
        (data_dir / "relation_validation_preview.json").write_text(
            json.dumps(out, indent=2, ensure_ascii=False)
        )


@cli.command()
@click.option("--local-only", is_flag=True, help="Only SQLite/files, no Neo4j backfill")
@click.option("--neo4j-only", is_flag=True, help="Only Neo4j edge backfill, no local part")
def migrate(local_only: bool, neo4j_only: bool):
    """One-time migration to the multi-source schema.

    Local part (SQLite/files) and Neo4j backfill are separately runnable (P2#10):
    an unreachable Neo4j does not block the local part.
    """
    if local_only and neo4j_only:
        raise click.UsageError("--local-only and --neo4j-only are mutually exclusive")
    from nlm_ingest.migrate import migrate_neo4j_edges
    settings = _get_settings()

    if not neo4j_only:
        # Auto-migration in _get_db() does the local part (Finding #3) — no second
        # migrate_local call here.
        _get_db().close()
        click.echo("Local migration done.")
    if local_only:
        return

    async def _backfill():
        async with httpx.AsyncClient() as client:
            await migrate_neo4j_edges(
                client, settings.neo4j_http_url,
                settings.neo4j_user, settings.neo4j_password)

    asyncio.run(_backfill())
    click.echo("Neo4j backfill done.")
