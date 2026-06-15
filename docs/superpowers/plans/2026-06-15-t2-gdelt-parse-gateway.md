# T2 — gdelt_raw Parse-Gateway Integrity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A single GDELT row with a null/empty primary key (or a type-corrupt cell on the fallback path) must never destroy a whole slice's Documents + Mentions + Qdrant vectors, and `parse_error_pct` must account for every quarantined/coerced row (closes WP-02 High and WP-12 Low).

**Architecture:** "Quarantine at the gateway + defense-in-depth + skip-and-log writers" (per spec `docs/superpowers/specs/2026-06-15-writepath-graph-integrity-fixes-design.md`, section T2). Four layers, each independently tested: (1) the **parser** diverts null/empty-key rows to the quarantine JSONL on **both** the strict and fallback paths and counts them into `parse_error_pct`; (2) the parser also counts post-fallback type-coerced nulls in non-id typed columns (`event_root_code`) so the 5% gate can see them (WP-12); (3) the **filter** drops null `gkg_record_id` before `unique()` and tightens its post-join invariant to also assert `doc_id` is non-null; (4) the **Neo4j + Qdrant writers** validate each row in a try/except, skip-and-log rejects, and continue — one bad row can no longer raise before the batch write. No migration is needed (see "Repair / no-migration" below).

**Tech Stack:** Python 3.12, `uv`, `pytest`/`pytest-asyncio`, polars, pydantic v2, `qdrant-client`, neo4j async bolt driver, structlog. Neo4j 5 **Community** (Pydantic writer contracts replace NOT-NULL/NODE-KEY constraints — `gdelt_raw/schemas.py:1-5`).

---

## Background: the verified defect chain (read before implementing)

WP-02 (High / DATA_LOSS) — a single GKG row with an empty leading `GKGRecordID`:
1. `parser.py:59` `null_values=[""]` turns the empty key into polars `null` on **both** the strict path (no error — empty→null is silent, so fallback is never triggered) and the fallback path.
2. `filter.py:93` `pl.concat([...]).unique(subset=["gkg_record_id"])` keeps the null (null counts as a value); `map_elements(build_doc_id, ...)` at `:118-120` skips null input → `doc_id = null`; the `n_unique("gkg_record_id") != height` invariant at `:135` passes (null counted as one value).
3. The null-`doc_id` row is written to **parquet** (`canonicalize_gkg`).
4. `neo4j_writer.py:202` `GDELTDocumentWrite.model_validate(r)` raises `ValidationError` on `doc_id=None` (pattern `^gdelt:gkg:\S+$`) **before any doc is written** — the whole `write_docs` batch is lost. `qdrant_writer.py:145` `qdrant_point_id_for_doc(None)` → `uuid5(NAMESPACE_URL, None)` raises `TypeError` before the single end-of-loop upsert — the whole vector batch is lost.
5. `run.py:143-144` already advanced `last_slice["parquet"]`; `recovery.py` re-reads the same poisoned parquet, re-fails forever → "recoverable" state but **permanent loss**.

WP-12 (Low / SILENT_SKIP) — on the fallback path (`ignore_errors=True`, `parser.py:99-107`), a row with the right tab count but a non-integer token in a typed column (e.g. `event_root_code` Int32, or `global_event_id` Int64) is **null-coerced** instead of quarantined. Tab-count-only quarantine means these are **not** counted in `parse_error_pct`, so the 5% gate (`run.py:70`, `config.py:18`) can't see them. A null-coerced `event_root_code` silently drops a possibly-tactical event from `tactical_ids`; a null `global_event_id` row silently vanishes via `is_in`.

Stream → primary-key column (confirmed in `gdelt_raw/polars_schemas.py`):
- events (`EVENT_COLUMNS[0]`): `global_event_id` (Int64)
- mentions (`MENTION_COLUMNS[0]`): `global_event_id` (Int64)
- gkg (`GKG_COLUMNS[0]`): `gkg_record_id` (Utf8)

### Repair / no-migration (important scoping decision — do NOT author a migration in T2)

The failure mode is **loss, not corruption** — no bad data was ever written to Neo4j/Qdrant. So T2 needs **no data migration**. Already-stranded slices (parquet on disk, stores incomplete) become **replayable** precisely because Task 4/5 make the writers skip-and-log: re-running the writer over an old poisoned parquet now skips the null-`doc_id` row and writes every valid row. The actual replay *trigger* — the "replay incomplete slices" command — is a **T5/WP-10** deliverable (T5 runs after T2 in the tranche order T1→T2→T3→T5→T4). T2's job is forward-prevention + making the existing parquet replayable; it does not ship the replay command. If you find yourself writing a migration script, stop — that is out of scope for this tranche.

---

## File Structure

Run all commands from `services/data-ingestion/` unless noted.

