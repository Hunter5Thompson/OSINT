# SUV Track 2 — Slice 1 (Defense Companies) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ingest the ~77-company suv.report defense-industry directory into ODIN as in-place `Entity{type:"ORGANIZATION"}` graph enrichment + agent-queryable Qdrant profiles, via a render→LLM-extract→reviewed-snapshot→deterministic-builder pipeline.

**Architecture:** crawl4ai (HTTP service, JS-rendered) returns the directory markdown → vLLM extracts a validated `List[Company]` → committed `seeds/suv_companies.yaml` (human review gate) → a deterministic, GPU-free builder writes Neo4j (own SUV templates) + Qdrant. Writes to existing entities happen only behind a hard `--approved-matches` gate. The intelligence read-path opens the analysis lane to the new source via `source↔source_type` pair validation.

**Tech Stack:** Python 3.12, Pydantic v2, httpx (async), qdrant-client, structlog, pytest; crawl4ai + TEI + Neo4j (HTTP tx API) + Qdrant as HTTP/clients; vLLM OpenAI-compatible endpoint.

**Spec:** `docs/superpowers/specs/2026-06-14-suv-track2-companies-design.md`

---

## File Structure

**New module `services/data-ingestion/suv_structured/`:**
- `__init__.py` — package marker.
- `schemas.py` — `Company` Pydantic model + profile-text helper.
- `fetch.py` — crawl4ai render wrapper (reuses the `_crawl4ai_md` shape).
- `extract.py` — markdown → `list[Company]` via vLLM (batched, schema-validated).
- `write_templates.py` — deterministic SUV Cypher (`UPSERT_COMPANY`, `LINK_COMPANY_COUNTRY`); **separate** from `nlm_ingest` (that dict is key-locked to `RelationType`).
- `countries.py` — German→graph country-name map for the `HEADQUARTERED_IN` MATCH.
- `match_report.py` — dry-run match-report build/load/validate (the merge gate).
- `build_companies.py` — deterministic builder: Neo4j + Qdrant writers, `--dry-run`/`--approved-matches`.
- `cli.py` — `odin-suv-structured` (`fetch | extract | build`).
- `seeds/suv_companies.yaml` — committed, reviewed snapshot (created operationally in Task 13).

**Modified:**
- `services/intelligence/rag/corpus_policy.py` — analysis-lane pair validation.
- `services/data-ingestion/pyproject.toml` — console script + hatch include.
- `services/data-ingestion/Dockerfile` — COPY the module.

**Tests:** under `services/data-ingestion/tests/` and `services/intelligence/tests/`, plus fixtures under `services/data-ingestion/tests/fixtures/suv/`.

---

## Task 0: Walking skeleton — verify crawl4ai renders the companies (GATE)

This is a spike, **not** TDD. Everything else depends on its outcome. Do not proceed to Task 1 until the rendered markdown demonstrably contains real company rows.

**Files:**
- Create: `services/data-ingestion/tests/fixtures/suv/industry_rendered.md` (captured output)
- Create: `services/data-ingestion/tests/fixtures/suv/SHAPES.md` (notes)

- [ ] **Step 1: Call crawl4ai `/md` against the directory and capture output**

Run (deps must be up: `docker ps` shows `crawl4ai-crawl4ai-1`):
```bash
curl -s -m 60 -X POST http://localhost:11235/md \
  -H 'Content-Type: application/json' \
  -d '{"url":"https://suv.report/sicherheits-und-verteidigungsindustrie/","f":"fit"}' \
  | python3 -c 'import sys,json; print(json.load(sys.stdin).get("markdown","")[:4000])'
```
Expected: company names (e.g. "Rheinmetall", "Hensoldt", "Diehl") with HQ/employees/revenue appear in the markdown.

- [ ] **Step 2: Decision gate**

- If company rows are present → save the full markdown to `tests/fixtures/suv/industry_rendered.md`, note the structure in `SHAPES.md`, proceed to Task 1.
- If only the page shell appears (AJAX not awaited) → retry via crawl4ai's full crawl endpoint with a wait condition:
```bash
curl -s -m 90 -X POST http://localhost:11235/crawl \
  -H 'Content-Type: application/json' \
  -d '{"urls":["https://suv.report/sicherheits-und-verteidigungsindustrie/"],"crawler_config":{"wait_for":"css:.company, .entry, [data-id]","page_timeout":45000}}' \
  | python3 -c 'import sys,json; d=json.load(sys.stdin); print(json.dumps(d,indent=2)[:2000])'
```
Record the working request shape in `SHAPES.md`. If neither renders the data, STOP and escalate (fallback = reverse-engineer `admin-ajax.php`; re-scope with the user).

- [ ] **Step 3: Commit the fixture + shapes**

```bash
git add services/data-ingestion/tests/fixtures/suv/
git commit -m "test(suv): capture crawl4ai-rendered industry fixture + SHAPES"
```

---

## Task 1: `Company` schema

**Files:**
- Create: `services/data-ingestion/suv_structured/__init__.py` (empty)
- Create: `services/data-ingestion/suv_structured/schemas.py`
- Test: `services/data-ingestion/tests/test_suv_schemas.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_suv_schemas.py
import pytest
from pydantic import ValidationError

from suv_structured.schemas import Company, profile_text


def test_company_minimal_requires_name_and_url():
    c = Company(name="Rheinmetall AG", suv_url="https://suv.report/rheinmetall/")
    assert c.name == "Rheinmetall AG"
    assert c.products == [] and c.aliases == []


def test_company_rejects_missing_name():
    with pytest.raises(ValidationError):
        Company(suv_url="https://suv.report/x/")


def test_company_coerces_numeric_strings():
    c = Company(name="X", suv_url="u", employees="34000", revenue_eur="9900000000", founded="1889")
    assert c.employees == 34000
    assert c.revenue_eur == 9_900_000_000.0
    assert c.founded == 1889


def test_profile_text_includes_key_fields():
    c = Company(name="Hensoldt", suv_url="u", hq_country="Deutschland",
                hq_city="Taufkirchen", employees=6500, products=["TRML-4D", "Spexer"])
    t = profile_text(c)
    assert "Hensoldt" in t and "Deutschland" in t and "TRML-4D" in t and "6500" in t
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd services/data-ingestion && uv run pytest tests/test_suv_schemas.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'suv_structured'`.

- [ ] **Step 3: Write minimal implementation**

