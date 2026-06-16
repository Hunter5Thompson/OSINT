# SUV HQ Location Bridge Backfill — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Materialize the 77 SUV company→country relationships as `HEADQUARTERED_IN` edges to the existing dominant `Entity{type:"LOCATION"}` nodes (Germany/Netherlands), via a write-template retarget + a separate, dry-run-default backfill migration.

**Architecture:** Retarget `LINK_COMPANY_COUNTRY` from `Entity{type:"COUNTRY"}` to `Entity{type:"LOCATION"}` (a reversible bridge — see spec). A NEW `backfill_hq` migration (NOT a `build` re-run, which the hardened drift-gate would correctly abort) reads the already-written suv.report orgs from the graph, maps `hq_country` via `to_graph_country`, and MERGEs the edges — behind a dry-run default + explicit `--apply` + an exactly-one-LOCATION-target preflight.

**Tech Stack:** Python 3.12, httpx (async), click, structlog, pytest; Neo4j HTTP tx API.

**Spec:** `docs/superpowers/specs/2026-06-16-suv-hq-location-bridge-backfill-design.md`

---

## File Structure
- **Modify** `services/data-ingestion/suv_structured/write_templates.py` — `LINK_COMPANY_COUNTRY` COUNTRY→LOCATION + bridge docstring.
- **Modify** `services/data-ingestion/suv_structured/countries.py` — docstring ADR note (no logic change).
- **Create** `services/data-ingestion/suv_structured/backfill_hq.py` — pure builder + preflight helper + live read helpers.
- **Modify** `services/data-ingestion/suv_structured/cli.py` — `backfill-hq` subcommand.
- **Tests**: `tests/test_suv_write_templates.py` (modify), `tests/test_suv_backfill_hq.py` (create), `tests/test_suv_cli.py` (modify).

---

## Task 1: Retarget `LINK_COMPANY_COUNTRY` to `Entity{type:"LOCATION"}`

**Files:**
- Modify: `services/data-ingestion/suv_structured/write_templates.py`
- Modify: `services/data-ingestion/suv_structured/countries.py`
- Test: `services/data-ingestion/tests/test_suv_write_templates.py`

- [ ] **Step 1: Update the failing test first** (`tests/test_suv_write_templates.py`) — replace `test_link_company_country_is_match_only_for_country` with the LOCATION expectation + label guard:

```python
def test_link_company_country_is_match_only_for_location():
    # Bridge: HQ-country endpoint MATCHes the existing Entity{type:"LOCATION"} node,
    # never a COUNTRY node and never the separate :Location-label node.
    assert "[r:HEADQUARTERED_IN]" in LINK_COMPANY_COUNTRY
    assert 'MATCH (co:Entity {type: "LOCATION"})' in LINK_COMPANY_COUNTRY
    assert 'type: "COUNTRY"' not in LINK_COMPANY_COUNTRY      # no longer targets COUNTRY
    assert "(co:Location" not in LINK_COMPANY_COUNTRY          # never the :Location label node
    assert "MERGE (co" not in LINK_COMPANY_COUNTRY             # MATCH-only endpoint
    assert "MERGE (c)-[r:HEADQUARTERED_IN]->(co)" in LINK_COMPANY_COUNTRY
```

- [ ] **Step 2: Run it, confirm it FAILS**

Run: `cd services/data-ingestion && uv run pytest tests/test_suv_write_templates.py::test_link_company_country_is_match_only_for_location -v`
Expected: FAIL — `'MATCH (co:Entity {type: "LOCATION"})'` not found (template still says COUNTRY).

- [ ] **Step 3: Edit `write_templates.py`** — change line 33 `type: "COUNTRY"` → `type: "LOCATION"`. The block becomes:

```python
LINK_COMPANY_COUNTRY = """
MATCH (c:Entity {name: $name, type: "ORGANIZATION"})
MATCH (co:Entity {type: "LOCATION"}) WHERE toLower(co.name) = toLower($country)
MERGE (c)-[r:HEADQUARTERED_IN]->(co)
ON CREATE SET r.first_seen = datetime(), r.data_source = "suv.report"
SET r.last_seen = datetime()
"""
```