- **Modify** `gdelt_raw/parser.py` — add `type_coerced_count` to `ParseResult`; add `_quarantine_null_keys` + `_count_type_coerced` helpers; thread an `id_column` arg through `_parse_stream`; apply the null-key gate uniformly to the strict **and** fallback dataframes; `parse_events`/`parse_mentions`/`parse_gkg` pass their key column.
- **Modify** `gdelt_raw/filter.py` — `drop_nulls(subset=["gkg_record_id"])` before the `unique()` at `:93`; tighten the post-join invariant at `:135` to also assert `doc_id` null-count == 0.
- **Modify** `gdelt_raw/writers/neo4j_writer.py` — add `_validate_rows` skip-and-log helper (import `ValidationError`); `write_from_parquet` validates each row, skips+logs rejects, continues.
- **Modify** `gdelt_raw/writers/qdrant_writer.py` — guard the per-row `doc_id` against null/empty in `upsert_from_parquet`: skip+log, continue.
- **Modify** `tests/test_gdelt_parser.py` — Task 1 + Task 2 red tests.
- **Modify** `tests/test_gdelt_filter.py` — Task 3 red test.
- **Modify** `tests/test_gdelt_neo4j_writer.py` — Task 4 red tests.
- **Modify** `tests/test_gdelt_qdrant_writer.py` — Task 5 red test.
- **Create** `tests/test_gdelt_parse_gateway_e2e.py` — Task 6 acceptance test (parse → filter → canonicalize → mocked writers).

---

## Task 1: Parser null-key gateway quarantine (WP-02)

**Files:**
- Modify: `gdelt_raw/parser.py`
- Test: `tests/test_gdelt_parser.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_gdelt_parser.py` (the module already imports `parse_events`; add `parse_gkg`):

```python
from gdelt_raw.parser import parse_events, parse_gkg  # replace existing parse_events import


def _gkg_line(record_id: str, *, url: str = "https://ex.com/a",
              themes: str = "MILITARY", date: str = "20260425120000") -> str:
    """Build a 27-column GKG line (tab-separated). Empty record_id => null key."""
    f = [""] * 27
    f[0] = record_id                 # gkg_record_id
    f[1] = date                      # v21_date
    f[3] = "ex.com"                  # v2_source_common_name
    f[4] = url                       # v2_document_identifier
    f[7] = themes                    # v1_themes
    f[15] = "0,0,0,0,0,0,0"          # v15_tone
    return "\t".join(f)


def test_gkg_empty_record_id_is_quarantined_valid_rows_survive(tmp_path):
    csv = tmp_path / "s.gkg.csv"
    csv.write_text("\n".join([
        _gkg_line(""),                       # poison: empty leading GKGRecordID
        _gkg_line("g1", url="https://ex.com/1"),
        _gkg_line("g2", url="https://ex.com/2"),
    ]) + "\n")
    q = tmp_path / "q"
    res = parse_gkg(csv, quarantine_dir=q)

    assert res.df.height == 2                                  # only valid rows remain
    assert res.df.get_column("gkg_record_id").null_count() == 0
    assert set(res.df.get_column("gkg_record_id").to_list()) == {"g1", "g2"}
    assert res.quarantine_count == 1                           # poison counted
    assert res.parse_error_pct > 30.0                          # 1 of 3
    qfile = q / "gkg.jsonl"
    assert qfile.exists()
    assert "null_key" in qfile.read_text()


def test_events_null_global_event_id_is_quarantined(tmp_path):
    """Reuse a real valid events line; blank its global_event_id on one copy."""
    good = (FIXTURES / "slice_20260425_full.export.CSV").read_text().splitlines()[0]
    parts = good.split("\t")
    parts[0] = ""                            # blank global_event_id => null key
    bad = "\t".join(parts)
    csv = tmp_path / "s.export.CSV"
    csv.write_text(good + "\n" + bad + "\n")
    q = tmp_path / "q"
    res = parse_events(csv, quarantine_dir=q)

    assert res.df.height == 1                                  # poison dropped
    assert res.df.get_column("global_event_id").null_count() == 0
    assert res.quarantine_count == 1
    assert (q / "events.jsonl").read_text().count("null_key") == 1
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_gdelt_parser.py -v`
Expected: the two new tests FAIL — `res.df.height == 2`/`== 1` assertions fail because the null-key row is currently retained (height 3 / 2) and `quarantine_count == 0`.

- [ ] **Step 3: Implement the null-key gateway in `parser.py`**

In `gdelt_raw/parser.py`, after the `log = structlog.get_logger(__name__)` line, add the helper:

```python
def _quarantine_null_keys(
    df: pl.DataFrame,
    id_column: str,
    stream_name: str,
    quarantine_dir: Path | None,
) -> tuple[pl.DataFrame, int]:
    """Divert rows whose primary-key column is null to the quarantine JSONL and
    drop them from the frame. Runs on BOTH the strict and fallback paths — an
    empty leading key is silently null-coerced by ``null_values=[""]`` on the
    strict path (no error), so this gate, not the tab-count check, is what
    catches it. Returns (clean_df, dropped_count)."""
    if df.height == 0 or id_column not in df.columns:
        return df, 0
    bad = df.filter(pl.col(id_column).is_null())
    if bad.height == 0:
        return df, 0
    if quarantine_dir is not None:
        quarantine_dir.mkdir(parents=True, exist_ok=True)
        qfile = quarantine_dir / f"{stream_name}.jsonl"
        with qfile.open("a", encoding="utf-8") as fh:  # append: tab-count path may have written
            for row in bad.to_dicts():
                fh.write(json.dumps(
                    {"reason": "null_key", "id_column": id_column, "row": row},
                    default=str,
                ) + "\n")
    log.warning(
        "gdelt_null_key_quarantined",
        stream=stream_name, id_column=id_column, count=bad.height,
    )
    return df.filter(pl.col(id_column).is_not_null()), bad.height
```

Change `_parse_stream` to accept `id_column` and apply the gate uniformly. Replace the existing `_parse_stream` body (lines ~111-140) with:

```python
def _parse_stream(
    path: Path,
    cols: list[str],
    schema: dict,
    stream_name: str,
    id_column: str,
    quarantine_dir: Path | None,
) -> ParseResult:
    if not path.is_file():
        raise FileNotFoundError(f"GDELT slice not found: {path}")
    non_empty_count = sum(
        1
        for ln in path.read_text(encoding="utf-8", errors="replace").splitlines()
        if ln.strip()
    )
    try:
        df = _parse_strict(path, cols, schema)
        tab_quarantine = 0
    except (
        pl.exceptions.ComputeError,
        pl.exceptions.SchemaFieldNotFoundError,
        pl.exceptions.NoDataError,
    ) as e:
        log.warning("gdelt_parser_fallback", stream=stream_name, error=str(e))
        fb = _parse_with_fallback(path, cols, schema, stream_name, quarantine_dir)
        df = fb.df
        tab_quarantine = fb.quarantine_count

    # WP-02: divert null/empty primary-key rows on both paths.
    df, null_quarantine = _quarantine_null_keys(df, id_column, stream_name, quarantine_dir)

    return ParseResult(
        df=df,
        total_lines=non_empty_count,
        quarantine_count=tab_quarantine + null_quarantine,
    )
```

Update the three public functions to pass their key column. Replace the bodies of `parse_events`, `parse_mentions`, `parse_gkg`:

```python
def parse_events(path: Path, quarantine_dir: Path | None = None) -> ParseResult:
    return _parse_stream(
        path, EVENT_COLUMNS, EVENT_POLARS_SCHEMA, "events",
        "global_event_id", quarantine_dir,
    )


def parse_mentions(path: Path, quarantine_dir: Path | None = None) -> ParseResult:
    return _parse_stream(
        path, MENTION_COLUMNS, MENTION_POLARS_SCHEMA, "mentions",
        "global_event_id", quarantine_dir,
    )


def parse_gkg(path: Path, quarantine_dir: Path | None = None) -> ParseResult:
    return _parse_stream(
        path, GKG_COLUMNS, GKG_POLARS_SCHEMA, "gkg",
        "gkg_record_id", quarantine_dir,
    )
```

(Keep the existing docstrings on the three functions.)

- [ ] **Step 4: Run the full parser test module to verify pass + no regression**

Run: `uv run pytest tests/test_gdelt_parser.py -v`
Expected: all tests PASS, including the pre-existing `test_strict_parse_fallback_quarantines_bad_rows` (tab-count path still works: 2 valid rows, `quarantine_count == 1`) and `test_parse_error_pct_computed`.

- [ ] **Step 5: Commit**

```bash
git add gdelt_raw/parser.py tests/test_gdelt_parser.py
git commit -m "fix(gdelt-raw): quarantine null/empty primary-key rows at the parse gateway (WP-02)"
```

---

## Task 2: Parser type-coerced counting (WP-12)

**Files:**
- Modify: `gdelt_raw/parser.py`
- Test: `tests/test_gdelt_parser.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_gdelt_parser.py`:

```python
def test_fallback_type_coerced_event_root_code_is_counted(tmp_path):
    """A row with the correct tab count but a non-integer event_root_code forces
    the strict parse to fail; the fallback null-coerces that cell. The row keeps
    a valid global_event_id (survives the null-key gate) but must be COUNTED so
    parse_error_pct reflects it (WP-12)."""
    good = (FIXTURES / "slice_20260425_full.export.CSV").read_text().splitlines()[0]
    parts = good.split("\t")
    parts[0] = "999999999"            # distinct, valid global_event_id
    parts[28] = "NOTANUMBER"          # event_root_code (Int32) => strict fail, fallback null-coerce
    bad = "\t".join(parts)
    csv = tmp_path / "s.export.CSV"
    csv.write_text(good + "\n" + bad + "\n")
    res = parse_events(csv, quarantine_dir=tmp_path / "q")

    assert res.df.height == 2                 # both rows survive (valid global_event_id)
    assert res.df.get_column("event_root_code").null_count() == 1
    assert res.type_coerced_count == 1        # the coerced cell is visible
    assert res.parse_error_pct > 0.0          # gate can now see it
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_gdelt_parser.py::test_fallback_type_coerced_event_root_code_is_counted -v`
Expected: FAIL — `AttributeError: 'ParseResult' object has no attribute 'type_coerced_count'`.