```python
# suv_structured/schemas.py
"""Pydantic model for one SUV defense-industry company + profile-text helper."""
from __future__ import annotations

from pydantic import BaseModel, field_validator


class Company(BaseModel):
    name: str
    suv_url: str
    aliases: list[str] = []
    hq_country: str | None = None   # raw SUV string (German), e.g. "Deutschland"
    hq_city: str | None = None
    employees: int | None = None
    revenue_eur: float | None = None
    founded: int | None = None      # year
    website: str | None = None
    products: list[str] = []
    description: str | None = None

    @field_validator("name")
    @classmethod
    def _name_nonempty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("company name must be non-empty")
        return v


def profile_text(c: Company) -> str:
    """Human-readable profile used as the Qdrant `content` (what gets embedded)."""
    parts = [f"{c.name} — Rüstungs-/Verteidigungsunternehmen."]
    loc = ", ".join(p for p in (c.hq_city, c.hq_country) if p)
    if loc:
        parts.append(f"Hauptsitz: {loc}.")
    if c.employees is not None:
        parts.append(f"Mitarbeiter: {c.employees}.")
    if c.revenue_eur is not None:
        parts.append(f"Umsatz: {c.revenue_eur:.0f} EUR.")
    if c.founded is not None:
        parts.append(f"Gegründet: {c.founded}.")
    if c.products:
        parts.append(f"Produkte: {', '.join(c.products)}.")
    if c.description:
        parts.append(c.description)
    return " ".join(parts)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd services/data-ingestion && uv run pytest tests/test_suv_schemas.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add services/data-ingestion/suv_structured/__init__.py services/data-ingestion/suv_structured/schemas.py services/data-ingestion/tests/test_suv_schemas.py
git commit -m "feat(suv): Company schema + profile_text helper"
```

---

## Task 2: `fetch.py` — crawl4ai render wrapper

**Files:**
- Create: `services/data-ingestion/suv_structured/fetch.py`
- Test: `services/data-ingestion/tests/test_suv_fetch.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_suv_fetch.py
import httpx
import pytest

from suv_structured.fetch import fetch_directory_markdown


@pytest.mark.asyncio
async def test_fetch_returns_markdown_from_md_endpoint():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/md"
        return httpx.Response(200, json={"markdown": "## Rheinmetall AG\nMitarbeiter: 34000"})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        md = await fetch_directory_markdown(
            "https://suv.report/x/", crawl4ai_url="http://c", client=client)
    assert "Rheinmetall" in md


@pytest.mark.asyncio
async def test_fetch_raises_on_empty_render():
    transport = httpx.MockTransport(lambda r: httpx.Response(200, json={"markdown": "   "}))
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(ValueError):
            await fetch_directory_markdown("u", crawl4ai_url="http://c", client=client)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd services/data-ingestion && uv run pytest tests/test_suv_fetch.py -v`
Expected: FAIL — `ModuleNotFoundError: suv_structured.fetch`.

- [ ] **Step 3: Write minimal implementation**

```python
# suv_structured/fetch.py
"""Render the SUV directory via the crawl4ai HTTP service (JS executed server-side).

crawl4ai is consumed as a service (no Python/browser dependency), mirroring
feeds/_fulltext_fetch._crawl4ai_md. The `/md` fit endpoint runs a headless
browser; Task 0 confirmed it returns the AJAX-rendered company rows."""
from __future__ import annotations

import httpx
import structlog

log = structlog.get_logger(__name__)

_FIT_KEYS = ("fit_markdown", "markdown")


async def fetch_directory_markdown(
    url: str, *, crawl4ai_url: str, client: httpx.AsyncClient
) -> str:
    """POST to crawl4ai /md and return the fit markdown. Raises ValueError if empty."""
    resp = await client.post(f"{crawl4ai_url.rstrip('/')}/md", json={"url": url, "f": "fit"})
    resp.raise_for_status()
    data = resp.json()
    for k in _FIT_KEYS:
        v = data.get(k)
        if isinstance(v, str) and v.strip():
            log.info("suv_directory_rendered", url=url, chars=len(v))
            return v
    raise ValueError(f"crawl4ai returned no markdown for {url}")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd services/data-ingestion && uv run pytest tests/test_suv_fetch.py -v`
Expected: PASS (2 tests). (`pytest-asyncio` is already used across the suite; `asyncio_mode` is configured.)

- [ ] **Step 5: Commit**

```bash
git add services/data-ingestion/suv_structured/fetch.py services/data-ingestion/tests/test_suv_fetch.py
git commit -m "feat(suv): crawl4ai directory fetch wrapper"
```

---

## Task 3: `extract.py` — markdown → `list[Company]` via vLLM (batched)

**Files:**
- Create: `services/data-ingestion/suv_structured/extract.py`
- Test: `services/data-ingestion/tests/test_suv_extract.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_suv_extract.py
import json

import httpx
import pytest

from suv_structured.extract import extract_companies


def _llm_response(companies: list[dict]) -> httpx.Response:
    content = json.dumps({"companies": companies})
    return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})


@pytest.mark.asyncio
async def test_extract_parses_companies_and_validates():
    payload = [
        {"name": "Rheinmetall AG", "suv_url": "https://suv.report/rheinmetall/",
         "hq_country": "Deutschland", "employees": 34000, "products": ["Leopard 2"]},
        {"name": "Hensoldt", "suv_url": "https://suv.report/hensoldt/"},
    ]
    transport = httpx.MockTransport(lambda r: _llm_response(payload))
    async with httpx.AsyncClient(transport=transport) as client:
        companies = await extract_companies(
            "## directory markdown", client=client,
            vllm_url="http://v", vllm_model="qwen3.5", batch_chars=10_000)
    assert [c.name for c in companies] == ["Rheinmetall AG", "Hensoldt"]
    assert companies[0].employees == 34000


@pytest.mark.asyncio
async def test_extract_skips_invalid_rows_not_whole_batch():
    payload = [
        {"name": "", "suv_url": "u"},                      # invalid: empty name
        {"name": "Diehl", "suv_url": "https://suv.report/diehl/"},
    ]
    transport = httpx.MockTransport(lambda r: _llm_response(payload))
    async with httpx.AsyncClient(transport=transport) as client:
        companies = await extract_companies(
            "md", client=client, vllm_url="http://v", vllm_model="m", batch_chars=10_000)
    assert [c.name for c in companies] == ["Diehl"]


@pytest.mark.asyncio
async def test_extract_strips_code_fences():
    fenced = "```json\n" + json.dumps({"companies": [{"name": "X", "suv_url": "u"}]}) + "\n```"
    transport = httpx.MockTransport(
        lambda r: httpx.Response(200, json={"choices": [{"message": {"content": fenced}}]}))
    async with httpx.AsyncClient(transport=transport) as client:
        companies = await extract_companies(
            "md", client=client, vllm_url="http://v", vllm_model="m", batch_chars=10_000)
    assert companies[0].name == "X"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd services/data-ingestion && uv run pytest tests/test_suv_extract.py -v`
Expected: FAIL — `ModuleNotFoundError: suv_structured.extract`.

- [ ] **Step 3: Write minimal implementation**

