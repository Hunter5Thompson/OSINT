# Regional atlas and strategic reference layers — 2026-09-06

## Delivered

- Aircraft: airliner fuselage, swept wings and tailplane, contrasting dorsal
  highlight; military jet silhouette refreshed. Double-resolution textures with
  fixed display sizes and existing heading caches / animation ownership retained.
  Explicit bomber identifiers precede speed heuristics.
- Vessels: clearer hull/deck separation, container rows, tanker tanks, carrier
  island and heading glint; double-resolution textures at controlled map size.
- Three independent reference toggles: Nuclear Power Plants, ICBM Bases, Major
  Military Bases. Clickable markers expose source, coordinate provenance and
  explicit non-live coverage limitations. Nuclear labels appear only nearer the
  ground to preserve regional label readability.
- Regional atlas: differentiated province fills, capital markers and bounded
  screen-space label placement. Region selection opens capital, division type,
  capital timezone and historical capital population where available. No regional
  population, current administration or current conflict assessment is invented.
  The panel collapses and respects focus mode / the open layer panel.
- Scope router writes now commit synchronously. World hydration no longer fits
  an Earth-centered bounding sphere; repeated presentation of the same scope
  does not reframe the camera. Country fitting uses the largest land component
  while still rendering overseas territories. Framing leaves room for the HUD.

## Geographic coverage and provenance

The active immutable catalog is `spatial-v1-0180e188358c`:

- 176 existing countries now all have renderable outlines; previously country
  outlines were emitted only when a province build existed.
- Germany adds 16 Bundesländer. Ukraine retains its 27 reviewed subdivisions.
  Other countries have outlines and, where available, capital/profile reference
  data, **not yet published clickable province boundaries**.
- 220 scopes, 276 validated assets, 6,583,842 asset bytes. The 204 pre-existing
  scope derivation revisions are unchanged. No location migration was performed.
- The active and immediately previous catalog remain served, as required by the
  two-revision pointer contract. The older on-disk catalog is retained, not deleted.

