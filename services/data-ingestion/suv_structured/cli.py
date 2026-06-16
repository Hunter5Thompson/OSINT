# suv_structured/cli.py
"""odin-suv-structured CLI: fetch | parse | build.

build is gated: it refuses without --approved-matches and aborts if the approved
report references companies absent from the seed snapshot (stale/divergent report)."""
from __future__ import annotations

import asyncio
from pathlib import Path

import click
import httpx
import yaml
from qdrant_client import QdrantClient

from config import settings
from suv_structured.build_companies import (
    _write_name,
    build_qdrant_points,
    build_statements,
    embed_text,
    write_neo4j,
)
from suv_structured.fetch import fetch_directory_markdown
from suv_structured.match_report import build_match_report, detect_drift, dump_report, load_approved
from suv_structured.parse import parse_companies
from suv_structured.schemas import Company, profile_text

DIRECTORY_URL = "https://suv.report/sicherheits-und-verteidigungsindustrie/"
SEED_PATH = Path(__file__).parent / "seeds" / "suv_companies.yaml"


class BuildGateError(RuntimeError):
    """Raised when the --approved-matches merge gate is not satisfied."""


def _load_seed(path: Path) -> list[Company]:
    return [Company(**row) for row in (yaml.safe_load(path.read_text()) or [])]


def resolve_build_inputs(
    *, seed_path: Path, approved_path: Path | None
) -> tuple[list[Company], list[dict]]:
    """Enforce the merge gate; return (all companies, approved entries to write)."""
    if approved_path is None:
        raise BuildGateError(
            "refusing to build without --approved-matches <match_report.yaml> "
            "(run `build --dry-run` first, curate + set approved: true)")
    companies = _load_seed(seed_path)
    approved = load_approved(approved_path)            # raises on approved+ambiguous
    seed_names = {c.name for c in companies}
    # name is the authoritative join key: every company shares the directory suv_url,
    # so a url-based check can never detect divergence (it always matches).
    unknown = [e["name"] for e in approved if e["name"] not in seed_names]
    if unknown:
        raise BuildGateError(f"approved report diverges from seed (unknown: {unknown})")
    # No two approved entries may resolve to the SAME canonical write-name — that
    # would silently collapse two SUV companies into one graph node + Qdrant point
    # (the second overwrites the first). Force the operator to resolve it.
    by_name = {c.name: c for c in companies}
    seen_write: dict[str, str] = {}
    collisions: list[str] = []
    for e in approved:
        co = by_name.get(e["name"])
        if co is None:
            continue
        wn = _write_name(co, e)
        if wn in seen_write:
            collisions.append(f"{seen_write[wn]!r} + {e['name']!r} -> {wn!r}")
        else:
            seen_write[wn] = e["name"]
    if collisions:
        raise BuildGateError(
            "multiple approved entries resolve to the same canonical entity "
            f"(would silently merge — resolve before building): {collisions}")
    return companies, approved


@click.group()
def cli() -> None:
    """SUV.report structured ingestion (Track 2)."""


@cli.command()
def fetch() -> None:
    """Render the directory and print markdown (for inspection / piping)."""
    async def _run() -> None:
        async with httpx.AsyncClient(timeout=90.0) as client:
            md = await fetch_directory_markdown(
                DIRECTORY_URL, crawl4ai_url=settings.crawl4ai_url, client=client)
        click.echo(md)
    asyncio.run(_run())


@cli.command()
def parse() -> None:
    """Render + deterministically parse companies; write the seed snapshot for human review."""
    async def _run() -> None:
        async with httpx.AsyncClient(timeout=120.0) as client:
            md = await fetch_directory_markdown(
                DIRECTORY_URL, crawl4ai_url=settings.crawl4ai_url, client=client)
        companies = parse_companies(md)
        if len(companies) < 5:
            raise click.ClickException(
                f"parse yielded only {len(companies)} companies — likely a shell/error "
                "page; seed NOT written")
        SEED_PATH.parent.mkdir(parents=True, exist_ok=True)
        dumped = yaml.safe_dump(
            [c.model_dump() for c in companies], allow_unicode=True, sort_keys=False)
        SEED_PATH.write_text(dumped)
        click.echo(f"wrote {len(companies)} companies -> {SEED_PATH}")
    asyncio.run(_run())