```python
# suv_structured/extract.py
"""LLM extraction: rendered directory markdown -> validated list[Company].

The directory is large, so it is split into character-bounded batches; each batch
is extracted independently and the validated results concatenated. Invalid rows
are dropped (logged) — never the whole batch. No LLM touches the write path; this
output is reviewed as a committed snapshot before any graph/Qdrant write."""
from __future__ import annotations

import json

import httpx
import structlog
from pydantic import ValidationError

from suv_structured.schemas import Company

log = structlog.get_logger(__name__)

_PROMPT = """You extract structured records of defense-industry companies from the \
markdown below (a directory page from suv.report). Return ONLY valid JSON of the form \
{{"companies": [{{"name": str, "suv_url": str, "hq_country": str|null, "hq_city": str|null, \
"employees": int|null, "revenue_eur": number|null, "founded": int|null, "website": str|null, \
"products": [str], "description": str|null}}]}}. \
`suv_url` is the company's own suv.report link if present, else the directory URL. \
`revenue_eur` must be a number in euros (convert "9,9 Mrd. €" -> 9900000000). \
Do not invent values; use null when unknown. Markdown:\n\n{body}"""


def _batches(markdown: str, batch_chars: int) -> list[str]:
    lines, cur, size, out = markdown.splitlines(keepends=True), [], 0, []
    for ln in lines:
        if size + len(ln) > batch_chars and cur:
            out.append("".join(cur)); cur, size = [], 0
        cur.append(ln); size += len(ln)
    if cur:
        out.append("".join(cur))
    return out or [markdown]


async def _extract_batch(
    body: str, *, client: httpx.AsyncClient, vllm_url: str, vllm_model: str
) -> list[Company]:
    payload = {
        "model": vllm_model,
        "messages": [{"role": "user", "content": _PROMPT.format(body=body)}],
        "temperature": 0.1,
        "max_tokens": 4000,
        "chat_template_kwargs": {"enable_thinking": False},
    }
    resp = await client.post(f"{vllm_url}/v1/chat/completions", json=payload, timeout=120.0)
    resp.raise_for_status()
    content = resp.json()["choices"][0]["message"]["content"].strip()
    if content.startswith("```"):
        content = content.split("\n", 1)[1].rsplit("```", 1)[0]
    rows = json.loads(content).get("companies", [])
    companies: list[Company] = []
    for row in rows:
        try:
            companies.append(Company(**row))
        except ValidationError as exc:
            log.warning("suv_extract_row_invalid", row=row, error=str(exc))
    return companies


async def extract_companies(
    markdown: str, *, client: httpx.AsyncClient, vllm_url: str, vllm_model: str,
    batch_chars: int = 14_000,
) -> list[Company]:
    """Extract all companies, de-duplicated by suv_url (first occurrence wins)."""
    seen: set[str] = set()
    result: list[Company] = []
    for batch in _batches(markdown, batch_chars):
        for c in await _extract_batch(
            batch, client=client, vllm_url=vllm_url, vllm_model=vllm_model):
            if c.suv_url in seen:
                continue
            seen.add(c.suv_url)
            result.append(c)
    log.info("suv_extract_done", count=len(result))
    return result
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd services/data-ingestion && uv run pytest tests/test_suv_extract.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add services/data-ingestion/suv_structured/extract.py services/data-ingestion/tests/test_suv_extract.py
git commit -m "feat(suv): batched LLM company extraction (validated, row-resilient)"
```

---

## Task 4: `countries.py` — German→graph country-name map

**Files:**
- Create: `services/data-ingestion/suv_structured/countries.py`
- Test: `services/data-ingestion/tests/test_suv_countries.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_suv_countries.py
from suv_structured.countries import to_graph_country


def test_maps_common_german_country_names():
    assert to_graph_country("Deutschland") == "Germany"
    assert to_graph_country("Frankreich") == "France"
    assert to_graph_country("USA") == "United States"
    assert to_graph_country("Vereinigte Staaten") == "United States"


def test_unknown_country_returns_none():
    assert to_graph_country("Atlantis") is None
    assert to_graph_country(None) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd services/data-ingestion && uv run pytest tests/test_suv_countries.py -v`
Expected: FAIL — `ModuleNotFoundError: suv_structured.countries`.

- [ ] **Step 3: Write minimal implementation**

```python
# suv_structured/countries.py
"""Map SUV's German HQ-country strings onto the English country names used as
Entity{type:"COUNTRY"} in the graph. Unknown -> None (relation skipped + reported)."""
from __future__ import annotations

_DE_EN: dict[str, str] = {
    "deutschland": "Germany",
    "frankreich": "France",
    "usa": "United States",
    "vereinigte staaten": "United States",
    "vereinigtes königreich": "United Kingdom",
    "großbritannien": "United Kingdom",
    "italien": "Italy",
    "spanien": "Spain",
    "schweden": "Sweden",
    "norwegen": "Norway",
    "niederlande": "Netherlands",
    "schweiz": "Switzerland",
    "österreich": "Austria",
    "polen": "Poland",
    "israel": "Israel",
    "türkei": "Türkiye",
    "finnland": "Finland",
    "belgien": "Belgium",
    "tschechien": "Czechia",
}


def to_graph_country(name: str | None) -> str | None:
    if not name:
        return None
    return _DE_EN.get(name.strip().lower())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd services/data-ingestion && uv run pytest tests/test_suv_countries.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add services/data-ingestion/suv_structured/countries.py services/data-ingestion/tests/test_suv_countries.py
git commit -m "feat(suv): German->graph country-name map"
```

---

## Task 5: `write_templates.py` — deterministic SUV Cypher

**Files:**
- Create: `services/data-ingestion/suv_structured/write_templates.py`
- Test: `services/data-ingestion/tests/test_suv_write_templates.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_suv_write_templates.py
from suv_structured.write_templates import LINK_COMPANY_COUNTRY, UPSERT_COMPANY


def test_upsert_company_is_org_typed_and_alias_append_dedup():
    assert 'MERGE (c:Entity {name: $name, type: "ORGANIZATION"})' in UPSERT_COMPANY
    # aliases appended + de-duplicated, never overwritten
    assert "coalesce(c.aliases, [])" in UPSERT_COMPANY
    # nullable scalars preserved on null param (no blind clobber)
    assert "c.hq_country = coalesce($hq_country, c.hq_country)" in UPSERT_COMPANY
    assert 'c.sector = "defense"' in UPSERT_COMPANY


def test_link_company_country_is_match_only_for_country():
    assert "[r:HEADQUARTERED_IN]" in LINK_COMPANY_COUNTRY
    # country endpoint is MATCH-ed, never MERGE-d (no phantom countries)
    assert 'MATCH (co:Entity {type: "COUNTRY"})' in LINK_COMPANY_COUNTRY
    assert "MERGE (co" not in LINK_COMPANY_COUNTRY
    assert "MERGE (c)-[r:HEADQUARTERED_IN]->(co)" in LINK_COMPANY_COUNTRY
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd services/data-ingestion && uv run pytest tests/test_suv_write_templates.py -v`
Expected: FAIL — `ModuleNotFoundError: suv_structured.write_templates`.

- [ ] **Step 3: Write minimal implementation**

```python
# suv_structured/write_templates.py
"""Deterministic Cypher for SUV structured ingestion.

Kept SEPARATE from nlm_ingest/write_templates.py:RELATION_TEMPLATES — that dict is
key-locked to nlm_ingest.schemas.RelationType by tests/test_nlm_relations.py. SUV
adds HEADQUARTERED_IN without touching the NLM RelationType contract.

Rules (Two-Loop write path): no LLM-generated Cypher, all values parameter-bound,
relationship labels hardcoded, country endpoint MATCH-ed (never MERGE-d), existing
properties preserved on null (coalesce) and aliases append-deduplicated."""

