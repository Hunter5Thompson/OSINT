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
from suv_structured.build_procurements import (
    ProcurementBuildGateError,
    build_procurement_statements,
    subject_candidate,
)
from suv_structured.build_procurements import (
    build_qdrant_points as build_procurement_qdrant_points,
)
from suv_structured.contractors import split_contractors
from suv_structured.equipment_parse import parse_weapon_systems
from suv_structured.equipment_schemas import WeaponSystemRow
from suv_structured.fetch import fetch_directory_markdown
from suv_structured.match_report import build_match_report, detect_drift, dump_report, load_approved
from suv_structured.operators import (
    load_operators,
    match_preflight_offenders,
    operator_for_branch,
    operators_by_slug,
)
from suv_structured.parse import parse_companies
from suv_structured.procurement_parse import parse_procurements
from suv_structured.procurement_schemas import ProcurementProgram
from suv_structured.procurement_schemas import profile_text as program_profile
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

PROCUREMENTS_URL = "https://suv.report/modernisierungsvorhaben/"
PROCUREMENTS_SEED = Path(__file__).parent / "seeds" / "suv_procurements.yaml"


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


class _MatchItem:
    """Minimal item for the procurement match surfaces. Exposes the attributes
    build_match_report/_lookup_existing read (.name, .suv_url) plus the program
    title it belongs to, so the dry-run report entries can be tagged per program."""

    __slots__ = ("name", "suv_url", "program_title")

    def __init__(self, name: str, suv_url: str, program_title: str) -> None:
        self.name = name
        self.suv_url = suv_url
        self.program_title = program_title


_SUBJECT_TYPES = ["WEAPON_SYSTEM", "AIRCRAFT", "VESSEL", "SATELLITE"]


async def _fetch_equipment_node_names(
    client: httpx.AsyncClient, neo4j_http_url: str, user: str, password: str,
) -> tuple[set[str], dict[str, str]]:
    """Fetch ALL existing equipment node names + their types from the graph.

    Returns (names, type_by_name). Mirrors _lookup_existing's httpx/base64/tx-commit
    plumbing. Used by `procurements build` to find subject candidates (the program's
    title/typ mentioning an existing weapon system) and to type the CONCERNS_SYSTEM
    edge correctly. Unlike _lookup_existing this is a full enumeration, not a name probe."""
    import base64
    cypher = ("MATCH (e:Entity) WHERE e.type IN $types "
              "RETURN e.name AS name, e.type AS type")
    auth = base64.b64encode(f"{user}:{password}".encode()).decode()
    resp = await client.post(
        f"{neo4j_http_url}/db/neo4j/tx/commit",
        json={"statements": [{"statement": cypher, "parameters": {"types": _SUBJECT_TYPES}}]},
        headers={"Authorization": f"Basic {auth}", "Content-Type": "application/json"})
    resp.raise_for_status()
    data = resp.json()
    if data.get("errors"):
        raise RuntimeError(
            f"Neo4j equipment-name lookup error: "
            f"{data['errors'][0].get('message', data['errors'])}")
    names: set[str] = set()
    type_by_name: dict[str, str] = {}
    for row in (data["results"][0]["data"] if data.get("results") else []):
        name, etype = row["row"]
        names.add(name)
        type_by_name[name] = etype
    return names, type_by_name