@cli.command()
@click.option("--dry-run", is_flag=True, help="Write match_report.yaml; no graph/Qdrant writes.")
@click.option("--approved-matches", "approved_path", type=click.Path(path_type=Path),
              default=None, help="Curated, approved match report (required for real build).")
@click.option("--report-out", type=click.Path(path_type=Path),
              default=Path("match_report.yaml"), help="Where --dry-run writes the report.")
def build(dry_run: bool, approved_path: Path | None, report_out: Path) -> None:
    """Dry-run produces the match report; real run requires --approved-matches."""
    async def _run() -> None:
        if not SEED_PATH.exists():
            raise click.ClickException(
                f"no seed at {SEED_PATH} — run `odin-suv-structured parse` first")
        companies = _load_seed(SEED_PATH)
        auth_user, auth_pw = settings.neo4j_user, settings.neo4j_password
        async with httpx.AsyncClient(timeout=60.0) as client:
            if dry_run:
                lookup = await _lookup_existing(companies, client, settings.neo4j_http_url,
                                                auth_user, auth_pw)
                dump_report(build_match_report(companies, lookup), report_out)
                click.echo(f"dry-run: wrote match report -> {report_out}")
                return
            _, approved = resolve_build_inputs(seed_path=SEED_PATH, approved_path=approved_path)
            # Re-derive matches against the CURRENT graph; a stale approved report
            # (graph changed since dry-run) must not write wrong merges.
            existing = await _lookup_existing(
                companies, client, settings.neo4j_http_url, auth_user, auth_pw)
            fresh = build_match_report(companies, existing)
            drift = detect_drift(approved, fresh)
            if drift:
                raise BuildGateError(
                    f"graph changed since dry-run — re-run `build --dry-run` + re-curate: {drift}")
            from datetime import UTC, datetime
            ts = datetime.now(UTC).isoformat()
            stmts = build_statements(companies, approved, extracted_at=ts)
            await write_neo4j(stmts, client=client, neo4j_http_url=settings.neo4j_http_url,
                              neo4j_user=auth_user, neo4j_password=auth_pw)
            # Pre-compute embeddings async, then pass a sync lookup as `embed` so
            # build_qdrant_points stays pure + as-tested.
            approved_names = {e["name"] for e in approved}
            vec_by_content: dict[str, list[float]] = {}
            for c in companies:
                if c.name not in approved_names:
                    continue
                content = profile_text(c)
                vec_by_content[content] = await embed_text(
                    content, client=client, tei_embed_url=settings.tei_embed_url)
            points = build_qdrant_points(
                companies, approved, embed=lambda content: vec_by_content[content], now_iso=ts)
            qdrant = QdrantClient(url=settings.qdrant_url)
            if points:
                qdrant.upsert(collection_name=settings.qdrant_collection, points=points)
            click.echo(
                f"built {len(approved)} companies "
                f"(neo4j stmts={len(stmts)}, qdrant={len(points)})")
    asyncio.run(_run())


async def _lookup_existing(
    companies: list[Company], client: httpx.AsyncClient,
    neo4j_http_url: str, user: str, password: str,
) -> dict[str, list[tuple[str, str, str]]]:
    import base64
    names = [c.name for c in companies]
    cypher = ("UNWIND $names AS nm "
              "MATCH (e:Entity) WHERE toLower(e.name) = toLower(nm) "
              "RETURN nm AS query, e.name AS name, e.type AS type, elementId(e) AS id")
    auth = base64.b64encode(f"{user}:{password}".encode()).decode()
    resp = await client.post(
        f"{neo4j_http_url}/db/neo4j/tx/commit",
        json={"statements": [{"statement": cypher, "parameters": {"names": names}}]},
        headers={"Authorization": f"Basic {auth}", "Content-Type": "application/json"})
    resp.raise_for_status()
    data = resp.json()
    if data.get("errors"):
        raise RuntimeError(
            f"Neo4j lookup error: {data['errors'][0].get('message', data['errors'])}")
    out: dict[str, list[tuple[str, str, str]]] = {}
    for row in (data["results"][0]["data"] if data.get("results") else []):
        query, name, etype, eid = row["row"]
        out.setdefault(query.strip().lower(), []).append((name, etype, eid))
    return out