UPSERT_COMPANY = """
MERGE (c:Entity {name: $name, type: "ORGANIZATION"})
ON CREATE SET c.first_seen = datetime()
SET c.aliases = coalesce(c.aliases, []) +
        [a IN $aliases WHERE NOT a IN coalesce(c.aliases, [])],
    c.hq_country = coalesce($hq_country, c.hq_country),
    c.hq_city = coalesce($hq_city, c.hq_city),
    c.employees = coalesce($employees, c.employees),
    c.revenue_eur = coalesce($revenue_eur, c.revenue_eur),
    c.founded = coalesce($founded, c.founded),
    c.website = coalesce($website, c.website),
    c.products = CASE WHEN size($products) > 0 THEN $products ELSE c.products END,
    c.sector = "defense",
    c.suv_url = $suv_url,
    c.data_source = "suv.report",
    c.suv_extracted_at = $extracted_at,
    c.last_seen = datetime()
"""

LINK_COMPANY_COUNTRY = """
MATCH (c:Entity {name: $name, type: "ORGANIZATION"})
MATCH (co:Entity {type: "COUNTRY"}) WHERE toLower(co.name) = toLower($country)
MERGE (c)-[r:HEADQUARTERED_IN]->(co)
ON CREATE SET r.first_seen = datetime(), r.data_source = "suv.report"
"""
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd services/data-ingestion && uv run pytest tests/test_suv_write_templates.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add services/data-ingestion/suv_structured/write_templates.py services/data-ingestion/tests/test_suv_write_templates.py
git commit -m "feat(suv): deterministic write templates (UPSERT_COMPANY, HEADQUARTERED_IN)"
```

---

## Task 6: `match_report.py` — dry-run match report (the merge gate's data)

**Files:**
- Create: `services/data-ingestion/suv_structured/match_report.py`
- Test: `services/data-ingestion/tests/test_suv_match_report.py`

The report classifies each company against existing graph entities. `build_match_report` takes the companies and a lookup result (`name -> list of (existing_name, type, id)`) — kept pure (no I/O) so it is fully unit-testable; the live Neo4j read is injected in Task 7.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_suv_match_report.py
from suv_structured.match_report import build_match_report, load_approved, MatchDecision
from suv_structured.schemas import Company


def _co(name, url="u"):
    return Company(name=name, suv_url=url)


def test_classifies_new_match_and_ambiguous():
    companies = [_co("Rheinmetall AG"), _co("Hensoldt"), _co("Diehl")]
    lookup = {
        "rheinmetall ag": [("Rheinmetall", "ORGANIZATION", "e1")],   # single org -> match
        "hensoldt": [],                                              # none -> new
        "diehl": [("Diehl", "ORGANIZATION", "e2"),
                  ("Diehl", "PERSON", "e3")],                        # multiple -> ambiguous
    }
    report = build_match_report(companies, lookup)
    by_name = {r["name"]: r for r in report}
    assert by_name["Rheinmetall AG"]["decision"] == MatchDecision.MATCH
    assert by_name["Rheinmetall AG"]["existing_name"] == "Rheinmetall"
    assert by_name["Hensoldt"]["decision"] == MatchDecision.NEW
    assert by_name["Diehl"]["decision"] == MatchDecision.AMBIGUOUS
    assert all(r["approved"] is False for r in report)


def test_type_mismatch_single_nonorg_is_ambiguous():
    report = build_match_report([_co("Airbus")],
                                {"airbus": [("Airbus", "PERSON", "e9")]})
    assert report[0]["decision"] == MatchDecision.AMBIGUOUS


def test_load_approved_keeps_only_approved_match_and_new(tmp_path):
    import yaml
    report = [
        {"name": "A", "suv_url": "ua", "decision": "match", "existing_name": "A0",
         "candidates": [], "approved": True},
        {"name": "B", "suv_url": "ub", "decision": "new", "existing_name": None,
         "candidates": [], "approved": True},
        {"name": "C", "suv_url": "uc", "decision": "ambiguous", "existing_name": None,
         "candidates": [], "approved": False},
    ]
    p = tmp_path / "match_report.yaml"
    p.write_text(yaml.safe_dump(report))
    approved = load_approved(p)
    assert {a["name"] for a in approved} == {"A", "B"}


def test_load_approved_rejects_approved_but_ambiguous(tmp_path):
    import yaml, pytest
    p = tmp_path / "r.yaml"
    p.write_text(yaml.safe_dump([
        {"name": "C", "suv_url": "uc", "decision": "ambiguous", "existing_name": None,
         "candidates": [], "approved": True}]))
    with pytest.raises(ValueError):
        load_approved(p)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd services/data-ingestion && uv run pytest tests/test_suv_match_report.py -v`
Expected: FAIL — `ModuleNotFoundError: suv_structured.match_report`.

- [ ] **Step 3: Write minimal implementation**

```python
# suv_structured/match_report.py
"""Dry-run match report: classify each SUV company against existing graph entities.

Pure classification (build_match_report) + YAML load/validate (load_approved).
The report is the human review artifact and the machine-checkable merge gate."""
from __future__ import annotations

from enum import StrEnum
from pathlib import Path

import yaml

from suv_structured.schemas import Company


class MatchDecision(StrEnum):
    MATCH = "match"        # exactly one existing ORGANIZATION with this name
    NEW = "new"           # no existing entity with this name
    AMBIGUOUS = "ambiguous"  # multiple matches, or a single non-ORGANIZATION match


def build_match_report(
    companies: list[Company],
    lookup: dict[str, list[tuple[str, str, str]]],
) -> list[dict]:
    """lookup maps lowercased company name -> [(existing_name, type, elementId), ...]."""
    report: list[dict] = []
    for c in companies:
        rows = lookup.get(c.name.strip().lower(), [])
        orgs = [r for r in rows if r[1] == "ORGANIZATION"]
        if not rows:
            decision, existing = MatchDecision.NEW, None
        elif len(rows) == 1 and len(orgs) == 1:
            decision, existing = MatchDecision.MATCH, orgs[0][0]
        else:
            decision, existing = MatchDecision.AMBIGUOUS, None
        report.append({
            "name": c.name,
            "suv_url": c.suv_url,
            "decision": str(decision),
            "existing_name": existing,
            "candidates": [{"name": n, "type": t, "id": i} for n, t, i in rows],
            "approved": False,
        })
    return report


def dump_report(report: list[dict], path: Path) -> None:
    path.write_text(yaml.safe_dump(report, allow_unicode=True, sort_keys=False))


def load_approved(path: Path) -> list[dict]:
    """Load report; return only approved entries. Raises if an approved entry is
    still ambiguous (a human must resolve ambiguity before approving)."""
    entries = yaml.safe_load(path.read_text()) or []
    approved = [e for e in entries if e.get("approved") is True]
    bad = [e["name"] for e in approved if e.get("decision") == str(MatchDecision.AMBIGUOUS)]
    if bad:
        raise ValueError(f"approved but still ambiguous (resolve first): {bad}")
    return approved
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd services/data-ingestion && uv run pytest tests/test_suv_match_report.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add services/data-ingestion/suv_structured/match_report.py services/data-ingestion/tests/test_suv_match_report.py
git commit -m "feat(suv): dry-run match report + approved-entry validation"
```