- [ ] **Step 3: Add `type_coerced_count` and the counting helper**

In `gdelt_raw/parser.py`, extend the `ParseResult` dataclass — add the field after `quarantine_count` and fold it into `parse_error_pct`:

```python
@dataclass
class ParseResult:
    df: pl.DataFrame
    total_lines: int
    quarantine_count: int
    type_coerced_count: int = 0

    @property
    def parse_error_pct(self) -> float:
        if self.total_lines == 0:
            return 0.0
        return 100.0 * (self.quarantine_count + self.type_coerced_count) / self.total_lines
```

Update the dataclass docstring's Fields list to mention `type_coerced_count: number of rows with a null-coerced non-id typed cell (counted, not dropped)`.

Add the counting helper near `_quarantine_null_keys`:

```python
# Non-id typed columns whose null on the fallback path means a silently coerced
# cell (WP-12). The id columns are handled by the null-key gate, not here.
_TYPE_COERCE_WATCH: dict[str, list[str]] = {"events": ["event_root_code"]}


def _count_type_coerced(df: pl.DataFrame, stream_name: str) -> int:
    """Count rows where any watched non-id typed column is null (post-fallback
    coercion). Run AFTER the null-key gate so dropped null-id rows aren't
    double-counted."""
    cols = [c for c in _TYPE_COERCE_WATCH.get(stream_name, []) if c in df.columns]
    if not cols or df.height == 0:
        return 0
    mask = pl.any_horizontal([pl.col(c).is_null() for c in cols])
    return df.filter(mask).height
```

Wire it into `_parse_stream` — after the null-key gate line, compute and pass it:

```python
    # WP-02: divert null/empty primary-key rows on both paths.
    df, null_quarantine = _quarantine_null_keys(df, id_column, stream_name, quarantine_dir)

    # WP-12: count (don't drop) non-id cells the fallback null-coerced.
    type_coerced = _count_type_coerced(df, stream_name)

    return ParseResult(
        df=df,
        total_lines=non_empty_count,
        quarantine_count=tab_quarantine + null_quarantine,
        type_coerced_count=type_coerced,
    )
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/test_gdelt_parser.py -v`
Expected: all PASS (the new test plus all Task 1 tests and the pre-existing ones).

- [ ] **Step 5: Commit**

```bash
git add gdelt_raw/parser.py tests/test_gdelt_parser.py
git commit -m "fix(gdelt-raw): count fallback type-coerced cells into parse_error_pct (WP-12)"
```

---

## Task 3: Filter defense-in-depth (WP-02)

**Files:**
- Modify: `gdelt_raw/filter.py` (line `93` concat/unique; invariant at `135`)
- Test: `tests/test_gdelt_filter.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_gdelt_filter.py`:

```python
def test_filter_drops_null_gkg_record_id():
    """A GKG row with a null gkg_record_id (e.g. it slipped past a caller that
    didn't run the parser gate) must be dropped before unique(), and the
    post-join frame must carry no null doc_id."""
    gkg = pl.DataFrame({
        "gkg_record_id": ["r1", None],
        "v21_date": [20260425120000, 20260425120000],
        "v2_document_identifier": ["https://nuc.com/a", "https://ex.com/x"],
        "v1_themes": ["NUCLEAR;WMD", "MILITARY"],
        "v2_source_common_name": ["nuc.com", "ex.com"],
    })
    res = apply_filters(_events_df(), _mentions_df(), gkg,
                        cameo_roots=[15, 18, 19, 20],
                        theme_alpha=["ARMEDCONFLICT", "KILL", "MILITARY"],
                        theme_nuclear_override=["NUCLEAR", "WMD"])
    ids = res.gkg.get_column("gkg_record_id").to_list()
    assert None not in ids
    assert res.gkg.get_column("doc_id").null_count() == 0
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_gdelt_filter.py::test_filter_drops_null_gkg_record_id -v`
Expected: FAIL — the null `gkg_record_id` row survives `unique()`, `map_elements(build_doc_id)` skips its null input → `doc_id` is null → `None in ids` and `null_count() == 1`. (Depending on polars version it may instead trip the `n_unique` invariant; either way it does not pass.)

- [ ] **Step 3: Implement the defense-in-depth**

In `gdelt_raw/filter.py`, replace the `gkg_union` line (`:93`):

```python
    # 7. gkg union and materialized join — drop null keys before unique() so a
    # null gkg_record_id can never reach build_doc_id (WP-02 defense-in-depth).
    gkg_union = (
        pl.concat([gkg_alpha, gkg_nuclear])
        .drop_nulls(subset=["gkg_record_id"])
        .unique(subset=["gkg_record_id"])
    )
```

Replace the invariant block (`:134-136`) to also assert non-null `doc_id`:

```python
    # Invariant: doc_id non-null AND unique (real correctness checks, not debug asserts)
    null_doc_ids = gkg_with_join.get_column("doc_id").null_count()
    if null_doc_ids:
        raise RuntimeError(
            f"filter invariant: doc_id must be non-null after materialized join "
            f"(found {null_doc_ids})"
        )
    if gkg_with_join.n_unique("gkg_record_id") != gkg_with_join.height:
        raise RuntimeError("filter invariant: doc_id must be unique after materialized join")
```

- [ ] **Step 4: Run the filter test module to verify pass + no regression**

Run: `uv run pytest tests/test_gdelt_filter.py -v`
Expected: all PASS, including the existing `test_gkg_join_does_not_duplicate_docs_with_multiple_events` and `test_gkg_alpha_doc_without_mentions_yields_empty_lists`.

- [ ] **Step 5: Commit**

```bash
git add gdelt_raw/filter.py tests/test_gdelt_filter.py
git commit -m "fix(gdelt-raw): drop null gkg_record_id before unique + assert non-null doc_id invariant (WP-02)"
```

---

## Task 4: Neo4j writer skip-and-log (WP-02)

**Files:**
- Modify: `gdelt_raw/writers/neo4j_writer.py` (imports; `write_from_parquet` lines `195-209`)
- Test: `tests/test_gdelt_neo4j_writer.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_gdelt_neo4j_writer.py`:

```python
from unittest.mock import AsyncMock

import polars as pl


def test_validate_rows_skips_invalid_keeps_valid():
    from gdelt_raw.writers.neo4j_writer import _validate_rows

    rows = [
        {  # valid
            "event_id": "gdelt:event:1", "cameo_code": "193", "cameo_root": 19,
            "quad_class": 4, "goldstein": -6.5, "avg_tone": -4.2,
            "num_mentions": 1, "num_sources": 1, "num_articles": 1,
            "date_added": "2026-04-25T12:15:00Z", "fraction_date": 2026.3164,
            "source_url": "https://ex.com", "codebook_type": "conflict.armed",
            "filter_reason": "tactical",
        },
        {  # invalid: missing event_id
            "cameo_code": "193", "cameo_root": 19, "quad_class": 4,
            "goldstein": -6.5, "avg_tone": -4.2, "num_mentions": 1,
            "num_sources": 1, "num_articles": 1, "date_added": "2026-04-25T12:15:00Z",
            "fraction_date": 2026.3164, "source_url": "https://ex.com",
            "codebook_type": "conflict.armed", "filter_reason": "tactical",
        },
    ]
    valid = _validate_rows(rows, GDELTEventWrite, "events")
    assert len(valid) == 1
    assert valid[0].event_id == "gdelt:event:1"


def test_validate_rows_skips_null_doc_id():
    from gdelt_raw.writers.neo4j_writer import _validate_rows

    rows = [
        {"doc_id": "gdelt:gkg:r1", "url": "https://ex.com", "source_name": "ex.com",
         "gdelt_date": "2026-04-25T12:15:00Z"},
        {"doc_id": None, "url": "https://ex.com", "source_name": "ex.com",
         "gdelt_date": "2026-04-25T12:15:00Z"},
    ]
    valid = _validate_rows(rows, GDELTDocumentWrite, "gkg")
    assert len(valid) == 1
    assert valid[0].doc_id == "gdelt:gkg:r1"


@pytest.mark.asyncio
async def test_write_from_parquet_skips_bad_gkg_row(tmp_path):
    """One null-doc_id row in the gkg parquet must not block the valid docs."""
    from gdelt_raw.writers.neo4j_writer import Neo4jWriter

    gkg_dir = tmp_path / "gkg" / "date=2026-04-25"
    gkg_dir.mkdir(parents=True)
    pl.DataFrame({
        "doc_id": ["gdelt:gkg:g1", None],
        "source": ["gdelt_gkg", "gdelt_gkg"],
        "url": ["https://ex.com/1", "https://ex.com/2"],
        "source_name": ["ex.com", "ex.com"],
        "gdelt_date": ["2026-04-25T12:00:00", "2026-04-25T12:00:00"],
        "themes": [["MILITARY"], ["MILITARY"]],
        "persons": [[], []], "organizations": [[], []],
        "tone_positive": [0.0, 0.0], "tone_negative": [0.0, 0.0],
        "tone_polarity": [0.0, 0.0], "tone_activity": [0.0, 0.0],
        "tone_self_group": [0.0, 0.0], "word_count": [0, 0],
        "sharp_image_url": [None, None], "quotations": [[], []],
        "linked_event_ids": [[], []], "goldstein_min": [None, None],
        "goldstein_avg": [None, None], "cameo_roots_linked": [[], []],
        "codebook_types_linked": [[], []],
    }).write_parquet(gkg_dir / "20260425120000.parquet")

    writer = Neo4jWriter("bolt://localhost:7687", "neo4j", "x")
    writer.write_docs = AsyncMock()           # capture validated docs; no real Neo4j
    writer.write_events = AsyncMock()
    writer.write_mentions = AsyncMock()

    await writer.write_from_parquet(tmp_path, "20260425120000", "2026-04-25")

    writer.write_docs.assert_awaited_once()
    (docs,) = writer.write_docs.await_args.args
    assert len(docs) == 1
    assert docs[0].doc_id == "gdelt:gkg:g1"
```