Regional profiles use [Natural Earth 5.1.2](https://www.naturalearthdata.com/downloads/10m-cultural-vectors/),
public-domain data pinned to repository commit
`f1890d9f152c896d250a77557a5751a93d494776`. The export contains 4,248 profiles
and 2,234 unambiguously matched capitals across 198 source country codes. Country
codes outside the 176-country boundary catalog are not automatically activated.
Capital joins require matching country and point containment; absent or multiple
matches remain unavailable. Invalid/duplicate subdivision identities and source
ISO/country conflicts (including conflicting Crimea assignments) are excluded
instead of being silently promoted into ODIN's boundary policy.

Nuclear references: 195 records from the historical
[WRI Global Power Plant Database](https://github.com/wri/global-power-plant-database/tree/7a91cfbb2a4e272597acbc00506d61fc1ec73b3d),
CC BY 4.0, pinned to that commit. WRI states the project is no longer maintained;
these records are **not an operating-reactor inventory**. Closed facilities can
remain present. The UI says historical / not live / operating status unverified.

Military starter coverage is deliberately explicit:

- ICBM wing headquarters: F. E. Warren, Malmstrom and Minot, supported by the
  [US Air Force's Twentieth Air Force directory](https://www.afgsc.af.mil/Units/Twentieth-Air-Force/20th-AF-Units/)
  and base mission pages. Approximate headquarters/base locations, no silo map or
  readiness claims. Not a global ICBM inventory.
- Major bases: Ramstein, Norfolk, Yokosuka, Toulon. Per-record institutional or
  Wikidata links and coordinate references are included in `military-sites.json`.
  This is a curated starter selection, not an objective global size ranking.

`services/data-ingestion/reference_layers.py` is the offline, SHA-256-checked
exporter for the nuclear/profile assets. Reproduction inputs:

```text
powerplants.csv:
https://raw.githubusercontent.com/wri/global-power-plant-database/7a91cfbb2a4e272597acbc00506d61fc1ec73b3d/output_database/global_power_plant_database.csv
admin1.geojson:
https://raw.githubusercontent.com/nvkelso/natural-earth-vector/f1890d9f152c896d250a77557a5751a93d494776/geojson/ne_10m_admin_1_states_provinces.geojson
cities.geojson:
https://raw.githubusercontent.com/nvkelso/natural-earth-vector/f1890d9f152c896d250a77557a5751a93d494776/geojson/ne_10m_populated_places.geojson
```

From `services/data-ingestion`, run:

```bash
uv run python reference_layers.py INPUT_DIRECTORY ../frontend/public/data
uv run python -m spatial_catalog fetch --source-lock ../backend/data/spatial/source-lock.json --cache-dir CACHE_DIRECTORY
uv run python -m spatial_catalog build --source-lock ../backend/data/spatial/source-lock.json --cache-dir CACHE_DIRECTORY --out OUTPUT_DIRECTORY/catalogs --policy odin-reference-v1
uv run python -m spatial_catalog verify --catalog OUTPUT_DIRECTORY/catalogs/spatial-v1-0180e188358c
```

Use a fresh output parent for isolated builds: the compiler also manages its
parent's catalog pointer and refuses to drop a missing predecessor. A repeat build
produced byte-identical catalog artifacts; an attempted activation under another
temporary root correctly rejected its missing predecessor.
Publish only after verification; copy the immutable directory first, then update
the pointer and restart catalog consumers. No GPU/provider swap is needed.

## Validation

Focused RED → GREEN receipts cover world-camera preservation, same-scope refresh,
synchronous router writes, overseas framing, missing country outlines, the new
Admin1 parser, source identity conflicts, icon resolution/classification, new
layer controls and capital label placement.

- Frontend: 656 tests / 118 files passed; ESLint, strict TypeScript and production
  builds passed. Existing large-bundle warning remains.
- Backend: 585 tests; Ruff and strict mypy (88 files) passed. Existing
  Starlette/httpx deprecation warning remains.
- Intelligence: 484 tests passed.
- Data ingestion: 1,449 passed, 1 existing skip, 17 default live-test deselections.
  Subsequent exporter/source-focused run: 44 passed; changed Python files pass Ruff.
- Vision enrichment: 22 tests passed; service not started.
- Live catalog API enumerated all 176 countries: zero missing outline descriptors.
- Live production Chromium: all three strategic toggles, Ramstein marker → source
  inspector, Germany → Bayern → Germany → World → France. No browser exceptions.
  Camera centers: Germany 10.37E/51.03N, Bayern 11.30E/48.85N, France 1.87E/46.53N.
  Ascending to World preserved the Germany camera exactly.
  A subsequent real pointer click hit the France `spatial-child` polygon in World
  scope and committed France successfully, with the camera remaining over France.
  Final desktop (1440px) and mobile (390px) pages had no horizontal overflow or
  console errors; mobile scope navigation is placed below the floating toolbars.
- Stack smoke: 14 passed, 0 failed, 1 expected skip (local ingestion profile off;
  Spark ingestion active). Backend, Intelligence and frontend refreshed; local LLM
  and unrelated services left unchanged.

Local screenshots: `/tmp/odin-region-deu-ready.png`,
`/tmp/odin-region-bavaria.png`, `/tmp/odin-strategic-production.png`,
`/tmp/odin-bavaria-production.png`, `/tmp/odin-france-production.png`.

## Remaining work

Expand reviewed province boundary coverage beyond Germany/Ukraine; obtain a
maintained nuclear operating-status source and broaden military reference coverage
under an explicit inclusion policy. Dense operational layers and the general
TASK-114 label/render governor remain separate work. Feed failures and inference
latency from the previous observatory review are not fixed by this change.

The `codebase-design` skill guided separation of reference parsing, Cesium
collection ownership, geographic identity and camera/navigation behavior. Existing
render loops, semantic query contracts and unrelated worktree files were preserved.