---

## Task 7: `build_companies.py` — Neo4j writer + statement builder

**Files:**
- Create: `services/data-ingestion/suv_structured/build_companies.py`
- Test: `services/data-ingestion/tests/test_suv_build_neo4j.py`

`build_statements` is pure (companies + approved-name resolution → Neo4j HTTP statements). The country MATCH uses `to_graph_country`; unmapped HQ → no relation statement (logged). The canonical write name comes from the approved report (`existing_name` for matches) else the SUV name via `canonicalize_entity`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_suv_build_neo4j.py
from suv_structured.build_companies import build_statements
from suv_structured.schemas import Company


def _co(**kw):
    kw.setdefault("suv_url", "u")
    return Company(**kw)


def test_match_uses_approved_existing_name():
    companies = [_co(name="Rheinmetall AG", hq_country="Deutschland", products=["Leopard 2"])]
    approved = [{"name": "Rheinmetall AG", "decision": "match", "existing_name": "Rheinmetall"}]
    stmts = build_statements(companies, approved, extracted_at="2026-06-14T00:00:00+00:00")
    upserts = [s for s in stmts if "MERGE (c:Entity" in s["statement"]]
    assert upserts[0]["parameters"]["name"] == "Rheinmetall"          # approved canonical
    assert upserts[0]["parameters"]["products"] == ["Leopard 2"]
    assert "Rheinmetall AG" in upserts[0]["parameters"]["aliases"]    # SUV spelling kept as alias
    links = [s for s in stmts if "HEADQUARTERED_IN" in s["statement"]]
    assert links[0]["parameters"]["country"] == "Germany"            # DE->EN mapped


def test_new_uses_canonicalized_suv_name_and_skips_unmapped_country():
    companies = [_co(name="Skyfall GmbH", hq_country="Atlantis")]
    approved = [{"name": "Skyfall GmbH", "decision": "new", "existing_name": None}]
    stmts = build_statements(companies, approved, extracted_at="t")
    assert any(s["parameters"].get("name") == "Skyfall GmbH"
               for s in stmts if "MERGE (c:Entity" in s["statement"])
    assert not [s for s in stmts if "HEADQUARTERED_IN" in s["statement"]]  # Atlantis unmapped


def test_only_approved_companies_are_written():
    companies = [_co(name="A"), _co(name="B", suv_url="ub")]
    approved = [{"name": "A", "decision": "new", "existing_name": None}]
    stmts = build_statements(companies, approved, extracted_at="t")
    names = {s["parameters"]["name"] for s in stmts if "MERGE (c:Entity" in s["statement"]}
    assert names == {"A"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd services/data-ingestion && uv run pytest tests/test_suv_build_neo4j.py -v`
Expected: FAIL — `ModuleNotFoundError: suv_structured.build_companies`.

- [ ] **Step 3: Write minimal implementation**

```python
# suv_structured/build_companies.py
"""Deterministic builder: approved companies -> Neo4j statements + Qdrant points.

No LLM, no GPU. Writes only companies present (and approved) in the match report."""
from __future__ import annotations

import base64

import httpx
import structlog

from canonicalize import canonicalize_entity
from suv_structured.countries import to_graph_country
from suv_structured.schemas import Company
from suv_structured.write_templates import LINK_COMPANY_COUNTRY, UPSERT_COMPANY

log = structlog.get_logger(__name__)


def _write_name(company: Company, approved_entry: dict) -> str:
    """Match -> approved existing canonical name; new -> canonicalized SUV name."""
    if approved_entry.get("decision") == "match" and approved_entry.get("existing_name"):
        return approved_entry["existing_name"]
    return canonicalize_entity(company.name, "ORGANIZATION").name


def build_statements(
    companies: list[Company], approved: list[dict], *, extracted_at: str
) -> list[dict]:
    """Build Neo4j HTTP-API statements for approved companies only."""
    by_url = {c.suv_url: c for c in companies}
    by_name = {c.name: c for c in companies}
    statements: list[dict] = []
    for entry in approved:
        company = by_url.get(entry.get("suv_url")) or by_name.get(entry["name"])
        if company is None:
            log.warning("suv_build_approved_without_company", entry=entry)
            continue
        name = _write_name(company, entry)
        aliases = sorted({company.name, name, *company.aliases})
        statements.append({
            "statement": UPSERT_COMPANY,
            "parameters": {
                "name": name,
                "aliases": aliases,
                "hq_country": company.hq_country,
                "hq_city": company.hq_city,
                "employees": company.employees,
                "revenue_eur": company.revenue_eur,
                "founded": company.founded,
                "website": company.website,
                "products": company.products,
                "suv_url": company.suv_url,
                "extracted_at": extracted_at,
            },
        })
        country = to_graph_country(company.hq_country)
        if country:
            statements.append({
                "statement": LINK_COMPANY_COUNTRY,
                "parameters": {"name": name, "country": country},
            })
        else:
            log.info("suv_country_unmapped", company=name, hq=company.hq_country)
    return statements


async def write_neo4j(
    statements: list[dict], *, client: httpx.AsyncClient,
    neo4j_http_url: str, neo4j_user: str, neo4j_password: str,
) -> None:
    if not statements:
        return
    auth = base64.b64encode(f"{neo4j_user}:{neo4j_password}".encode()).decode()
    resp = await client.post(
        f"{neo4j_http_url}/db/neo4j/tx/commit",
        json={"statements": statements},
        headers={"Authorization": f"Basic {auth}", "Content-Type": "application/json"},
        timeout=60.0,
    )
    resp.raise_for_status()
    errors = resp.json().get("errors", [])
    if errors:
        raise RuntimeError(f"Neo4j returned {len(errors)} error(s): {errors[0].get('message','')}")
    log.info("suv_neo4j_written", statements=len(statements))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd services/data-ingestion && uv run pytest tests/test_suv_build_neo4j.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add services/data-ingestion/suv_structured/build_companies.py services/data-ingestion/tests/test_suv_build_neo4j.py
git commit -m "feat(suv): Neo4j statement builder + HTTP writer (approved-only)"
```

---

## Task 8: Qdrant profile points (embed + payload)

**Files:**
- Modify: `services/data-ingestion/suv_structured/build_companies.py`
- Test: `services/data-ingestion/tests/test_suv_build_qdrant.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_suv_build_qdrant.py
from suv_structured.build_companies import build_qdrant_points
from suv_structured.schemas import Company


def test_qdrant_payload_has_dataset_provenance_no_credibility():
    companies = [Company(name="Hensoldt", suv_url="https://suv.report/hensoldt/",
                         hq_country="Deutschland", products=["TRML-4D"])]
    approved = [{"name": "Hensoldt", "decision": "new", "existing_name": None}]
    points = build_qdrant_points(companies, approved, embed=lambda t: [0.1] * 1024,
                                 now_iso="2026-06-14T00:00:00+00:00")
    p = points[0]
    assert len(p.vector) == 1024
    assert p.payload["source"] == "suv_structured"
    assert p.payload["source_type"] == "dataset"
    assert p.payload["provider"] == "suv.report"
    assert "credibility" not in p.payload                  # read-side only
    assert p.payload["entities"] == [{"name": "Hensoldt"}]
    assert "TRML-4D" in p.payload["content"]


def test_qdrant_point_id_is_deterministic():
    c = [Company(name="X", suv_url="https://suv.report/x/")]
    a = [{"name": "X", "decision": "new", "existing_name": None}]
    id1 = build_qdrant_points(c, a, embed=lambda t: [0.0] * 1024, now_iso="t")[0].id
    id2 = build_qdrant_points(c, a, embed=lambda t: [0.0] * 1024, now_iso="t")[0].id
    assert id1 == id2


def test_only_approved_get_points():
    companies = [Company(name="A", suv_url="ua"), Company(name="B", suv_url="ub")]
    approved = [{"name": "A", "suv_url": "ua", "decision": "new", "existing_name": None}]
    points = build_qdrant_points(companies, approved, embed=lambda t: [0.0] * 1024, now_iso="t")
    assert len(points) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd services/data-ingestion && uv run pytest tests/test_suv_build_qdrant.py -v`
Expected: FAIL — `ImportError: cannot import name 'build_qdrant_points'`.

- [ ] **Step 3: Write minimal implementation (append to `build_companies.py`)**

```python
# --- append to suv_structured/build_companies.py ---
import hashlib
import uuid
from collections.abc import Callable
from datetime import UTC, datetime

from qdrant_client.models import PointStruct

from feeds.provenance import provenance_fields
from suv_structured.schemas import profile_text

SUV_QDRANT_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, "odin/suv_structured/odin_intel")


