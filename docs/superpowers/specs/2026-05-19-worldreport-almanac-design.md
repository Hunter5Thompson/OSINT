# WorldReport Almanac Design

Date: 2026-05-19

## Context

Worldview already has country click/focus support. When a country is selected, `CountryHeader` renders the country name, ISO/M49 identifier, capital, and a placeholder: `§ Almanac · S2.5 coming soon`.

The requested feature is an ODIN Almanac / WorldReport experience inspired by the CIA World Factbook. The official CIA World Factbook page now redirects to a February 4, 2026 CIA story saying the publication has sunset, so this feature must treat the Factbook as an information-architecture reference only, not a live runtime dependency.

## Goal

Replace the existing country placeholder in Worldview Inspector with a compact country file that gives operators basic national context and adjacent ODIN signals without leaving the globe.

The first slice should feel like a tactical WorldReport panel:

- Static country facts for broad global coverage.
- Compact active signal context when ODIN can conservatively link a signal to the selected country.
- Hlíðskjalf visual language and existing Inspector panel behavior.
- No new intelligence-generation flow, no live third-party calls during page render, and no fake health/status claims.

## Chosen Approach

Implement the Almanac inside the existing Worldview country Inspector rather than adding a dedicated `/worldreport` route.

This fills the already-reserved S2.5 placeholder, keeps country context tied to map clicks/search/spotlight, and avoids building a second navigation surface before the compact panel proves useful.

Use a backend-served static dataset as the source of country facts. The API gives the frontend a stable contract and leaves room for future enrichment from REST Countries, Wikidata, World Bank, Munin summaries, or Neo4j country nodes without changing the Inspector component contract.

Use active signals as a separate ODIN context block. Signals must only be associated with a country when the signal payload contains explicit ISO/M49/country metadata or a conservative exact country-name match. Do not infer geopolitical relevance from vague text.

## Product Shape

The country Inspector renders in this order:

1. Existing country eyebrow: `§ inspector · country · <ISO3 or M49>`.
2. Existing country title.
3. Existing capital grid when capital data is present.
4. New `§ Almanac · WorldReport` panel.
5. New active ODIN signals subsection inside the Almanac panel.

The Almanac panel contains:

- A compact source/timestamp line such as `§ Almanac · WorldReport`.
- Category tabs or segmented controls:
  - `Profile`
  - `People`
  - `Gov`
  - `Economy`
  - `Security`
- A two-column fact grid on desktop, one column on narrow screens.
- A small capability strip using static subsystem labels:
  - `Hugin`
  - `Signalia`
  - `Vectorium`
  - `Memoria`
  - `Fenestra`

The capability strip is presentational context, not health monitoring. It must not use green status dots, `ONLINE`, `UP`, or similar fixed claims.

## Almanac Data Contract

Backend route:

- `GET /api/almanac/countries/{country_id}`

`country_id` accepts:

- ISO3 code when available, case-insensitive.
- M49 code as fallback for countries/entities without ISO3 in the current TopoJSON.

Response shape:

```json
{
  "id": "GRC",
  "iso3": "GRC",
  "m49": "300",
  "name": "Greece",
  "region": "Europe",
  "subregion": "Southern Europe",
  "capital": {
    "name": "Athens",
    "lat": 37.98,
    "lon": 23.73
  },
  "facts": {
    "profile": [
      { "label": "Area", "value": "131,957 sq km" },
      { "label": "Currency", "value": "Euro (EUR)" }
    ],
    "people": [
      { "label": "Population", "value": "10.4M" },
      { "label": "Languages", "value": "Greek" }
    ],
    "government": [
      { "label": "Government type", "value": "Parliamentary republic" }
    ],
    "economy": [
      { "label": "GDP", "value": "Available in future enrichment" }
    ],
    "security": [
      { "label": "Military", "value": "Available in future enrichment" }
    ]
  },
  "updated_at": "2026-05-19",
  "source_note": "ODIN static country almanac"
}
```

Fields may be sparse. The frontend must render available fields and omit empty facts rather than displaying `undefined`, `null`, or misleading placeholders.

Initial data coverage should prefer all countries/entities present in `countries-110m.json` with sparse stable fields over a small set of richly curated countries. Richer per-country files can be added later without changing the API shape.

## Active Signals Contract

Backend route:

- `GET /api/almanac/countries/{country_id}/signals?limit=5`

The endpoint returns a compact newest-first list derived from the existing in-memory signal stream:

```json
{
  "country_id": "GRC",
  "items": [
    {
      "event_id": "0001768651200000-000001",
      "ts": "2026-05-19T10:20:00.000Z",
      "type": "signal.rss",
      "title": "Diplomatic statement indexed by Hugin",
      "severity": "low",
      "source": "rss",
      "url": "https://example.test/source"
    }
  ]
}
```