Also update the module docstring's relation line (was "country endpoint MATCH-ed (never MERGE-d)") to:
```
HQ-country endpoint MATCH-ed against the existing Entity{type:"LOCATION"} node
(never MERGE-d, never the :Location-label node) — a reversible tactical bridge,
see docs/superpowers/specs/2026-06-16-suv-hq-location-bridge-backfill-design.md.
```

- [ ] **Step 4: Add the ADR note to `countries.py`** — update the module docstring (no logic change). Append to the existing docstring:
```python
"""Map SUV's German HQ-country strings onto the English names used by the graph's
geo nodes. Unknown/empty/None -> None (relation skipped + reported).

BRIDGE NOTE (2026-06-16): the mapped names (Germany/Netherlands) target the existing
dominant Entity{type:"LOCATION"} nodes via LINK_COMPANY_COUNTRY — a reversible bridge
pending the canonical-country model from graph-integrity-geo. See spec
docs/superpowers/specs/2026-06-16-suv-hq-location-bridge-backfill-design.md."""
```
(Keep `_DE_EN` and `to_graph_country` unchanged.)

- [ ] **Step 5: Run the write-template + countries tests, confirm PASS**

Run: `cd services/data-ingestion && uv run pytest tests/test_suv_write_templates.py tests/test_suv_countries.py -v`
Expected: PASS (all template tests incl. the new LOCATION one; countries unchanged).

- [ ] **Step 6: ruff + commit**

```bash
cd services/data-ingestion && uv run ruff check suv_structured/write_templates.py suv_structured/countries.py tests/test_suv_write_templates.py
git add services/data-ingestion/suv_structured/write_templates.py services/data-ingestion/suv_structured/countries.py services/data-ingestion/tests/test_suv_write_templates.py
git commit -m "feat(suv): HEADQUARTERED_IN targets Entity{LOCATION} (reversible HQ bridge)"
```

---

## Task 2: `backfill_hq.py` — pure statement builder + preflight helper

**Files:**
- Create: `services/data-ingestion/suv_structured/backfill_hq.py`
- Test: `services/data-ingestion/tests/test_suv_backfill_hq.py`

- [ ] **Step 1: Write the failing test** (`tests/test_suv_backfill_hq.py`):

```python
from suv_structured.backfill_hq import (
    build_hq_link_statements,
    unmapped_or_ambiguous_targets,
)


def test_build_hq_link_statements_maps_and_skips():
    rows = [("Rheinmetall", "Deutschland"), ("KNDS", "Niederlande"), ("Skyfall", "Atlantis")]
    statements, skipped = build_hq_link_statements(rows)
    params = [s["parameters"] for s in statements]
    assert {"name": "Rheinmetall", "country": "Germany"} in params
    assert {"name": "KNDS", "country": "Netherlands"} in params
    assert len(statements) == 2
    assert skipped == [("Skyfall", "Atlantis")]          # unmapped -> skipped, not written
    assert all("HEADQUARTERED_IN" in s["statement"] for s in statements)


def test_unmapped_or_ambiguous_targets_flags_non_singletons():
    # exactly-1 target required; 0 (missing) or >1 (fan-out) are offenders
    assert unmapped_or_ambiguous_targets({"Germany": 1, "Netherlands": 1}) == []
    assert unmapped_or_ambiguous_targets({"Germany": 0, "Netherlands": 1}) == ["Germany"]
    assert unmapped_or_ambiguous_targets({"Germany": 2}) == ["Germany"]
```

- [ ] **Step 2: Run it, confirm FAIL** — `ModuleNotFoundError: suv_structured.backfill_hq`.

Run: `cd services/data-ingestion && uv run pytest tests/test_suv_backfill_hq.py -v`

- [ ] **Step 3: Create `backfill_hq.py` (pure core first)**:

```python
"""Backfill HEADQUARTERED_IN edges for already-written suv.report companies onto the
existing Entity{type:"LOCATION"} nodes. A SEPARATE migration — NOT a `build` re-run
(the hardened detect_drift gate would correctly abort, since the once-`new` companies
now exist). Reversible tactical bridge; see the design spec.

Reversal: MATCH ()-[r:HEADQUARTERED_IN {data_source:"suv.report"}]->() DELETE r
"""
from __future__ import annotations

import base64

import httpx
import structlog

from suv_structured.countries import to_graph_country
from suv_structured.write_templates import LINK_COMPANY_COUNTRY

log = structlog.get_logger(__name__)


def build_hq_link_statements(
    org_rows: list[tuple[str, str]],
) -> tuple[list[dict], list[tuple[str, str]]]:
    """(statements, skipped) for org rows (name, german_hq_country).
    Maps the country via to_graph_country; unmapped rows are skipped (not written)."""
    statements: list[dict] = []
    skipped: list[tuple[str, str]] = []
    for name, hq_country in org_rows:
        loc = to_graph_country(hq_country)
        if loc:
            statements.append(
                {"statement": LINK_COMPANY_COUNTRY, "parameters": {"name": name, "country": loc}})
        else:
            skipped.append((name, hq_country))
            log.info("suv_backfill_country_unmapped", company=name, hq=hq_country)
    return statements, skipped


def unmapped_or_ambiguous_targets(counts: dict[str, int]) -> list[str]:
    """Preflight: country names whose Entity{type:"LOCATION"} target count != 1
    (0 = missing, >1 = a toLower MATCH would fan out into multiple edges)."""
    return sorted(name for name, n in counts.items() if n != 1)
```

- [ ] **Step 4: Run the test, confirm PASS** (2 tests).

Run: `cd services/data-ingestion && uv run pytest tests/test_suv_backfill_hq.py -v`

- [ ] **Step 5: ruff + commit**

```bash
cd services/data-ingestion && uv run ruff check suv_structured/backfill_hq.py tests/test_suv_backfill_hq.py
git add services/data-ingestion/suv_structured/backfill_hq.py services/data-ingestion/tests/test_suv_backfill_hq.py
git commit -m "feat(suv): backfill_hq pure statement builder + exactly-1-target preflight"
```

---

## Task 3: `backfill_hq.py` — live Neo4j read helpers

**Files:**
- Modify: `services/data-ingestion/suv_structured/backfill_hq.py`
- Test: `services/data-ingestion/tests/test_suv_backfill_hq.py`

- [ ] **Step 1: Add the failing tests** (append to `tests/test_suv_backfill_hq.py`):

```python
import json

import httpx
import pytest

from suv_structured.backfill_hq import count_location_targets, fetch_suv_orgs


@pytest.mark.asyncio
async def test_fetch_suv_orgs_parses_rows():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"results": [{"data": [
            {"row": ["Rheinmetall", "Deutschland"]},
            {"row": ["KNDS", "Niederlande"]},
        ]}], "errors": []})
    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        rows = await fetch_suv_orgs(client, neo4j_http_url="http://neo",
                                    neo4j_user="neo4j", neo4j_password="pw")
    assert rows == [("Rheinmetall", "Deutschland"), ("KNDS", "Niederlande")]


@pytest.mark.asyncio
async def test_count_location_targets_zero_fills_missing():
    def handler(request: httpx.Request) -> httpx.Response:
        # OPTIONAL MATCH yields a row per requested name; Germany has 1, Atlantis 0
        return httpx.Response(200, json={"results": [{"data": [
            {"row": ["Germany", 1]},
            {"row": ["Atlantis", 0]},
        ]}], "errors": []})
    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        counts = await count_location_targets(client, ["Germany", "Atlantis"],
                                              neo4j_http_url="http://neo",
                                              neo4j_user="neo4j", neo4j_password="pw")
    assert counts == {"Germany": 1, "Atlantis": 0}


@pytest.mark.asyncio
async def test_read_raises_on_neo4j_error_body():
    transport = httpx.MockTransport(lambda r: httpx.Response(
        200, json={"results": [], "errors": [{"message": "boom"}]}))
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(RuntimeError, match="boom"):
            await fetch_suv_orgs(client, neo4j_http_url="http://neo",
                                 neo4j_user="neo4j", neo4j_password="pw")
```