(Module-level imports `pytest` and `from gdelt_raw.schemas import GDELTDocumentWrite, GDELTEventWrite` already exist at the top of this file.)

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_gdelt_neo4j_writer.py -v`
Expected: FAIL — `ImportError: cannot import name '_validate_rows'`; the async test fails because the current list-comprehension raises `ValidationError` on the null-doc_id row.

- [ ] **Step 3: Implement skip-and-log**

In `gdelt_raw/writers/neo4j_writer.py`, add to the imports near the top:

```python
from pydantic import ValidationError
```

Add the helper after the `render_doc_params` function (before `class Neo4jWriter`):

```python
def _validate_rows(rows: list[dict], model: type, stream: str) -> list:
    """Validate each row against ``model``; skip-and-log rejects instead of
    fail-fast. One malformed row (e.g. a null doc_id that slipped past the
    parser gate) must not block the whole slice's batch write (WP-02)."""
    valid = []
    rejected = 0
    for r in rows:
        try:
            valid.append(model.model_validate(r))
        except ValidationError as e:
            rejected += 1
            log.warning(
                "gdelt_writer_row_rejected",
                stream=stream,
                doc_id=r.get("doc_id"),
                event_id=r.get("event_id"),
                error=str(e).splitlines()[0],
            )
    if rejected:
        log.warning(
            "gdelt_writer_rows_rejected",
            stream=stream, rejected=rejected, accepted=len(valid),
        )
    return valid
```

Replace the two fail-fast comprehensions in `write_from_parquet` (lines `195-203`):

```python
        if ev_path.exists():
            ev_df = pl.read_parquet(ev_path)
            events = _validate_rows(ev_df.to_dicts(), GDELTEventWrite, "events")
            if events:
                await self.write_events(events)

        if gkg_path.exists():
            gkg_df = pl.read_parquet(gkg_path)
            docs = _validate_rows(gkg_df.to_dicts(), GDELTDocumentWrite, "gkg")
            if docs:
                await self.write_docs(docs)
```

- [ ] **Step 4: Run the test module to verify pass + no regression**

Run: `uv run pytest tests/test_gdelt_neo4j_writer.py -v`
Expected: all PASS, including the existing template/schema tests.

- [ ] **Step 5: Commit**

```bash
git add gdelt_raw/writers/neo4j_writer.py tests/test_gdelt_neo4j_writer.py
git commit -m "fix(gdelt-raw): Neo4j writer skips-and-logs invalid rows instead of fail-fast (WP-02)"
```

---

## Task 5: Qdrant writer null-doc_id guard (WP-02)

**Files:**
- Modify: `gdelt_raw/writers/qdrant_writer.py` (`upsert_from_parquet` loop `137-148`)
- Test: `tests/test_gdelt_qdrant_writer.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_gdelt_qdrant_writer.py`:

```python
@pytest.mark.asyncio
async def test_qdrant_skips_row_with_null_doc_id(tmp_path):
    """A null doc_id must be skipped+logged, not crash uuid5(NAMESPACE_URL, None)."""
    df = pl.DataFrame({
        "doc_id": ["gdelt:gkg:g1", None],
        "url": ["https://ex.com/1", "https://ex.com/2"],
        "source_name": ["ex.com", "ex.com"],
        "gdelt_date": ["2026-04-25T12:00:00", "2026-04-25T12:00:00"],
        "themes": [["MILITARY"], ["MILITARY"]],
        "persons": [[], []], "organizations": [[], []],
        "linked_event_ids": [[], []], "goldstein_min": [None, None],
        "goldstein_avg": [None, None], "cameo_roots_linked": [[], []],
        "codebook_types_linked": [[], []],
        "tone_polarity": [0.0, 0.0], "word_count": [0, 0],
    })
    gkg_dir = tmp_path / "gkg" / "date=2026-04-25"
    gkg_dir.mkdir(parents=True)
    df.write_parquet(gkg_dir / "20260425120000.parquet")

    mock_client = MagicMock()
    mock_client.get_collections = AsyncMock(return_value=MagicMock(collections=[]))
    mock_client.create_collection = AsyncMock()
    mock_client.upsert = AsyncMock()
    embedder = AsyncMock(return_value=[0.1] * 1024)

    w = QdrantWriter(client=mock_client, embed=embedder, collection="test")
    n = await w.upsert_from_parquet(tmp_path, "20260425120000", "2026-04-25")

    assert n == 1                                  # only the valid row upserted
    mock_client.upsert.assert_called_once()
    (_, kwargs) = mock_client.upsert.call_args
    assert len(kwargs["points"]) == 1
