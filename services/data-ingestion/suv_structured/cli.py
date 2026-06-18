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

from canonicalize import canonicalize_entity
from config import settings
from suv_structured.backfill_hq import (
    build_hq_link_statements,
    count_location_targets,
    fetch_suv_orgs,
    unmapped_or_ambiguous_targets,
)
from suv_structured.build_companies import (
    _write_name,
    build_qdrant_points,
    build_statements,
    embed_text,
    write_neo4j,
)
from suv_structured.build_equipment import (
    EquipmentBuildGateError,
    build_equipment_statements,
    dedup_systems,
    match_target_counts,
    resolve_equipment_build_inputs,
)
from suv_structured.equipment_parse import parse_weapon_systems
from suv_structured.equipment_schemas import WeaponSystemRow
from suv_structured.fetch import fetch_directory_markdown
from suv_structured.match_report import build_match_report, detect_drift, dump_report, load_approved
from suv_structured.operators import (
    load_operators,
    match_preflight_offenders,
    operators_by_slug,
)
from suv_structured.parse import parse_companies
from suv_structured.schemas import Company, profile_text
from suv_structured.system_types import classify_system_type

DIRECTORY_URL = "https://suv.report/sicherheits-und-verteidigungsindustrie/"
SEED_PATH = Path(__file__).parent / "seeds" / "suv_companies.yaml"

EQUIPMENT_PAGES = {
    "hauptwaffensysteme-des-heeres": "https://suv.report/hauptwaffensysteme-des-heeres/",
    "hauptwaffensysteme-der-luftwaffe": "https://suv.report/hauptwaffensysteme-der-luftwaffe/",
    "hauptwaffensysteme-der-marine": "https://suv.report/hauptwaffensysteme-der-marine/",
    "hauptwaffensysteme-des-cyber-und-informationsraums":
        "https://suv.report/hauptwaffensysteme-des-cyber-und-informationsraums/",
    "hauptwaffensysteme-des-unterstuetzungsbereichs":
        "https://suv.report/hauptwaffensysteme-des-unterstuetzungsbereichs/",
}
EQUIPMENT_SEED = Path(__file__).parent / "seeds" / "suv_equipment.yaml"
OPERATORS_SEED = Path(__file__).parent / "seeds" / "suv_operators.yaml"


def _load_equipment_seed(path: Path) -> list[WeaponSystemRow]:
    return [WeaponSystemRow(**row) for row in (yaml.safe_load(path.read_text()) or [])]


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


@cli.command(name="backfill-hq")
@click.option("--apply", "do_apply", is_flag=True,
              help="Actually write the edges (default is dry-run, no write).")
def backfill_hq(do_apply: bool) -> None:
    """Backfill HEADQUARTERED_IN edges from existing suv.report orgs to Entity{LOCATION}.

    Dry-run by default (prints a summary, no write). Pass --apply to write. A preflight
    requires each mapped country to resolve to exactly one Entity{type:"LOCATION"}."""
    async def _run() -> None:
        kw = dict(neo4j_http_url=settings.neo4j_http_url, neo4j_user=settings.neo4j_user,
                  neo4j_password=settings.neo4j_password)
        async with httpx.AsyncClient(timeout=60.0) as client:
            orgs = await fetch_suv_orgs(client, **kw)
            statements, skipped = build_hq_link_statements(orgs)
            mapped_countries = sorted({s["parameters"]["country"] for s in statements})
            counts = await count_location_targets(client, mapped_countries, **kw)
            offenders = unmapped_or_ambiguous_targets(counts)

            click.echo(f"SUV orgs with hq_country: {len(orgs)}")
            click.echo(f"mapped: {len(statements)}   skipped (unmapped): {len(skipped)}")
            for c in mapped_countries:
                click.echo(f'  {c} -> Entity{{type:"LOCATION"}} count={counts.get(c, 0)}')
            if skipped:
                click.echo(f"  skipped countries: {sorted({hc for _, hc in skipped})}")
            click.echo(f"statements to write: {len(statements)}")

            if offenders:
                raise click.ClickException(
                    "preflight failed — these countries do not resolve to exactly one "
                    f'Entity{{type:"LOCATION"}} node: {offenders}. Aborting (no write).')
            if not do_apply:
                click.echo("DRY-RUN (no write). Re-run with --apply to write the edges.")
                return
            await write_neo4j(statements, client=client, **kw)
            click.echo(f"APPLIED: wrote {len(statements)} HEADQUARTERED_IN edges.")
    asyncio.run(_run())


@cli.group()
def equipment() -> None:
    """SUV Hauptwaffensysteme structured ingestion (Track 2a)."""


@equipment.command("fetch")
def equipment_fetch() -> None:
    """Render all 5 Hauptwaffensysteme sub-pages and print their markdown."""
    async def _run() -> None:
        async with httpx.AsyncClient(timeout=120.0) as client:
            for slug, url in EQUIPMENT_PAGES.items():
                md = await fetch_directory_markdown(
                    url, crawl4ai_url=settings.crawl4ai_url, client=client)
                click.echo(f"===== {slug} ({len(md)} chars) =====")
                click.echo(md)
    asyncio.run(_run())


