# Country Indicators Enrichment Design

Date: 2026-06-23

## Context

ODIN already ingests live conflict, infrastructure, maritime, RSS, full-text, and structured SUV data. It also has a WorldReport/Almanac concept for country context, but the current structured country facts are still sparse and mostly static.

The proposed source family fills the missing "hard country context" layer: macroeconomics, population, trade dependency, fiscal/financial data, democracy/regime indicators, and military expenditure. These are the numeric baselines analysts need before interpreting incidents, sanctions, supply chains, and geopolitical pressure.

Existing related pieces:

- IMF PortWatch maritime/chokepoint collector exists in `services/data-ingestion/feeds/portwatch_collector.py`.
- SIPRI exists as an RSS/full-text source, but not yet as structured military expenditure or arms-transfer data.
- WorldReport Almanac spec exists at `docs/superpowers/specs/2026-05-19-worldreport-almanac-design.md`.
- Neo4j write-path rules require deterministic Cypher templates and parameter binding only.

## Goal

Build a reusable `country-indicators` ingestion layer that normalizes official and curated country-year indicators into one stable internal contract.

The layer should support:

- Country Inspector / WorldReport enrichment.
- Neo4j country fact nodes and relationships.
- Intelligence-agent retrieval of hard numeric evidence.
- Longitudinal trend analysis by country, region, source, and indicator.
- Later dependency graphs such as bilateral trade exposure and military spending pressure.

This is not a live request-path feature. All external data should be fetched by scheduled/batch ingestion and then served from local stores.

## Source Priority

### P0: World Bank Open Data

First source to implement.

Why:

- No API key.
- Simple REST API with JSON support.
- Broad country coverage.
- World Bank Indicators API exposes nearly 16,000 time-series indicators across 45+ databases, many going back more than 50 years.

Primary use:

- Population, GDP, GDP per capita, inflation, unemployment, poverty, trade share, energy, CO2, education, health, and World-Bank-hosted SIPRI military expenditure indicators.

Official docs:

- https://datahelpdesk.worldbank.org/knowledgebase/articles/889392-about-the-indicators-api-documentation
- https://datahelpdesk.worldbank.org/knowledgebase/articles/898581-api-basic-call-structures

### P0: Our World in Data

Second source to implement.

Why:

- Curated indicators with strong methodology notes.
- Simple chart API: append `.csv`, `.metadata.json`, or `.zip` to grapher URLs.
- Useful bridge for fast analyst-facing indicators where OWID already harmonizes source metadata.

Primary use:

- Curated development, health, energy, democracy, emissions, conflict-adjacent, technology, and SIPRI-derived military expenditure series.

Official docs:

- https://docs.owid.io/projects/etl/api/chart-api/

### P1: SIPRI Structured Data

Why:

- Gold-standard military expenditure and arms data for geopolitics.
- Military expenditure database is open-source-based and downloadable as Excel.
- Time series cover many countries from at least the late 1950s, with world totals from 1988.

Primary use:

- Military expenditure absolute, share of GDP, share of government expenditure, regional military expenditure trends.
- Later slice: arms transfers and arms industry datasets if licensing/format allows reliable ingestion.

Official docs:

- https://www.sipri.org/databases/milex
- https://www.sipri.org/databases

### P1: V-Dem

Why:

- Best structured country-year source for democracy/autocracy/regime indicators.
- Batch dataset, not a live API dependency.

Primary use:

- Electoral democracy, liberal democracy, deliberative democracy, civil liberties, party system, repression and institutional indicators.

Official docs:

- https://www.v-dem.net/data/the-v-dem-dataset/

### P2: UN Comtrade

Why:

- Essential for bilateral dependency analysis: who buys/sells what from whom.
- Supports power-structure analysis, sanctions exposure, chokepoint relevance, and commodity dependence.

Constraints:

- Requires account/API subscription key for practical API use.
- Free access has limits; current public Comtrade material advertises 100k records per call and 500 API calls per day for free keys.
- Large datasets require careful partitioning, caching, and resumable ingestion.

Official docs:

- https://comtrade.un.org/
- https://comtradeplus.un.org/TradeFlow
- https://uncomtrade.org/docs/developer-tools/

### P2: IMF SDMX

Why:

- Stronger macro-financial source than World Bank for balance of payments, exchange rates, fiscal and financial statistics.