```

(Module already imports `AsyncMock, MagicMock`, `pl`, `pytest`, and `QdrantWriter`.)

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_gdelt_qdrant_writer.py::test_qdrant_skips_row_with_null_doc_id -v`
Expected: FAIL — `TypeError` from `uuid5(NAMESPACE_URL, None)` (or a KeyError from `row["doc_id"]` being None) while building the second point.

- [ ] **Step 3: Implement the guard**

In `gdelt_raw/writers/qdrant_writer.py`, replace the per-row loop body in `upsert_from_parquet` (lines `138-148`):

```python
        for row in df.to_dicts():
            doc_id = row.get("doc_id")
            if not doc_id:
                log.warning("gdelt_qdrant_row_skipped_no_doc_id", url=row.get("url"))
                continue
            text = build_embed_text(row)
            content_hash = hashlib.sha256(text.encode()).hexdigest()
            vector = await self._embed(text)
            payload = build_payload(row)
            payload["content_hash"] = content_hash
            points.append(PointStruct(
                id=qdrant_point_id_for_doc(doc_id),
                vector=vector,
                payload=payload,
            ))
```

- [ ] **Step 4: Run the test module to verify pass + no regression**

Run: `uv run pytest tests/test_gdelt_qdrant_writer.py -v`
Expected: all PASS, including the existing upsert/validation/close tests.

- [ ] **Step 5: Commit**

```bash
git add gdelt_raw/writers/qdrant_writer.py tests/test_gdelt_qdrant_writer.py
git commit -m "fix(gdelt-raw): Qdrant writer skips null doc_id rows instead of crashing uuid5 (WP-02)"
```

---

## Task 6: End-to-end acceptance test (WP-02)

Proves the spec's acceptance criterion with no real stores (CI-runnable): a GKG slice with one empty leading `GKGRecordID` → the bad row is quarantined, **all** valid rows still flow parse → filter → canonicalize → both writers, and `parse_error_pct` reflects the bad row.

**Files:**
- Create: `tests/test_gdelt_parse_gateway_e2e.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_gdelt_parse_gateway_e2e.py`:

```python
"""T2 acceptance: one malformed key never destroys a slice's batch.

parse -> filter -> canonicalize -> (mocked) Neo4j + Qdrant writers, all in
process. No dev-compose services required (stores are mocked)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import polars as pl
import pytest

from gdelt_raw.filter import apply_filters
from gdelt_raw.parser import parse_gkg
from gdelt_raw.transform import canonicalize_gkg
from gdelt_raw.writers.neo4j_writer import Neo4jWriter
from gdelt_raw.writers.qdrant_writer import QdrantWriter


def _gkg_line(record_id: str, url: str, themes: str = "MILITARY",
              date: str = "20260425120000") -> str:
    f = [""] * 27
    f[0] = record_id            # gkg_record_id
    f[1] = date                 # v21_date
    f[3] = "ex.com"             # v2_source_common_name
    f[4] = url                  # v2_document_identifier
    f[7] = themes               # v1_themes
    f[15] = "0,0,0,0,0,0,0"     # v15_tone
    return "\t".join(f)


def _empty_events_df() -> pl.DataFrame:
    return pl.DataFrame({
        "global_event_id": [], "event_root_code": [], "quad_class": [],
        "goldstein_scale": [], "avg_tone": [], "num_mentions": [],
        "num_sources": [], "num_articles": [], "date_added": [],
        "fraction_date": [], "event_code": [], "actor1_code": [],
        "actor1_name": [], "actor2_code": [], "actor2_name": [], "source_url": [],
        "action_geo_lat": [], "action_geo_long": [], "action_geo_fullname": [],
        "action_geo_country_code": [], "action_geo_feature_id": [],
    }, schema={
        "global_event_id": pl.Int64, "event_root_code": pl.Int32,
        "quad_class": pl.Int8, "goldstein_scale": pl.Float64, "avg_tone": pl.Float64,
        "num_mentions": pl.Int32, "num_sources": pl.Int32, "num_articles": pl.Int32,
        "date_added": pl.Int64, "fraction_date": pl.Float64, "event_code": pl.Utf8,
        "actor1_code": pl.Utf8, "actor1_name": pl.Utf8, "actor2_code": pl.Utf8,
        "actor2_name": pl.Utf8, "source_url": pl.Utf8, "action_geo_lat": pl.Float64,
        "action_geo_long": pl.Float64, "action_geo_fullname": pl.Utf8,
        "action_geo_country_code": pl.Utf8, "action_geo_feature_id": pl.Utf8,
    })


def _empty_mentions_df() -> pl.DataFrame:
    return pl.DataFrame({
        "global_event_id": [], "mention_identifier": [], "mention_doc_tone": [],
        "confidence": [], "action_char_offset": [],
    }, schema={
        "global_event_id": pl.Int64, "mention_identifier": pl.Utf8,
        "mention_doc_tone": pl.Float64, "confidence": pl.Int32,
        "action_char_offset": pl.Int32,
    })


@pytest.mark.asyncio
async def test_one_empty_gkgid_does_not_destroy_the_slice(tmp_path):
    csv = tmp_path / "s.gkg.csv"
    csv.write_text("\n".join([
        _gkg_line("", "https://ex.com/poison"),    # poison
        _gkg_line("g1", "https://ex.com/a"),
        _gkg_line("g2", "https://ex.com/b"),
    ]) + "\n")

    # 1. parse — poison quarantined, error pct reflects it
    gk = parse_gkg(csv, quarantine_dir=tmp_path / "q")
    assert gk.df.height == 2
    assert gk.quarantine_count == 1
    assert gk.parse_error_pct > 0.0

    # 2. filter + canonicalize the two survivors (no events -> empty linked aggs)
    fr = apply_filters(
        _empty_events_df(), _empty_mentions_df(), gk.df,
        cameo_roots=[15, 18, 19, 20],
        theme_alpha=["MILITARY"],
        theme_nuclear_override=["NUCLEAR", "WMD"],
    )
    assert fr.gkg.height == 2
    assert fr.gkg.get_column("doc_id").null_count() == 0
    gkg_canon = canonicalize_gkg(fr.gkg)

    # 3. write parquet
    gkg_dir = tmp_path / "gdelt" / "gkg" / "date=2026-04-25"
    gkg_dir.mkdir(parents=True)
    gkg_canon.write_parquet(gkg_dir / "20260425120000.parquet")

    # 4. Neo4j writer (mocked driver) — both valid docs reach write_docs
    neo = Neo4jWriter("bolt://localhost:7687", "neo4j", "x")
    neo.write_docs = AsyncMock()
    neo.write_events = AsyncMock()
    neo.write_mentions = AsyncMock()
    await neo.write_from_parquet(tmp_path / "gdelt", "20260425120000", "2026-04-25")
    neo.write_docs.assert_awaited_once()
    (docs,) = neo.write_docs.await_args.args
    assert {d.doc_id for d in docs} == {"gdelt:gkg:g1", "gdelt:gkg:g2"}

    # 5. Qdrant writer (mocked client) — both valid docs upserted
    mock_client = MagicMock()
    mock_client.get_collections = AsyncMock(return_value=MagicMock(collections=[]))
    mock_client.create_collection = AsyncMock()
    mock_client.upsert = AsyncMock()
    qw = QdrantWriter(client=mock_client, embed=AsyncMock(return_value=[0.1] * 1024),
                      collection="test")
    n = await qw.upsert_from_parquet(tmp_path / "gdelt", "20260425120000", "2026-04-25")
    assert n == 2
```