@equipment.command("parse")
def equipment_parse_cmd() -> None:
    """Render + parse all 5 sub-pages; write the seed snapshot for human review."""
    async def _run() -> None:
        rows: list[WeaponSystemRow] = []
        async with httpx.AsyncClient(timeout=120.0) as client:
            for slug, url in EQUIPMENT_PAGES.items():
                md = await fetch_directory_markdown(
                    url, crawl4ai_url=settings.crawl4ai_url, client=client)
                rows.extend(parse_weapon_systems(md, page_slug=slug, suv_url=url))
        if len(rows) < 30:
            raise click.ClickException(
                f"parse yielded only {len(rows)} systems — likely a shell/error page; "
                "seed NOT written")
        EQUIPMENT_SEED.parent.mkdir(parents=True, exist_ok=True)
        EQUIPMENT_SEED.write_text(
            yaml.safe_dump([r.model_dump() for r in rows], allow_unicode=True, sort_keys=False))
        click.echo(f"wrote {len(rows)} weapon systems -> {EQUIPMENT_SEED}")
    asyncio.run(_run())


@equipment.command("build")
@click.option("--dry-run", is_flag=True, help="Write match_report.yaml; no graph writes.")
@click.option("--approved-matches", "approved_path", type=click.Path(path_type=Path),
              default=None, help="Curated, approved match report (required for real build).")
@click.option("--report-out", type=click.Path(path_type=Path),
              default=Path("equipment_match_report.yaml"),
              help="Where --dry-run writes the report.")
def equipment_build(dry_run: bool, approved_path: Path | None, report_out: Path) -> None:
    """Dry-run produces the weapon-system match report; real run requires --approved-matches."""
    async def _run() -> None:
        if not EQUIPMENT_SEED.exists():
            raise click.ClickException(
                f"no seed at {EQUIPMENT_SEED} — run `odin-suv-structured equipment parse` first")
        rows = _load_equipment_seed(EQUIPMENT_SEED)
        operators = operators_by_slug(load_operators(OPERATORS_SEED))
        unique = dedup_systems(rows)

        def _ttype(item):
            return classify_system_type(item.type_raw, item.muster)

        u, pw = settings.neo4j_user, settings.neo4j_password
        async with httpx.AsyncClient(timeout=60.0) as client:
            if dry_run:
                lookup = await _lookup_existing(unique, client, settings.neo4j_http_url, u, pw,
                                                entity_type="WEAPON_SYSTEM")
                report = build_match_report(
                    unique, lookup, gate_new_creation=True, target_type_of=_ttype)
                dump_report(report, report_out)
                click.echo(f"dry-run: wrote match report -> {report_out}")
                return
            if approved_path is None:
                raise EquipmentBuildGateError(
                    "refusing to build without --approved-matches <report.yaml> "
                    "(run `equipment build --dry-run` first, curate + set approved: true)")
            approved = load_approved(approved_path, gate_new_creation=True)
            resolve_equipment_build_inputs(rows=rows, operators=operators, approved=approved)
            # re-derive against the live graph; abort on drift
            lookup = await _lookup_existing(unique, client, settings.neo4j_http_url, u, pw,
                                            entity_type="WEAPON_SYSTEM")
            fresh = build_match_report(
                unique, lookup, gate_new_creation=True, target_type_of=_ttype)
            drift = detect_drift(approved, fresh)
            if drift:
                raise EquipmentBuildGateError(
                    "graph changed since dry-run — re-run `equipment build --dry-run` "
                    f"+ re-curate: {drift}")
            # operator exactly-1 preflight (match rows only)
            counts = await match_target_counts(
                operators, client, neo4j_http_url=settings.neo4j_http_url,
                neo4j_user=u, neo4j_password=pw)
            offenders = match_preflight_offenders(counts)
            if offenders:
                raise EquipmentBuildGateError(
                    f"operator match preflight failed (not exactly-1): {offenders}")
            from datetime import UTC, datetime
            ts = datetime.now(UTC).isoformat()
            stmts = build_equipment_statements(rows, approved, operators, extracted_at=ts)
            await write_neo4j(stmts, client=client, neo4j_http_url=settings.neo4j_http_url,
                              neo4j_user=u, neo4j_password=pw)
            click.echo(f"built {len(approved)} systems (neo4j stmts={len(stmts)}, qdrant=0)")
    asyncio.run(_run())


async def _lookup_existing(
    companies: list[Company], client: httpx.AsyncClient,
    neo4j_http_url: str, user: str, password: str,
    *, entity_type: str = "ORGANIZATION",
) -> dict[str, list[tuple[str, str, str]]]:
    import base64
    names: list[str] = []
    for c in companies:
        names.append(c.name)
        canon = canonicalize_entity(c.name, entity_type).name
        if canon != c.name:
            names.append(canon)
    names = list(dict.fromkeys(names))  # dedup, preserve order
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