- [ ] **Step 2: Run, confirm FAIL** — `ImportError: cannot import name 'fetch_suv_orgs'`.

- [ ] **Step 3: Append the live helpers to `backfill_hq.py`**:

```python
async def _run_read(
    client: httpx.AsyncClient, cypher: str, params: dict,
    *, neo4j_http_url: str, neo4j_user: str, neo4j_password: str,
) -> list[dict]:
    auth = base64.b64encode(f"{neo4j_user}:{neo4j_password}".encode()).decode()
    resp = await client.post(
        f"{neo4j_http_url}/db/neo4j/tx/commit",
        json={"statements": [{"statement": cypher, "parameters": params}]},
        headers={"Authorization": f"Basic {auth}", "Content-Type": "application/json"})
    resp.raise_for_status()
    data = resp.json()
    if data.get("errors"):
        raise RuntimeError(
            f"Neo4j read error: {data['errors'][0].get('message', data['errors'])}")
    return data["results"][0]["data"] if data.get("results") else []


async def fetch_suv_orgs(
    client: httpx.AsyncClient, *, neo4j_http_url: str, neo4j_user: str, neo4j_password: str,
) -> list[tuple[str, str]]:
    """All suv.report ORGANIZATION nodes that carry an hq_country (read-only)."""
    cypher = ('MATCH (c:Entity {type:"ORGANIZATION"}) '
              'WHERE c.data_source = "suv.report" AND c.hq_country IS NOT NULL '
              'RETURN c.name AS name, c.hq_country AS hq_country ORDER BY name')
    rows = await _run_read(client, cypher, {}, neo4j_http_url=neo4j_http_url,
                           neo4j_user=neo4j_user, neo4j_password=neo4j_password)
    return [(r["row"][0], r["row"][1]) for r in rows]


async def count_location_targets(
    client: httpx.AsyncClient, country_names: list[str],
    *, neo4j_http_url: str, neo4j_user: str, neo4j_password: str,
) -> dict[str, int]:
    """Per requested name, how many Entity{type:"LOCATION"} nodes match (case-insensitive).
    OPTIONAL MATCH guarantees a row per requested name (count 0 when none)."""
    cypher = ('UNWIND $names AS nm '
              'OPTIONAL MATCH (l:Entity {type:"LOCATION"}) WHERE toLower(l.name) = toLower(nm) '
              'RETURN nm AS name, count(l) AS n')
    rows = await _run_read(client, cypher, {"names": country_names},
                           neo4j_http_url=neo4j_http_url, neo4j_user=neo4j_user,
                           neo4j_password=neo4j_password)
    return {r["row"][0]: r["row"][1] for r in rows}
```

- [ ] **Step 4: Run, confirm PASS** (3 new tests + the 2 pure ones = 5).

Run: `cd services/data-ingestion && uv run pytest tests/test_suv_backfill_hq.py -v`

- [ ] **Step 5: ruff + commit**

```bash
cd services/data-ingestion && uv run ruff check suv_structured/backfill_hq.py tests/test_suv_backfill_hq.py
git add services/data-ingestion/suv_structured/backfill_hq.py services/data-ingestion/tests/test_suv_backfill_hq.py
git commit -m "feat(suv): backfill_hq live read helpers (fetch orgs, count location targets)"
```

---

## Task 4: CLI `backfill-hq` subcommand (dry-run default, --apply, preflight)

**Files:**
- Modify: `services/data-ingestion/suv_structured/cli.py`
- Test: `services/data-ingestion/tests/test_suv_cli.py`

- [ ] **Step 1: Write the failing tests** (append to `tests/test_suv_cli.py`; `import json`, `httpx`, `pytest`, `Company`, `CliRunner` already available — add any missing):