def _point_id(suv_url: str) -> str:
    return str(uuid.uuid5(SUV_QDRANT_NAMESPACE, suv_url))


def build_qdrant_points(
    companies: list[Company], approved: list[dict],
    *, embed: Callable[[str], list[float]], now_iso: str | None = None,
) -> list[PointStruct]:
    ts = now_iso or datetime.now(UTC).isoformat()
    by_url = {c.suv_url: c for c in companies}
    by_name = {c.name: c for c in companies}
    points: list[PointStruct] = []
    for entry in approved:
        company = by_url.get(entry.get("suv_url")) or by_name.get(entry["name"])
        if company is None:
            continue
        content = profile_text(company)
        payload = {
            "source": "suv_structured",
            **provenance_fields(source_type="dataset", provider="suv.report"),
            "ingested_at": ts,
            "title": company.name,
            "content": content,
            "entities": [{"name": company.name}],
            "url": company.suv_url,
            "content_hash": hashlib.sha256(content.encode()).hexdigest()[:16],
        }
        points.append(PointStruct(
            id=_point_id(company.suv_url), vector=embed(content), payload=payload))
    return points


async def embed_text(text: str, *, client: httpx.AsyncClient, tei_embed_url: str) -> list[float]:
    """TEI /embed returns a list of vectors; a single string input -> one vector."""
    resp = await client.post(f"{tei_embed_url.rstrip('/')}/embed", json={"inputs": text})
    resp.raise_for_status()
    return resp.json()[0]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd services/data-ingestion && uv run pytest tests/test_suv_build_qdrant.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add services/data-ingestion/suv_structured/build_companies.py services/data-ingestion/tests/test_suv_build_qdrant.py
git commit -m "feat(suv): Qdrant profile points (dataset provenance, no credibility)"
```

---

## Task 9: `cli.py` — fetch | extract | build, with the hard `--approved-matches` gate

**Files:**
- Create: `services/data-ingestion/suv_structured/cli.py`
- Test: `services/data-ingestion/tests/test_suv_cli.py`

`cli.py` is a `click` group (matching `infra_atlas.cli:cli` / `nlm_ingest.cli:cli`). The gate logic lives in a pure helper `resolve_build_inputs` so it is unit-testable without live services; `build` wires it to Neo4j/Qdrant.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_suv_cli.py
import pytest
import yaml

from suv_structured.cli import resolve_build_inputs, BuildGateError
from suv_structured.schemas import Company


def _seed(tmp_path, companies):
    p = tmp_path / "suv_companies.yaml"
    p.write_text(yaml.safe_dump([c.model_dump() for c in companies], allow_unicode=True))
    return p


def test_build_refuses_without_approved_matches(tmp_path):
    seed = _seed(tmp_path, [Company(name="A", suv_url="ua")])
    with pytest.raises(BuildGateError, match="approved-matches"):
        resolve_build_inputs(seed_path=seed, approved_path=None)


def test_build_aborts_when_report_diverges_from_seed(tmp_path):
    seed = _seed(tmp_path, [Company(name="A", suv_url="ua")])
    report = tmp_path / "r.yaml"
    report.write_text(yaml.safe_dump([
        {"name": "GHOST", "suv_url": "uX", "decision": "new",
         "existing_name": None, "candidates": [], "approved": True}]))
    with pytest.raises(BuildGateError, match="diverge|unknown"):
        resolve_build_inputs(seed_path=seed, approved_path=report)


def test_build_returns_companies_and_approved_on_valid_gate(tmp_path):
    seed = _seed(tmp_path, [Company(name="A", suv_url="ua"), Company(name="B", suv_url="ub")])
    report = tmp_path / "r.yaml"
    report.write_text(yaml.safe_dump([
        {"name": "A", "suv_url": "ua", "decision": "new", "existing_name": None,
         "candidates": [], "approved": True},
        {"name": "B", "suv_url": "ub", "decision": "ambiguous", "existing_name": None,
         "candidates": [], "approved": False}]))
    companies, approved = resolve_build_inputs(seed_path=seed, approved_path=report)
    assert {c.name for c in companies} == {"A", "B"}
    assert {a["name"] for a in approved} == {"A"}     # only approved+unambiguous
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd services/data-ingestion && uv run pytest tests/test_suv_cli.py -v`
Expected: FAIL — `ModuleNotFoundError: suv_structured.cli`.