async def _procurement_operator_counts(
    targets: list[tuple[str, str]], client: httpx.AsyncClient,
    *, neo4j_http_url: str, neo4j_user: str, neo4j_password: str,
) -> dict[tuple[str, str], int]:
    """Live node-count per (name, type) for the operators the programs actually use.

    Mirrors build_equipment.match_target_counts' Cypher, but counts EVERY passed target
    (both `match` AND `create` operators) — 2b upserts NO operators, so a `create` operator
    (e.g. CIR) must already exist exactly once for its PROCURES MATCH to bind. Returns
    {(name, type): count} for every target (0 for absent), ready for match_preflight_offenders."""
    import base64
    targets = sorted(set(targets))
    if not targets:
        return {}
    cypher = ("UNWIND $pairs AS p "
              "MATCH (e:Entity {name: p.name, type: p.type}) "
              "RETURN p.name AS name, p.type AS type, count(e) AS c")
    pairs = [{"name": n, "type": t} for n, t in targets]
    auth = base64.b64encode(f"{neo4j_user}:{neo4j_password}".encode()).decode()
    resp = await client.post(
        f"{neo4j_http_url}/db/neo4j/tx/commit",
        json={"statements": [{"statement": cypher, "parameters": {"pairs": pairs}}]},
        headers={"Authorization": f"Basic {auth}", "Content-Type": "application/json"})
    resp.raise_for_status()
    data = resp.json()
    if data.get("errors"):
        msg = data['errors'][0].get('message', data['errors'])
        raise RuntimeError(f"Neo4j operator preflight error: {msg}")
    counts = {(n, t): 0 for n, t in targets}
    for row in (data["results"][0]["data"] if data.get("results") else []):
        name, etype, c = row["row"]
        counts[(name, etype)] = c
    return counts


@cli.group()
def procurements() -> None:
    """SUV Modernisierungsvorhaben structured ingestion (Track 2b)."""


@procurements.command("fetch")
def procurements_fetch() -> None:
    """Render the Modernisierungsvorhaben page and print its markdown."""
    async def _run() -> None:
        async with httpx.AsyncClient(timeout=120.0) as client:
            md = await fetch_directory_markdown(
                PROCUREMENTS_URL, crawl4ai_url=settings.crawl4ai_url, client=client)
        click.echo(md)
    asyncio.run(_run())


@procurements.command("parse")
def procurements_parse_cmd() -> None:
    """Render + parse the Modernisierungsvorhaben page; write the seed for human review."""
    async def _run() -> None:
        async with httpx.AsyncClient(timeout=120.0) as client:
            md = await fetch_directory_markdown(
                PROCUREMENTS_URL, crawl4ai_url=settings.crawl4ai_url, client=client)
        progs = parse_procurements(md, suv_url=PROCUREMENTS_URL)
        if len(progs) < 10:
            raise click.ClickException(
                f"parse yielded only {len(progs)} programs — likely a shell/error page; "
                "seed NOT written")
        PROCUREMENTS_SEED.parent.mkdir(parents=True, exist_ok=True)
        PROCUREMENTS_SEED.write_text(
            yaml.safe_dump([p.model_dump() for p in progs], allow_unicode=True, sort_keys=False))
        click.echo(f"wrote {len(progs)} procurement programs -> {PROCUREMENTS_SEED}")
    asyncio.run(_run())


@procurements.command("build")
@click.option("--dry-run", is_flag=True, help="Write match_report.yaml; no graph/Qdrant writes.")
@click.option("--approved-matches", "approved_path", type=click.Path(path_type=Path),
              default=None, help="Curated, approved match report (required for real build).")
@click.option("--report-out", type=click.Path(path_type=Path),
              default=Path("procurements_match_report.yaml"),
              help="Where --dry-run writes the report.")