```python
def test_backfill_hq_dry_run_default_does_not_write(monkeypatch):
    from click.testing import CliRunner
    import suv_structured.cli as cli_mod

    async def fake_fetch(client, **kw):
        return [("Rheinmetall", "Deutschland"), ("KNDS", "Niederlande")]

    async def fake_counts(client, names, **kw):
        return {n: 1 for n in names}

    wrote = {"called": False}

    async def fake_write(*a, **k):
        wrote["called"] = True

    monkeypatch.setattr(cli_mod, "fetch_suv_orgs", fake_fetch)
    monkeypatch.setattr(cli_mod, "count_location_targets", fake_counts)
    monkeypatch.setattr(cli_mod, "write_neo4j", fake_write)
    result = CliRunner().invoke(cli_mod.cli, ["backfill-hq"])   # no --apply
    assert result.exit_code == 0
    assert wrote["called"] is False                              # dry-run never writes
    assert "DRY-RUN" in result.output
    assert 'Germany -> Entity{type:"LOCATION"} count=1' in result.output


def test_backfill_hq_apply_writes_when_preflight_clean(monkeypatch):
    from click.testing import CliRunner
    import suv_structured.cli as cli_mod

    async def fake_fetch(client, **kw):
        return [("Rheinmetall", "Deutschland")]

    async def fake_counts(client, names, **kw):
        return {n: 1 for n in names}

    wrote = {"n": 0}

    async def fake_write(statements, **k):
        wrote["n"] = len(statements)

    monkeypatch.setattr(cli_mod, "fetch_suv_orgs", fake_fetch)
    monkeypatch.setattr(cli_mod, "count_location_targets", fake_counts)
    monkeypatch.setattr(cli_mod, "write_neo4j", fake_write)
    result = CliRunner().invoke(cli_mod.cli, ["backfill-hq", "--apply"])
    assert result.exit_code == 0
    assert wrote["n"] == 1
    assert "APPLIED" in result.output


def test_backfill_hq_preflight_aborts_on_non_singleton_target(monkeypatch):
    from click.testing import CliRunner
    import suv_structured.cli as cli_mod

    async def fake_fetch(client, **kw):
        return [("Rheinmetall", "Deutschland")]

    async def fake_counts(client, names, **kw):
        return {n: 2 for n in names}     # Germany resolves to 2 LOCATION nodes -> abort

    wrote = {"called": False}

    async def fake_write(*a, **k):
        wrote["called"] = True

    monkeypatch.setattr(cli_mod, "fetch_suv_orgs", fake_fetch)
    monkeypatch.setattr(cli_mod, "count_location_targets", fake_counts)
    monkeypatch.setattr(cli_mod, "write_neo4j", fake_write)
    result = CliRunner().invoke(cli_mod.cli, ["backfill-hq", "--apply"])
    assert result.exit_code != 0
    assert wrote["called"] is False                              # preflight blocks the write
    assert "preflight" in result.output.lower()
```

- [ ] **Step 2: Run, confirm FAIL** — no `backfill-hq` command.

Run: `cd services/data-ingestion && uv run pytest tests/test_suv_cli.py -k backfill -v`