- [ ] **Step 3: Write minimal implementation**

```python
# suv_structured/cli.py
"""odin-suv-structured CLI: fetch | extract | build.

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
    build_qdrant_points, build_statements, embed_text, write_neo4j)
from suv_structured.extract import extract_companies
from suv_structured.fetch import fetch_directory_markdown
from suv_structured.match_report import build_match_report, dump_report, load_approved
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
    seed_urls = {c.suv_url for c in companies}
    seed_names = {c.name for c in companies}
    unknown = [e["name"] for e in approved
               if e.get("suv_url") not in seed_urls and e["name"] not in seed_names]
    if unknown:
        raise BuildGateError(f"approved report diverges from seed (unknown: {unknown})")
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
def extract() -> None:
    """Render + extract companies; write the seed snapshot for human review."""
    async def _run() -> None:
        async with httpx.AsyncClient(timeout=120.0) as client:
            md = await fetch_directory_markdown(
                DIRECTORY_URL, crawl4ai_url=settings.crawl4ai_url, client=client)
            companies = await extract_companies(
                md, client=client, vllm_url=settings.vllm_url, vllm_model=settings.vllm_model)
        SEED_PATH.parent.mkdir(parents=True, exist_ok=True)
        SEED_PATH.write_text(
            yaml.safe_dump([c.model_dump() for c in companies], allow_unicode=True, sort_keys=False))
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
            from datetime import UTC, datetime
            ts = datetime.now(UTC).isoformat()
            stmts = build_statements(companies, approved, extracted_at=ts)
            await write_neo4j(stmts, client=client, neo4j_http_url=settings.neo4j_http_url,
                              neo4j_user=auth_user, neo4j_password=auth_pw)
            # Pre-compute embeddings async (small N), then pass a sync lookup as `embed`
            # so build_qdrant_points stays pure + as-tested.
            vec_by_content: dict[str, list[float]] = {}
            for c in companies:
                content = profile_text(c)
                vec_by_content[content] = await embed_text(
                    content, client=client, tei_embed_url=settings.tei_embed_url)
            points = build_qdrant_points(
                companies, approved, embed=lambda content: vec_by_content[content], now_iso=ts)
            qdrant = QdrantClient(url=settings.qdrant_url)
            if points:
                qdrant.upsert(collection_name=settings.qdrant_collection, points=points)
            click.echo(f"built {len(approved)} companies (neo4j stmts={len(stmts)}, qdrant={len(points)})")
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
    out: dict[str, list[tuple[str, str, str]]] = {}
    for row in resp.json()["results"][0]["data"]:
        query, name, etype, eid = row["row"]
        out.setdefault(query.strip().lower(), []).append((name, etype, eid))
    return out
```

> **Note for the implementer:** only `resolve_build_inputs` is unit-tested here; `build` and `_lookup_existing` are exercised live in the Task 13 operational run. The `build` embed wiring pre-computes TEI vectors async into `vec_by_content`, then passes a synchronous dict-lookup `embed` so `build_qdrant_points` keeps the exact signature its tests pin. Do not change that tested signature.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd services/data-ingestion && uv run pytest tests/test_suv_cli.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add services/data-ingestion/suv_structured/cli.py services/data-ingestion/tests/test_suv_cli.py
git commit -m "feat(suv): CLI (fetch|extract|build) with hard --approved-matches gate"
```

---

## Task 10: Intelligence read-path — analysis-lane pair validation

**Files:**
- Modify: `services/intelligence/rag/corpus_policy.py:18` (ANALYSIS_SOURCES), `:95` (replace `_ANALYSIS_TYPES`), `:111-114` (validate_lane analysis branch)
- Test: `services/intelligence/tests/test_corpus_policy_suv.py`

- [ ] **Step 1: Write the failing test**

```python
# services/intelligence/tests/test_corpus_policy_suv.py
from rag.corpus_policy import ANALYSIS_SOURCES, validate_lane


def _r(**kw):
    return kw


def test_suv_structured_in_analysis_sources():
    assert "suv_structured" in ANALYSIS_SOURCES


def test_keeps_valid_analysis_pairs():
    rows = [
        _r(source="rss", source_type="rss"),
        _r(source="rss_fulltext", source_type="rss"),
        _r(source="suv_structured", source_type="dataset"),
        _r(notebook_id="nb1", source_type="notebooklm"),
        _r(source="rss"),                       # legacy None source_type
    ]
    assert validate_lane(rows, "analysis") == rows


def test_drops_mismatched_pairs():
    rows = [
        _r(source="rss", source_type="dataset"),         # leak attempt -> drop
        _r(source="suv_structured", source_type="rss"),  # wrong type -> drop
        _r(source="rss", source_type="gdelt"),           # existing AC-2 -> still drop
        _r(source="firms", source_type="dataset"),       # not an analysis source -> drop
    ]
    assert validate_lane(rows, "analysis") == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd services/intelligence && uv run pytest tests/test_corpus_policy_suv.py -v`
Expected: FAIL — `assert "suv_structured" in ANALYSIS_SOURCES` and pair drops fail (current code allows `rss`/anything-in-_ANALYSIS_TYPES).

- [ ] **Step 3: Write minimal implementation**

Edit `services/intelligence/rag/corpus_policy.py`:

Replace line 18:
```python
ANALYSIS_SOURCES: frozenset[str] = frozenset({"rss", "rss_fulltext", "suv_structured"})
```

Replace the `_ANALYSIS_TYPES` definition (line ~95) with the pair map:
```python
# Canonical source -> expected source_type for the analysis lane (PAIR validation).
# Independent identity/type checks would let {source:"rss", source_type:"dataset"} leak,
# and many dataset collectors (firms/usgs/…) stamp source_type="dataset".
# NLM points carry no analysis `source`; identified by notebook_id, expected "notebooklm".
_ANALYSIS_SOURCE_TYPE: dict[str, str] = {
    "rss": "rss",
    "rss_fulltext": "rss",
    "suv_structured": "dataset",
}
assert set(_ANALYSIS_SOURCE_TYPE) == ANALYSIS_SOURCES  # keep in lock-step
```

Replace the analysis branch in `validate_lane` (lines ~112-114):
```python
        if lane == "analysis":
            src = r.get("source")
            if src in ANALYSIS_SOURCES:
                expected = _ANALYSIS_SOURCE_TYPE[src]
                ok = st is None or st == expected
            elif r.get("notebook_id"):
                ok = st is None or st == "notebooklm"
            else:
                ok = False