Matching rules:

- Prefer explicit payload fields: `iso3`, `country_iso3`, `country_code`, `m49`, `country_m49`.
- Then allow exact normalized country-name match from fields such as `country`, `country_name`, or `location_country`.
- Do not match against arbitrary title/body substring in this slice.
- If no signals match, return an empty `items` list with HTTP 200.

This endpoint is intentionally shallow. It does not query Neo4j, Qdrant, or external services in the first slice.

## Frontend Integration

Primary existing file:

- `services/frontend/src/components/globe/spotlight/CountryHeader.tsx`

New frontend pieces may include:

- `services/frontend/src/types/almanac.ts`
- `services/frontend/src/hooks/useCountryAlmanac.ts`
- `services/frontend/src/components/globe/spotlight/CountryAlmanacPanel.tsx`

`CountryHeader` passes `name`, `iso3`, `m49`, and `capital` into the Almanac panel. The panel fetches by `iso3` when present, otherwise `m49`.

The active signals block belongs visually inside the Almanac panel, but the facts and signals states must be independent:

- Almanac facts can render while signals are loading or failed.
- Signals can fail without hiding facts.
- Missing country facts should keep the existing country header visible and show a compact unavailable state.

## Backend Integration

New backend pieces may include:

- `services/backend/app/models/almanac.py`
- `services/backend/app/services/country_almanac.py`
- `services/backend/app/routers/almanac.py`
- `services/backend/app/data/country_almanac.json`

Register the router in `services/backend/app/main.py` under the same `/api` prefix pattern used by `signals`, `landing`, and `incidents`.

Runtime behavior:

- Load the static JSON once per process or lazily with caching.
- Normalize IDs case-insensitively.
- Return `404` for unknown country IDs.
- Keep signal matching deterministic and side-effect free.
- Do not add external HTTP calls in the request path.

## Error Handling

Backend:

- Unknown country: `404` with a clear error detail.
- Malformed country ID: `422` or `404`; either is acceptable if tests document it.
- Signal stream unavailable should degrade to an empty list only if the existing stream accessor can fail in practice; otherwise keep normal exceptions visible in tests.

Frontend:

- Loading facts: show a compact `§ Almanac · loading` state.
- Missing facts: show `§ Almanac · unavailable for this country`.
- Failed signals: show `§ Signals · unavailable` while keeping facts visible.
- Empty signals: show `No linked ODIN signals in current window`.

Never show a fake positive state such as `all systems online`.

## Visual Language

The panel must stay inside the existing Hlíðskjalf Inspector aesthetic:

- `var(--granite)` and related line tokens for separators.
- `Martian Mono` for eyebrows, tabs, labels, and capability strip.
- Serif emphasis only for country/file titles where already consistent.
- Hairline sections rather than large rounded cards.
- No nested cards.
- No green health dots or dashboard-style status lights.

## Accessibility

Tabs/segmented controls must be keyboard reachable. If implemented as buttons, use native `button` elements and visible focus states. If only one static category is rendered in the first implementation, avoid fake tabs and render section headings instead.

The active signals list should use links only when a source URL is present. Link text must describe the signal title/source, not just `Source`.

## Testing

Use TDD for implementation.

Backend tests:

- Almanac model accepts sparse facts.
- Service resolves ISO3 case-insensitively.
- Service resolves M49 fallback.
- Router returns facts for a known country.
- Router returns 404 for unknown country.
- Signal endpoint matches explicit ISO3 payload fields.
- Signal endpoint does not match arbitrary title substring.

Frontend tests:

- `CountryHeader` no longer renders the S2.5 placeholder for a known country.
- Almanac facts render after successful fetch.
- M49 fallback is used when `iso3` is null.
- Missing facts render unavailable state while preserving country title.
- Signals block renders matched compact items.
- Empty signals render a neutral empty-window message.

Run focused tests first:

- Backend: targeted pytest files for Almanac service/router.
- Frontend: focused Vitest tests around `CountryHeader` / `CountryAlmanacPanel`.

Then run the relevant service checks if dependencies are available:

- `cd services/backend && uv run pytest`
- `cd services/frontend && npm test && npm run type-check`

## Out of Scope

- Dedicated `/worldreport` route.
- Full CIA World Factbook clone.
- Live CIA, Wikidata, REST Countries, or World Bank calls during page render.
- Neo4j country graph writes.
- LLM-generated country summaries.
- Qdrant retrieval over country files.
- Country history essays, photos, maps, or long-form reference pages.
- Reworking Worldview globe layers, country hit testing, or Inspector selection mechanics.
- Cleanup of unrelated untracked files such as `test.html`.