Constraints:

- SDMX 2.1/3.0 requires adapter work and source-specific flow discovery.
- Better implemented after a generic SDMX/JSON-stat adapter exists.

Official docs:

- https://data.imf.org/en/Resource-Pages/IMF-API

### P2: OECD and Eurostat

Why:

- High-quality structured indicators for OECD/EU/NATO-adjacent analysis.
- Useful for industrial production, trade, energy, labor, fiscal, migration, and regional Europe datasets.

Constraints:

- OECD uses SDMX APIs.
- Eurostat uses public REST APIs with JSON-stat 2.0 and SDMX variants.
- Coverage is regionally biased, so these should enrich rather than anchor global country context.

Official docs:

- https://www.oecd.org/en/data/insights/data-explainers/2024/09/api.html
- https://ec.europa.eu/eurostat/web/user-guides/data-browser/api-data-access/api-getting-started

## Chosen Approach

Implement a shared internal `CountryIndicatorObservation` contract plus source-specific collectors.

Do not build one giant "macro collector". Each source gets its own small collector and parser, but all collectors emit the same normalized observation shape. This keeps source quirks isolated while allowing one storage, validation, provenance, and query layer.

The first implementation plan should include only:

1. Shared country-indicator schemas and deterministic IDs.
2. World Bank collector for a small curated indicator set.
3. OWID collector for a small curated chart set.
4. Local JSON/Parquet artifact output.
5. Tests and coverage-ratchet integration.

SIPRI, V-Dem, Comtrade, IMF, OECD, and Eurostat are follow-on slices.

## Normalized Data Contract

Each observation represents one value for one country/entity, one indicator, one year or date, from one source.

```json
{
  "observation_id": "worldbank:DEU:NY.GDP.MKTP.CD:2025",
  "source": "worldbank",
  "source_dataset": "WDI",
  "source_url": "https://api.worldbank.org/v2/country/DEU/indicator/NY.GDP.MKTP.CD",
  "country_iso3": "DEU",
  "country_name": "Germany",
  "year": 2025,
  "date": null,
  "indicator_code": "NY.GDP.MKTP.CD",
  "indicator_name": "GDP (current US$)",
  "indicator_group": "economy",
  "value": 4300000000000.0,
  "unit": "current US$",
  "scale": 1.0,
  "as_of": "2026-06-23T00:00:00Z",
  "provenance": {
    "retrieved_at": "2026-06-23T00:00:00Z",
    "license_note": "source terms apply",
    "raw_ref": "data/country_indicators/raw/worldbank/DEU_NY.GDP.MKTP.CD.json"
  }
}
```

Rules:

- `observation_id` is deterministic: `{source}:{country_iso3}:{indicator_code}:{year-or-date}`.
- `country_iso3` is required for country-level observations.
- Non-country aggregates use explicit entity IDs such as `WLD`, `EUU`, or source-defined aggregates only when documented.
- `value` is numeric or absent; do not store formatted strings as values.
- `unit` and `scale` preserve source semantics.
- Store source metadata and raw artifacts for reproducibility.
- Do not overwrite observations without preserving `retrieved_at` and source version context.

## Storage Shape

Initial slice:

- Raw responses under `services/data-ingestion/data/country_indicators/raw/<source>/`.
- Normalized JSONL or Parquet under `services/data-ingestion/data/country_indicators/normalized/`.
- No Neo4j writes in the first slice unless the implementation plan explicitly adds deterministic templates and tests.

Later Neo4j model:

- `(:Country {iso3})`
- `(:Indicator {code, source, name, group, unit})`
- `(:IndicatorObservation {id, year, value, source, retrieved_at})`
- `(:Country)-[:HAS_INDICATOR]->(:IndicatorObservation)`
- `(:IndicatorObservation)-[:MEASURES]->(:Indicator)`

For bilateral trade:

- `(:Country)-[:EXPORTS_TO {year, commodity_code, value_usd, source}]->(:Country)`
- `(:Country)-[:IMPORTS_FROM {year, commodity_code, value_usd, source}]->(:Country)`

All graph writes must use deterministic Cypher templates with parameter binding.

## Curated P0 Indicator Seed

World Bank first seed:

- `SP.POP.TOTL` population.
- `NY.GDP.MKTP.CD` GDP current US$.
- `NY.GDP.PCAP.CD` GDP per capita current US$.
- `FP.CPI.TOTL.ZG` inflation consumer prices annual %.
- `SL.UEM.TOTL.ZS` unemployment total % of labor force.
- `NE.TRD.GNFS.ZS` trade as % of GDP.
- `MS.MIL.XPND.GD.ZS` military expenditure % of GDP.
- `MS.MIL.XPND.ZS` military expenditure % of general government expenditure.
- `EG.USE.PCAP.KG.OE` energy use per capita where available.
- `EN.ATM.CO2E.PC` CO2 emissions metric tons per capita.

OWID first seed:

- Military spending SIPRI chart if stable in Grapher.
- Democracy/V-Dem-derived charts where OWID provides clean country-year CSVs.
- Energy and population charts only where they add methodology or cleaner harmonization than World Bank.

Do not ingest every available indicator in P0. Start small, validate contract and storage, then expand.

## Scheduler and Update Cadence

Recommended cadence:

- World Bank: weekly.
- OWID: weekly.
- SIPRI: monthly check, annual meaningful update.
- V-Dem: monthly check, annual meaningful update.
- Comtrade: explicit backfill jobs by year/commodity/country pair, not blind global daily pulls.
- IMF/OECD/Eurostat: weekly for selected flows once implemented.

The scheduler must support:

- Source-specific enable flags.
- Dry-run mode.
- Backfill year ranges.
- Per-source rate limits.
- Resumable checkpoints for large sources.

## Error Handling

Collectors should fail closed for malformed schema changes:

- Raw HTTP failure: retry with bounded exponential backoff.
- Source returns empty series: write no observation, log source/country/indicator.
- Source schema changes: fail the collector and preserve raw response for debugging.
- Invalid numeric value: reject the observation with a structured validation error.
- Missing country ISO3 mapping: quarantine record under a rejected artifact file.

Do not silently coerce ambiguous country names into ISO3. Use explicit source country codes or a tested mapping table.

## API / Product Use

Backend should eventually expose:

- `GET /api/almanac/countries/{iso3}/indicators`
- `GET /api/almanac/countries/{iso3}/indicators/{indicator_code}`
- `GET /api/almanac/countries/{iso3}/indicator-groups/{group}`

Frontend WorldReport use:

- Show compact latest values in Economy, People, Security, and Governance sections.
- Show small sparklines only after normalized time series are locally available.
- Always show source and year.
- Never imply current-year values are current if latest source year is older.

Intelligence use:

- RAG context can cite indicator values as structured evidence.
- Agent tools may query the local indicator store.
- No LLM-generated graph writes.

## Testing Strategy

Required tests for P0:

- Schema validation accepts valid observations and rejects invalid values.
- Deterministic IDs are stable and collision-resistant across sources.
- World Bank parser handles normal values, null values, pagination, and source metadata.
- OWID parser handles CSV + metadata JSON, missing values, and renamed columns.
- Country mapping tests cover ISO2/ISO3 and source aggregate entities.
- Raw artifact writer is deterministic and does not overwrite unrelated source data.
- Scheduler dry-run lists enabled source jobs without network calls.
- Coverage ratchet includes the new parser/schema modules once initial tests are in place.

Integration tests should mock HTTP at the boundary. Do not require live World Bank or OWID network calls in CI.

## Security and Compliance

- No API keys in code.
- Comtrade key, if used later, goes through `.env` / settings only.
- Respect source terms and citation requirements.
- Store provenance URL and retrieval timestamp for every observation.
- Do not scrape pages when an official API/download exists.

## Non-Goals

- No universal SDMX engine in P0.
- No full historical Comtrade backfill in P0.
- No graph writes until the normalized store is tested.
- No live external calls from frontend or backend request paths.
- No attempt to ingest all World Bank indicators in the first slice.

## Open Decisions

1. Normalized artifact format: JSONL first for debuggability, or Parquet first for analytical scale.
2. Country mapping source of truth: existing almanac map, a new ISO mapping file, or both.
3. Whether World Bank-hosted SIPRI military indicators are enough for P0 Security, or SIPRI Excel should be P1 immediately after World Bank.
4. Whether to expose country indicators through backend API before Neo4j storage, or wait until graph write templates exist.