```

Then grep for the removed name and fix any stragglers:
```bash
cd services/intelligence && grep -rn "_ANALYSIS_TYPES" rag/ tests/
```
Update any test that referenced `_ANALYSIS_TYPES` to the new map/behavior.

- [ ] **Step 4: Run tests to verify they pass (and no regression)**

Run: `cd services/intelligence && uv run pytest tests/test_corpus_policy_suv.py tests/ -k corpus -v`
Expected: PASS — new tests green; existing corpus-policy tests still green.

- [ ] **Step 5: Commit**

```bash
git add services/intelligence/rag/corpus_policy.py services/intelligence/tests/test_corpus_policy_suv.py
git commit -m "feat(intel): open analysis lane to suv_structured via source/type pair validation"
```

---

## Task 11: Packaging & wiring

**Files:**
- Modify: `services/data-ingestion/pyproject.toml` (`[project.scripts]`, `[tool.hatch.build.targets.wheel].include`)
- Modify: `services/data-ingestion/Dockerfile` (COPY block, ~`:25`)

- [ ] **Step 1: Add the console script**

In `pyproject.toml [project.scripts]`, after `odin-infra-atlas = ...`:
```toml
odin-suv-structured = "suv_structured.cli:cli"
```

- [ ] **Step 2: Add the hatch wheel includes**

In `[tool.hatch.build.targets.wheel].include`, after the `infra_atlas/**` entries:
```toml
  "suv_structured/**/*.py",
  "suv_structured/seeds/*.yaml",
```

- [ ] **Step 3: Add the Dockerfile COPY**

In `services/data-ingestion/Dockerfile`, after the `infra_atlas/` COPY line:
```dockerfile
COPY services/data-ingestion/suv_structured/ suv_structured/
```

- [ ] **Step 4: Verify the package resolves + the console script is wired**

Run:
```bash
cd services/data-ingestion && uv sync && uv run odin-suv-structured --help
```
Expected: click help listing `fetch`, `extract`, `build`.

- [ ] **Step 5: Commit**

```bash
git add services/data-ingestion/pyproject.toml services/data-ingestion/Dockerfile
git commit -m "build(suv): wire console script, hatch include, Dockerfile COPY"
```

---

## Task 12: Full suite + lint gate (both services)

**Files:** none (verification task)

- [ ] **Step 1: Run the data-ingestion suite + lint**

Run:
```bash
cd services/data-ingestion && uv run pytest -q && uv run ruff check .
```
Expected: all green (new SUV tests + existing suite); ruff clean.

- [ ] **Step 2: Run the intelligence suite + lint**

Run:
```bash
cd services/intelligence && uv run pytest -q && uv run ruff check .
```
Expected: all green (incl. new corpus-policy tests); ruff clean.

- [ ] **Step 3: Commit any lint fixes**

```bash
git add -A && git commit -m "chore(suv): ruff + test fixups across data-ingestion + intelligence" || echo "nothing to commit"
```

---

## Task 13: Operational run — snapshot, dry-run, approve, build, verify (merge gate)

**Files:**
- Create (data artifact): `services/data-ingestion/suv_structured/seeds/suv_companies.yaml`

This task runs against **live** services and **writes to the production graph + Qdrant**. It is the human merge gate. Prereqs: `docker ps` shows crawl4ai, qdrant, neo4j, tei-embed, and a vLLM (9B) healthy; `.env` has `NEO4J_PASSWORD`.

- [ ] **Step 1: Generate + review the seed snapshot**

```bash
cd services/data-ingestion && uv run odin-suv-structured extract
```
Open `suv_structured/seeds/suv_companies.yaml`, eyeball all ~77 rows (names, revenue magnitudes, products). Fix any obvious LLM errors by hand. Commit:
```bash
git add services/data-ingestion/suv_structured/seeds/suv_companies.yaml
git commit -m "data(suv): reviewed company seed snapshot (~77 companies)"
```

- [ ] **Step 2: Dry-run the match report**

```bash
cd services/data-ingestion && uv run odin-suv-structured build --dry-run --report-out match_report.yaml
```
Expected: `match_report.yaml` with one entry per company (`decision: match|new|ambiguous`).

- [ ] **Step 3: Curate + approve the report**

For each entry: confirm `match` targets the right existing entity; resolve every `ambiguous` (pick a canonical, or add a curated alias to `canonicalize.py:_ALIAS_GROUPS` and re-run dry-run); set `approved: true` only on the entries you want written. Leave anything unresolved as `approved: false`.

- [ ] **Step 4: Real build behind the gate**

```bash
cd services/data-ingestion && uv run odin-suv-structured build --approved-matches match_report.yaml
```
Expected: `built N companies (neo4j stmts=…, qdrant=…)`. (Without `--approved-matches` it must refuse — verify once.)

- [ ] **Step 5: Verify graph + Qdrant + agent read-path**

```bash
# Qdrant: suv_structured points present
curl -s http://localhost:6333/collections/odin_intel/points/count \
  -H 'Content-Type: application/json' \
  -d '{"filter":{"must":[{"key":"source","match":{"value":"suv_structured"}}]},"exact":true}'
# Neo4j: companies linked to countries
#   MATCH (c:Entity{type:"ORGANIZATION"})-[:HEADQUARTERED_IN]->(co:Entity{type:"COUNTRY"})
#   WHERE c.data_source="suv.report" RETURN c.name, co.name LIMIT 10;
```
Then ask the ReAct agent a company question (e.g. *"Standort und Umsatz von Hensoldt?"*) and confirm a SUV-sourced answer comes back via the analysis lane. Record results in the task session notes.

---

## Self-Review

**1. Spec coverage:**
- §2 4-stage pipeline → Tasks 0,2,3,7,8 (+cli Task 9). ✓
- §3 enrich-in-place, no `:Company`, targeted SET, alias append-dedup → Task 5 template + Task 7 builder. ✓
- §3 mandatory dry-run + hard `--approved-matches` gate → Tasks 6, 9, 13. ✓
- §4 HEADQUARTERED_IN in `suv_structured` (not nlm_ingest), MATCH-only country; products as property; geo non-goal → Tasks 5, 7 + countries Task 4. ✓
- §5 Qdrant payload (dataset provenance, no credibility, deterministic id) → Task 8. ✓
- §5 read-path pair validation + tests → Task 10. ✓
- §6 provenance via `provenance_fields` → Task 8. ✓
- §7 packaging (script, hatch, Dockerfile) → Task 11. ✓
- §8 TDD coverage → every code task is test-first. ✓
- §9 implementation order (walking-skeleton → tests → module → lane → merge-gate) → Task order 0→13. ✓

**2. Placeholder scan:** No "TBD/TODO/handle edge cases" left as instructions; every code step shows code. The one inline-wiring note in Task 9 is flagged explicitly and does not affect the tested surface. ✓

**3. Type consistency:** `Company` fields are identical across schemas/extract/build/cli. `build_qdrant_points(companies, approved, *, embed, now_iso)` and `build_statements(companies, approved, *, extracted_at)` signatures match their tests and the CLI call sites. `resolve_build_inputs(seed_path, approved_path)` matches Task 9 tests. `to_graph_country` / `profile_text` / `_point_id` consistent. ✓

---

## Execution Handoff

(Filled in by the writing-plans skill after save.)