def procurements_build(dry_run: bool, approved_path: Path | None, report_out: Path) -> None:
    """Dry-run produces the combined contractor+subject match report; real run requires
    --approved-matches. Real build is Neo4j-FIRST: programs + PROCURES are always written,
    CONTRACTED_TO/CONCERNS_SYSTEM for approved matches, then Qdrant profiles (all programs).

    Two gates guard the real build, both BEFORE any write (drift first, then operator preflight):
      1. Per-kind drift check (contractors + subjects separately, so a contractor and a subject
         sharing a name can't cross-collide in detect_drift's name-keyed map). The fresh
         match-reports are re-derived against the LIVE graph; if any approved entry's decision
         or match target moved/vanished since the dry-run we abort and ask for a re-curate.
         For subjects, an additional target_type drift check is applied: if the live graph now
         types a subject system differently from the approved YAML (e.g. AIRCRAFT→VESSEL),
         LINK_CONCERNS_SYSTEM's $sys_type param would bind the wrong (stale) type and produce no
         edge. This check aborts before any write in that case too.
         This keeps the Qdrant payload (built from the same approved entries) consistent with the
         graph: after a passing drift check every approved match still resolves, so the MATCH-only
         CONTRACTED_TO/CONCERNS_SYSTEM edge IS written for every entity the payload lists.
      2. Exactly-1 operator preflight over EVERY operator the programs actually use (both `match`
         and `create` — 2b upserts no operators, so a `create` operator must already exist exactly
         once). LINK_PROCURES is MATCH-only, so this guarantees no program is silently
         PROCURES-less."""
    async def _run() -> None:
        if not PROCUREMENTS_SEED.exists():
            raise click.ClickException(
                f"no seed at {PROCUREMENTS_SEED} — run "
                "`odin-suv-structured procurements parse` first")
        programs = [
            ProcurementProgram(**row)
            for row in (yaml.safe_load(PROCUREMENTS_SEED.read_text()) or [])
        ]
        # Gate first: refuse a real build with no approved report BEFORE any network work,
        # so the failure is the gate error (not a Neo4j auth error from the lookups below).
        if not dry_run and approved_path is None:
            raise ProcurementBuildGateError(
                "refusing to build without --approved-matches <report.yaml> "
                "(run `procurements build --dry-run` first, curate + set approved: true)")
        u, pw = settings.neo4j_user, settings.neo4j_password
        async with httpx.AsyncClient(timeout=60.0) as client:
            # Build the contractor match items (one per split party per program).
            contractor_items: list[_MatchItem] = []
            for p in programs:
                for party in split_contractors(p.contractor_raw):
                    contractor_items.append(_MatchItem(party, p.suv_url, p.title))

            # Build the subject match items: probe each program title/typ against the full
            # set of existing equipment node names; one item per program that hits a name.
            equip_names, equip_type_by_name = await _fetch_equipment_node_names(
                client, settings.neo4j_http_url, u, pw)
            subject_items: list[_MatchItem] = []
            for p in programs:
                cand = subject_candidate(p, equip_names)
                if cand:
                    subject_items.append(_MatchItem(cand, p.suv_url, p.title))

            # Re-derive the CURRENT-graph match reports for BOTH kinds (shared by dry-run
            # and the real-build drift check, so the real build compares the approved YAML
            # against the live graph as it is RIGHT NOW, not as it was at the dry-run).
            org_lookup = await _lookup_existing(
                contractor_items, client, settings.neo4j_http_url, u, pw)
            equip_lookup = await _lookup_existing(
                subject_items, client, settings.neo4j_http_url, u, pw,
                entity_type="WEAPON_SYSTEM")
            contractor_report = build_match_report(
                contractor_items, org_lookup, target_type="ORGANIZATION")
            for i, entry in enumerate(contractor_report):
                entry["kind"] = "contractor"
                entry["program_title"] = contractor_items[i].program_title
            subject_report = build_match_report(
                subject_items, equip_lookup,
                target_type_of=lambda it: equip_type_by_name[it.name])
            for i, entry in enumerate(subject_report):
                entry["kind"] = "subject"
                entry["program_title"] = subject_items[i].program_title

            if dry_run:
                dump_report(contractor_report + subject_report, report_out)
                click.echo(
                    f"dry-run: wrote match report -> {report_out} "
                    f"(contractors={len(contractor_report)}, subjects={len(subject_report)})")
                return

            # Real build (gate already enforced above: approved_path is not None here).
            approved = load_approved(approved_path, gate_new_creation=False)
            approved_contractors = [e for e in approved if e.get("kind") == "contractor"]
            approved_subjects = [e for e in approved if e.get("kind") == "subject"]

            # GATE 1 — per-kind drift check (BEFORE any write). Contractors and subjects are
            # drift-checked separately against their own fresh report so two entries sharing a
            # name (one ORG contractor, one equipment subject) can't cross-collide in
            # detect_drift's name-keyed map. A stale/retyped/now-ambiguous approved match aborts.
            drift = (detect_drift(approved_contractors, contractor_report)
                     + detect_drift(approved_subjects, subject_report))
            if drift:
                raise ProcurementBuildGateError(
                    "graph changed since dry-run — re-run `procurements build --dry-run` "
                    f"+ re-curate: {drift}")

            # GATE 1b — subject target_type drift check (BEFORE any write). detect_drift only
            # compares decision + existing_name. But LINK_CONCERNS_SYSTEM binds $sys_type from
            # the approved entry's target_type. If the live graph retyped a subject node between
            # the dry-run and now (e.g. AIRCRAFT → VESSEL), the approved target_type is stale:
            # the MATCH (s {name: "XYZ", type: "AIRCRAFT"}) binds nothing → no edge, while the
            # Qdrant system_links payload still lists "XYZ" → graph/Qdrant divergence. Abort.
            fresh_subject_type = {e["name"]: e.get("target_type") for e in subject_report}
            subj_type_drift = sorted({
                e["name"] for e in approved_subjects
                if (e.get("decision") or "").lower() == "match"
                and fresh_subject_type.get(e["name"]) != e.get("target_type")
            })
            if subj_type_drift:
                raise ProcurementBuildGateError(
                    "subject system type changed since dry-run (re-run `procurements build "
                    f"--dry-run` + re-curate): {subj_type_drift}")

            operators_list = load_operators(OPERATORS_SEED)
            # GATE 2 — exactly-1 operator preflight over EVERY operator the programs USE
            # (BEFORE any write). Resolve each program's branch operator early (clean abort
            # instead of failing deep inside build_procurement_statements), collect the distinct
            # (name, type) targets, then count live nodes. match|create both must exist exactly
            # once because LINK_PROCURES is MATCH-only and 2b upserts no operators.
            used_targets: set[tuple[str, str]] = set()
            for p in programs:
                op = operator_for_branch(p.branch, operators_list)
                if op is None:
                    raise ProcurementBuildGateError(
                        f"no operator for branch {p.branch!r} (program {p.title!r}) — "
                        "add a matching page_label row to suv_operators.yaml")
                used_targets.add((op.target_name, op.target_type))
            op_counts = await _procurement_operator_counts(
                sorted(used_targets), client, neo4j_http_url=settings.neo4j_http_url,
                neo4j_user=u, neo4j_password=pw)
            op_offenders = match_preflight_offenders(op_counts)
            if op_offenders:
                raise ProcurementBuildGateError(
                    "operator preflight failed (not exactly-1 live node): "
                    f"{op_offenders}")

            from datetime import UTC, datetime
            ts = datetime.now(UTC).isoformat()
            stmts = build_procurement_statements(
                programs, operators_list,
                approved_contractors=approved_contractors,
                approved_subjects=approved_subjects, extracted_at=ts)
            # Neo4j FIRST — Qdrant strictly after a successful write_neo4j (no Qdrant
            # in an except; if write_neo4j raises, the program never reaches the upsert).
            await write_neo4j(stmts, client=client, neo4j_http_url=settings.neo4j_http_url,
                              neo4j_user=u, neo4j_password=pw)
            # Every program gets a Qdrant profile (not just matched ones). Pre-compute
            # embeddings async, then pass a sync lookup as `embed` so build stays pure.
            vec_by_content: dict[str, list[float]] = {}
            for p in programs:
                content = program_profile(p)
                if content not in vec_by_content:
                    vec_by_content[content] = await embed_text(
                        content, client=client, tei_embed_url=settings.tei_embed_url)
            contractor_links: dict[str, list[str]] = {}
            for e in approved_contractors:
                if (e.get("decision") or "").lower() == "match" and e.get("existing_name"):
                    contractor_links.setdefault(e["program_title"], []).append(e["existing_name"])
            system_links: dict[str, list[str]] = {}
            for e in approved_subjects:
                if (e.get("decision") or "").lower() == "match" and e.get("existing_name"):
                    system_links.setdefault(e["program_title"], []).append(e["existing_name"])
            points = build_procurement_qdrant_points(
                programs, contractor_links=contractor_links, system_links=system_links,
                embed=lambda content: vec_by_content[content], now_iso=ts)
            if points:
                QdrantClient(url=settings.qdrant_url).upsert(
                    collection_name=settings.qdrant_collection, points=points)
            click.echo(
                f"built {len(programs)} programs "
                f"(neo4j stmts={len(stmts)}, qdrant={len(points)}, "
                f"contractor-links={sum(len(v) for v in contractor_links.values())}, "
                f"system-links={sum(len(v) for v in system_links.values())})")
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