- [ ] **Step 3: Wire the command in `cli.py`** — add imports at top:
```python
from suv_structured.backfill_hq import (
    build_hq_link_statements,
    count_location_targets,
    fetch_suv_orgs,
    unmapped_or_ambiguous_targets,
)
```
Then add the command (after the existing `build` command):
```python
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
```
(Note: `write_neo4j`'s kwargs are `client, neo4j_http_url, neo4j_user, neo4j_password` — the `**kw` dict matches exactly; `client` is passed explicitly.)

- [ ] **Step 4: Run, confirm PASS** (3 backfill tests) + the existing CLI tests still pass.

Run: `cd services/data-ingestion && uv run pytest tests/test_suv_cli.py -v`

- [ ] **Step 5: ruff + commit**

```bash
cd services/data-ingestion && uv run ruff check suv_structured/cli.py tests/test_suv_cli.py
git add services/data-ingestion/suv_structured/cli.py services/data-ingestion/tests/test_suv_cli.py
git commit -m "feat(suv): odin-suv-structured backfill-hq (dry-run default, --apply, exactly-1 preflight)"
```

---

## Task 5: Full suite + lint gate

**Files:** none (verification).

- [ ] **Step 1: data-ingestion suite + lint**

Run: `cd services/data-ingestion && uv run pytest -q && uv run ruff check .`
Expected: all green (existing suite + new backfill/CLI tests); ruff clean. (intelligence untouched — no need to run it.)

- [ ] **Step 2: console script resolves**

Run: `cd services/data-ingestion && uv run odin-suv-structured backfill-hq --help`
Expected: click help showing `--apply`.

- [ ] **Step 3: commit any lint fixups**

```bash
git add -A && git commit -m "chore(suv): lint fixups for backfill-hq" || echo "nothing to commit"
```

---

## Task 6: Operational backfill run (HUMAN-gated apply) — against PROD

**Files:** none (operational). Prereqs: `osint-neo4j-1` healthy; the worktree `.env` carries `NEO4J_PASSWORD` (copy from the main checkout's `services/data-ingestion/.env` if absent).

- [ ] **Step 1: Dry-run + operator review**

```bash
cd services/data-ingestion && uv run odin-suv-structured backfill-hq
```
Confirm the output: ~77 SUV orgs, ~77 mapped (0 unmapped expected — only DE/NL present), `Germany -> Entity{type:"LOCATION"} count=1`, `Netherlands -> Entity{type:"LOCATION"} count=1`, statements ~77. If any country shows count ≠ 1 → STOP (preflight will also abort); investigate the geo duplication before applying.

- [ ] **Step 2: Apply (creates edges; additive + reversible — no backup needed)**

```bash
cd services/data-ingestion && uv run odin-suv-structured backfill-hq --apply
```
Expected: `APPLIED: wrote N HEADQUARTERED_IN edges.`

- [ ] **Step 3: Verify**

```bash
cd services/data-ingestion && uv run python -c "
import asyncio, httpx, base64
from config import settings
async def m():
    cy='MATCH (c:Entity{type:\"ORGANIZATION\", data_source:\"suv.report\"})-[:HEADQUARTERED_IN]->(l:Entity{type:\"LOCATION\"}) RETURN l.name AS n, count(*) AS c ORDER BY c DESC'
    auth=base64.b64encode(f'{settings.neo4j_user}:{settings.neo4j_password}'.encode()).decode()
    async with httpx.AsyncClient() as cl:
        r=await cl.post(f'{settings.neo4j_http_url}/db/neo4j/tx/commit',json={'statements':[{'statement':cy}]},headers={'Authorization':f'Basic {auth}','Content-Type':'application/json'},timeout=20)
        print(r.json()['results'][0]['data'])
asyncio.run(m())
"
```
Expected: `[{'row': ['Germany', 76]}, {'row': ['Netherlands', 1]}]` (≈77 edges).

- [ ] **Reversal (only if needed):**
```cypher
MATCH ()-[r:HEADQUARTERED_IN {data_source:"suv.report"}]->() DELETE r
```

---

## Self-Review
- **Spec coverage:** §1 write-template → Task 1; §2 countries docstring → Task 1 Step 4; §3 backfill module (pure + preflight + live) → Tasks 2–3; §4 CLI (dry-run default, --apply, preflight, per-country target+count output) → Task 4; safety/reversal/no-backup → Task 6 + spec; verification → Task 6 Step 3. ✓
- **Placeholders:** none — every code step shows complete code. ✓
- **Type consistency:** `build_hq_link_statements(rows)->(statements,skipped)`, `unmapped_or_ambiguous_targets(counts)->list[str]`, `fetch_suv_orgs(...)->list[tuple]`, `count_location_targets(...,names,...)->dict`, all used consistently in cli.py; `write_neo4j(statements, *, client, neo4j_http_url, neo4j_user, neo4j_password)` call matches its Task-7 signature from the prior SUV work. ✓