- [ ] **Step 2: Run the test to verify it passes**

Run: `uv run pytest tests/test_gdelt_parse_gateway_e2e.py -v`
Expected: PASS — by this point Tasks 1, 3, 4, 5 are all merged, so the full chain works. (This test is green on first run because it exercises already-implemented behavior end-to-end; it is the regression lock, not a red→green driver. If it fails, a prior task is incomplete — fix that task, do not weaken the assertion.)

- [ ] **Step 3: Run the whole gdelt suite for regression**

Run: `uv run pytest tests/ -k "gdelt or parser or filter or writer" -q`
Expected: all PASS (was 217 passed, 1 skipped at baseline; now higher with the new tests, still 0 failures).

- [ ] **Step 4: Commit**

```bash
git add tests/test_gdelt_parse_gateway_e2e.py
git commit -m "test(gdelt-raw): e2e acceptance — one empty GKGRecordID never destroys the slice (WP-02)"
```

---

## Final verification (after Task 6)

- [ ] Full data-ingestion suite: `uv run pytest -q` → record pass/skip counts; 0 failures.
- [ ] Lint: `uv run ruff check gdelt_raw/ tests/` → 0 findings (the repo CI gate is diff-based ruff; keep it clean).
- [ ] Confirm no migration/script was added (T2 is forward-fix + replayability only; the replay command is T5).

---

## Self-Review (spec coverage)

| Spec T2 item | Task |
| --- | --- |
| Quarantine null/empty keys at gateway, both strict + fallback, count into `parse_error_pct` | Task 1 |
| `global_event_id` key for events/mentions; `gkg_record_id` for gkg | Task 1 (threaded `id_column`) |
| Filter `.drop_nulls(subset=["gkg_record_id"])` before `unique()` | Task 3 |
| Tighten post-join invariant to assert `doc_id` null-count == 0 | Task 3 |
| Writers skip-and-log instead of fail-fast; guard `qdrant_point_id_for_doc` against None | Task 4 (Neo4j), Task 5 (Qdrant) |
| WP-12: count post-fallback null typed columns into `parse_error_pct`; drop/quarantine null-id rows | Task 2 (type-coerce count) + Task 1 (null-id drop) |
| Acceptance: one malformed key never destroys a slice's batch; `parse_error_pct` accounts for it | Task 6 |
| Repair = T5 replay command; **no T2 migration** | Final verification checklist |
