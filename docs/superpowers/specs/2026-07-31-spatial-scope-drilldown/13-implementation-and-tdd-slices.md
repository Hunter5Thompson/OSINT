# Teil-Spec 13 — Umsetzung und TDD-Slices

> **Parent:** [Spatial-Scope-Index](../2026-07-31-spatial-scope-drilldown-design.md)
>
> **Normativer Besitz:** konkreter Dateiplan, neun vertikale TDD-Slices, Red Tests,
> Slice-Gates und service-lokale Verifikationskommandos.
>
> **Voraussetzungen:** nur die fachlichen Teil-Specs des gerade umgesetzten Slice.
> Diese Datei plant und prüft Verträge, überschreibt sie aber nicht.

---

## 23. Konkreter Dateiplan

### 23.1 Frontend neu

```text
services/frontend/src/spatial/
  contracts.ts                 stabile öffentliche Typen + Runtime-Parser
  scopeController.ts           State Machine, Generation, In-flight-Dedupe, Caches
  catalog.ts                   Catalog-Port, HTTP-Adapter, Bundle/Asset-Validation
  navigation.ts                Browser- und Memory-History-Adapter
  geometry.ts                  interne Extent-/Antimeridian-/Point-in-Polygon-Helfer
  react.tsx                    Provider + useSyncExternalStore-Hook
  layerScopePolicy.ts          explizite Layer-Capability-Registry
  cesium/
    CesiumSpatialScopeAdapter.ts
    buildScopePrimitives.ts
    resolveWorldviewPick.ts
  __tests__/
    scopeController.test.ts
    navigation.test.ts
    catalog.test.ts
    geometry.test.ts
    react.test.tsx
    cesiumAdapter.test.ts
    resolveWorldviewPick.test.ts
```

Die Dateien sind nach echter Änderungs-/Test-Locality geschnitten. Es wird kein Wald aus Ein-Klassen-Ports erzeugt; Port und Produktions-/Testadapter dürfen gemeinsam in einer kohärenten Datei leben.

### 23.2 Frontend geändert/entfernt

```text
services/frontend/src/pages/WorldviewPage.tsx
services/frontend/src/app/router.tsx
services/frontend/src/app/__tests__/router.test.tsx
services/frontend/src/components/globe/EntityClickHandler.tsx
services/frontend/src/components/globe/hooks/useCountryHitTest.ts        # Legacy bis Phase D, dann entfernt
services/frontend/src/components/globe/hooks/pointInPolygon.ts          # nach spatial/geometry.ts verschoben, dann entfernt
services/frontend/src/components/globe/hooks/__tests__/pointInPolygon.test.ts  # migriert, dann entfernt
services/frontend/src/components/globe/hooks/__tests__/useCountryHitTest.test.ts # Phase D entfernt
services/frontend/src/components/globe/__tests__/capitalCoverage.test.ts # durch Catalog-/Almanac-Fixture ersetzt
services/frontend/src/components/globe/spotlight/SpotlightContext.tsx
services/frontend/src/components/globe/spotlight/SpotlightOverlay.tsx
services/frontend/src/components/globe/spotlight/SpotlightCartouche.tsx
services/frontend/src/components/globe/visual-layers/CountryBorders.tsx
services/frontend/src/components/worldview/InspectorPanel.tsx
services/frontend/src/components/globe/spotlight/CountryHeader.tsx
services/frontend/public/country-endonyms.json                          # _topoIndex/Legacy-Projektion entfernt
services/frontend/src/components/time/ScrubberMount.tsx
services/frontend/src/hooks/useTimeHistogram.ts
services/frontend/src/hooks/useTimeWindow.ts
services/frontend/src/services/api.ts
services/frontend/src/types/index.ts
```

`WorldviewPage` mountet den Provider nahe am Composition Root. Viewer-Anbindung geschieht über eine Bridge innerhalb des Providers, nicht durch neues Scope-State-Lifting in die bereits große Page.

Der vorhandene `useLocation`-Pfad in `WorldviewPage` behält `layer`, `filter` und
`entity`; er parst `scope` nicht zusätzlich. Genau ein `ReactRouterScopeNavigation`-
Adapter besitzt diesen Parameter, sonst entstehen doppelte Hydration und History-
Schleifen.

In Phase B/C wählt der Composition Root per Flag genau einen Country-Renderer. Der
Spatial-Pfad liest `scopeKey` nur aus validierten Catalog-Pick-IDs; der Legacy-
`useCountryHitTest` kann keinen Scope-Command dispatchen. `CountryTarget`,
`_topoIndex` und der alte Hit-Test verschwinden erst im Phase-D-Cleanup. Circle-
Spotlight für Zoom/Pin/Search bleibt.

Die vorhandene `pointInPolygon.ts`-Logik wird nicht dupliziert. Sie wandert in
`spatial/geometry.ts` und wird für normalisierte/unwrapte Dateline-Ringe gehärtet;
reine Geometrie-Fixtures werden migriert und um Löcher, MultiPolygon und `179/-179`
erweitert. Legacy-Identity-/Hook-Tests existieren nur bis Phase D. Der heutige naive
Longitude-Ray-Cast ist für Dateline-Polygone nicht der Zielalgorithmus.

### 23.3 Backend neu/geändert

```text
services/backend/app/models/spatial.py
services/backend/app/services/spatial_catalog.py
services/backend/app/services/spatial_filters.py
services/backend/app/routers/spatial.py
services/backend/app/config.py
services/backend/app/models/timeline.py
services/backend/app/routers/timeline.py
services/backend/app/models/intel.py
services/backend/app/routers/intel.py
services/backend/app/routers/almanac.py
services/backend/app/services/intel_stream.py
services/backend/app/services/briefing.py
services/backend/app/services/report_store.py
services/backend/app/cypher/report_read.py
services/backend/app/main.py
services/backend/tests/unit/test_spatial_catalog.py
services/backend/tests/unit/test_spatial_router.py
services/backend/tests/unit/test_spatial_filters.py
services/backend/tests/unit/test_timeline_models.py
services/backend/tests/unit/test_timeline_params.py
services/backend/tests/unit/test_timeline_router.py
services/backend/tests/unit/test_timeline_histogram.py
services/backend/tests/unit/test_intel_models.py
services/backend/tests/unit/test_intel_router_reports.py
services/backend/tests/test_intel_stream.py
services/backend/tests/test_report_scope.py
services/backend/data/spatial/source-lock.json
services/backend/data/spatial/catalogs/<catalog-revision>/...  # deterministische Build-Artefakte
```

### 23.4 Data Ingestion

```text
services/data-ingestion/spatial_catalog/...
services/data-ingestion/spatial_catalog/data/country_crosswalk.json
services/data-ingestion/spatial_catalog/catalog-plan.json
services/data-ingestion/infra_atlas/build_country_almanac.py
services/data-ingestion/infra_atlas/data/crosswalk.json   # removed after migration
services/data-ingestion/tests/test_spatial_catalog_*.py
services/data-ingestion/migrations/location_spatial_scope_indexes.cypher
services/data-ingestion/graph_integrity/spatial_normalizer.py
services/data-ingestion/graph_integrity/backfill_spatial_scope.py
services/data-ingestion/graph_integrity/reenrich_spatial_scope.py
services/data-ingestion/tests/test_spatial_normalizer.py
services/data-ingestion/tests/test_backfill_spatial_scope.py
services/data-ingestion/tests/test_reenrich_spatial_scope.py
```

Alle bestehenden Location-/Qdrant-Writer werden schrittweise auf den gemeinsamen Normalizer umgestellt. Kein Parallel-„neues Geomodell“ neben dem alten ohne Migrationsreport.

### 23.5 Intelligence

```text
services/intelligence/spatial.py
services/intelligence/main.py
services/intelligence/graph/state.py
services/intelligence/graph/workflow.py
services/intelligence/agents/react_agent.py
services/intelligence/agents/tools/__init__.py
services/intelligence/agents/tools/qdrant_search.py
services/intelligence/agents/tools/graph_query.py
services/intelligence/agents/tools/graph_templates.py
services/intelligence/agents/tools/gdelt_query.py
services/intelligence/agents/tools/rss_fetch.py
services/intelligence/agents/tools/vision.py
services/intelligence/config.py
services/intelligence/rag/retriever.py
services/intelligence/rag/indexer.py
services/intelligence/rag/qdrant_schema.py
services/intelligence/rag/spatial_reenrich.py
services/intelligence/tests/test_spatial.py
services/intelligence/tests/test_qdrant_search_tool.py
services/intelligence/tests/test_spatial_reenrich.py
services/intelligence/tests/test_workflow.py
```

---

## 24. TDD-Umsetzung in vertikalen Slices

Jeder Slice beginnt rot, implementiert minimal grün, refaktoriert danach und läuft mit den service-lokalen Qualitätskommandos. Kein Slice setzt `pytest.mark.skip` ohne TODO plus Ticket.

### Slice 0 — Catalog Policy, Source Lock und Contract Fixtures

**Ziel:** Bevor UI-Code entsteht, sind Identität, Lizenz, Representation, Wire-Schema und deterministische Artefakte fixiert.

Red Tests:

- `test_scope_key_accepts_canonical_examples`
- `test_shared_contract_symbols_have_one_normative_doc_owner`
- `test_scope_key_rejects_path_and_oversize_input`
- `test_manifest_rejects_broken_lineage`
- `test_manifest_rejects_unknown_parent`
- `test_build_is_byte_deterministic`
- `test_source_hash_mismatch_fails_closed`
- `test_unresolved_admin0_crosswalk_fails_build`
- `test_non_scope_admin0_feature_requires_reviewed_reason`
- `test_odin_country_key_cannot_be_generated_from_display_name`
- `test_kosovo_northern_cyprus_somaliland_policy_fixtures`
- `test_xkx_is_legacy_alias_not_official_iso3_scope`
- `test_antarctica_uses_m49_010_without_invented_iso3`
- `test_country_almanac_and_spatial_catalog_share_one_crosswalk`
- `test_every_pickable_world_child_carries_catalog_canonical_scope_key`
- `test_country_endonyms_topo_index_is_not_a_spatial_identity_input`
- `test_catalog_only_change_carries_forward_derivation_revision`
- `test_ninth_compatible_derivation_revision_fails_build_instead_of_truncating`
- `test_catalog_plan_controls_children_available_without_runtime_fetch`
- `test_antimeridian_fixtures_emit_two_spans`
- `test_asset_budget_is_enforced`
- `test_containment_feasibility_report_covers_required_theaters_and_top_ten_ring_counts`
- `test_drillable_bundle_requires_preferred_child_lod`
- `test_world_pack_report_counts_post_expansion_vertices_and_enforces_lod_budget`

Minimal Green:

- Source Lock mit realen, reviewten Releases;
- `world` plus Natural-Earth-Admin0-Seed;
- ausgewählte Admin-1-Testfixtures, noch kein Vollrollout;
- Manifest/Asset-Validator und Audit-Report.
- gemessener `containment-feasibility.json`-Report für Containment und alle emittierten
  World-Child-Pack-LODs, noch ohne Budget-Ausnahme.

Gate:

- Lizenz/Attribution reviewed;
- Boundary-Policy schriftlich approved;
- topology-aware Tool exakt gepinnt;
- zweiter Build byteidentisch;
- keine unklassifizierten Admin-0-Features; Kosovo, N. Cyprus und Somaliland besitzen
  explizite, getestete Policy-/Alias-Entscheidungen statt Namensfallbacks.
- kein als `client_strict_containment_required` markierter Scope überschreitet die
  reviewten Wire-/Heap-/Ring-/50-m-Error-Gates.
- World-`children_lods`, insbesondere `preferred_lod`, erfüllen nach Arc-Auflösung
  Feature-, Wire-, Heap- und ihr jeweiliges Pack-Vertex-Gate.

### Slice 1 — Frameworkfreier Frontend-Core

**Red Tests:**

- Hydration eines Admin-Deep-Links ohne globalen Query-Flash;
- `world → country → admin1 → ascend`;
- Geschwister-Jump rekonstruiert vollständige Lineage;
- `enter(current)` ist No-op ohne History;
- A→B-Race: A `superseded`, nur B committed;
- zwei pending Resolves desselben Targets teilen einen HTTP-/Asset-Load, erzeugen aber
  höchstens einen semantischen/History-Commit;
- externer Abort ohne neueres Intent liefert `cancelled`, nicht `failed`;
- `ascend` während pending verwendet committed Parent;
- Catalog-Ausfall verändert weder State noch URL;
- fehlende Geometry committed `semantic-only`;
- Popstate schreibt keinen neuen History-Eintrag;
- fremde Query-Parameter bleiben erhalten;
- `/?scope=country%3AUKR` wird mit allen Parametern nach `/worldview` migriert;
- `stop()` abortet Requests/Listener/Leases und ignoriert späte Completion; ein
  anschließendes `start()` hydriert in StrictMode sauber neu.
- StrictMode `start→stop→start` erzeugt genau eine Router-Subscription und keinen
  doppelten Initial-Query.
- fehlendes Router-Echo endet nach Fake-Clock-Timeout mit `URL_SYNC_FAILED`, bewahrt
  committed Store/URL und committed erst nach explizitem Retry.

**Minimal Green:** `contracts.ts`, `scopeController.ts`, Memory-Catalog, Memory-Navigation, React-Adapter. Noch kein Cesium.

### Slice 2 — Backend-Catalog und HTTP-Adapter

**Red Tests:**

- Scope Resolve liefert kanonische Path und Revision;
- manipulierte/zu alte Revision ergibt 409;
- Path Traversal und encoded Slash ergeben 422;
- unbekannter Scope/Asset ergibt 404;
- Asset-ID kann keinen freien Pfad öffnen;
- korruptes Manifest/Hash ergibt 503;
- ETag/304 und immutable Asset-Cache;
- active + previous Revision gleichzeitig bedienbar.
- Bootstrap liefert die strikt begrenzte, reviewte Attributionsprojektion;
- fehlende, malformed oder übergroße Attribution ergibt 503/CATALOG_UNAVAILABLE;
- gesättigte Asset-Semaphore liefert `429 ASSET_BUSY` plus `Retry-After`, ohne eine
  Datei zu öffnen; Cancellation gibt den Slot frei.

**Minimal Green:** Backend-Service/Router, lokale Assets, Frontend-HTTP-Adapter und Validator.

### Slice 3 — Cesium World→Country, Breadcrumb und Spotlight-Migration

**Red Tests:**

- Country-Pick dispatcht Scope und separate Country-Selection;
- Spatial-Country-Pick verwendet exakt den Catalog-`scopeKey`; Kosovo erzeugt nie
  `country:XKX`, und `_topoIndex` wird nicht gelesen;
- Flag off mountet nur Legacy, Flag on nur Spatial; nie beide Renderer/Click-Handler;
- Legacy-Country-Hit kann keinen Spatial-Command dispatchen;
- Country-Inspector lädt Almanac über den committed kanonischen Scope; fehlender
  Almanac ändert Scope/URL nicht;
- operatives Entity gewinnt über transparente Child-Fläche;
- blank click löscht Scope nicht;
- stale Primitive-Generation wird zerstört und nie gezeigt;
- alter Container wird beim Commit verborgen;
- Kamera-LOD-Swap behält dagegen die semantisch gleiche alte LOD bis ready und ändert
  weder `stateRevision` noch Query/URL;
- Kamera-LOD-Swap ändert für feste Testpunkte niemals das Containment-Ergebnis;
- eine Fixture mit absichtlich abweichenden Overview-/Regional-Grenzen liefert für
  denselben kartographischen Punkt vor und nach Kamera-LOD-Swap stets das Child aus
  `childrenLods[preferredLod]`;
- Presenter-Fehler rollt Scope nicht zurück;
- reduced motion setzt Flight-Duration null;
- Listener und Primitives werden auf Unmount entfernt;
- 100 synthetische Wechsel halten Containerzahl konstant;
- Escape führt genau eine priorisierte Action aus.
- Scope-Commit löscht ungeprüfte operative Selection, bewahrt aber das Ziel-Country-
  Almanac; fehlgeschlagener Resolve verändert Selection/Spotlight nicht.

**Minimal Green:** World/Country-Boundary, feste Preferred-LOD-Pickfläche, Country-
Children, Breadcrumb und Kamera-Fit. `CountryTarget` bleibt ausschließlich im flag-off
Legacy-Zweig; im flag-on Zweig wird er weder geschrieben noch gerendert. Das ist
temporärer, wechselseitiger Rollback-Code, kein doppelter Laufzeit-Renderer.

### Slice 4 — CHRONIK mit ehrlicher BBox-Approximation

**Red Tests:**

- `scope_key + bbox` ergibt 422;
- Backend löst Scope, nicht Client-Bounds;
- Fiji/Dateline compiliert korrekt;
- Response meldet `bbox_approximate + partial`;
- Scope A→B löscht A-Histogramm sofort;
- schon der erste Render mit B-Props gated das noch gespeicherte A-Envelope, ohne auf
  einen Effect zu warten;
- verspätete A-Antwort bleibt unsichtbar;
- Response mit abweichendem echoed Scope/Revision wird als Contract-Fehler verworfen;
- Backend-Ausfall liefert keinen globalen Fallback;
- Movement-Response unterscheidet `intersects` von Event-`occurs-in`.
- Scope-Wechsel bewahrt CHRONIK-Cursor/Range/Mode/Speed, Zeit-Seek bewahrt Scope.

**Minimal Green:** strukturierter Scope in Timeline-Requests, Katalog-BBox-Projektion,
Response-Accounting, Scrubber-Badge und initiale CHRONIK-Capability-Registry. Slice 8
erweitert dieselbe Registry erst später um weitere aktivierte Layer.

### Slice 5 — Admin-1, Picking und Hover-Prefetch

**Red Tests:**

- Country-Bundle liefert direkte Admin-1-Children und valide Lineage;
- 200-ms-Dwell, Leave-Abort, Concurrency zwei;
- Click übernimmt laufenden Prefetch ohne doppelten HTTP-Request;
- Prefetch mutiert State/URL/Kamera nie;
- Admin-1-Deep-Link funktioniert ohne vorherigen Country-Besuch;
- Geometry-Budget und LRU-Eviction;
- Touch/save-data deaktivieren Hover-Prefetch.

**Minimal Green:** ausgewählte Theater-Admin-1-Daten, Child-Pack, Admin-Drill.

**Post-Slice-5 Rollout/Cleanup-Gate:** Nach Canary und einer default-on Soak-Periode
entfernt Phase D `CountryTarget`, `useCountryHitTest`, `_topoIndex`, die alten Tests
und das Feature-Flag. Ein Bundle-/Static-Import-Test beweist, dass kein Produktionspfad
die Legacy-Dateien referenziert. Vor diesem Gate bleibt Flag-off ein gültiger
Rollback; danach erfolgt Rollback per vorherigem Frontend-Artefakt.

### Slice 6 — Neo4j-Normalisierung und exact CHRONIK

**Red Tests:**

- GDELT/FIPS `UP` wird über Codesystem zu `country:UKR`, nie per ISO-Annahme;
- Rawcode/Codesystem bleiben erhalten;
- Country-only ohne Punkt erhält keinen Admin-1-Key;
- widersprüchliche Quellen setzen Conflict und werden ausgeschlossen;
- Writer setzt `geo=point(...)` und Scope-Keys parametergebunden;
- Backfill dry-run schreibt nichts;
- Apply ist idempotent und restartbar;
- static template registry enthält keine dynamischen Property-Namen;
- Event mit zwei passenden `OCCURRED_AT`-Locations erscheint einmal; `LIMIT`,
  `total_count` und `included_count` zählen distinct Events;
- Query-Plan-/Index-Smoke;
- Response-Accounting stimmt für located/unlocated/conflict.
- neue Derivationsrevision erzeugt restartbaren Dry-run/Apply-Re-Enrichment-Job;
  Carry-forward derselben Derivationsrevision erzeugt keinen Rewrite.

**Gate:** Coverage-Report approved; exact wird pro Lane/Kind geschaltet, nicht pauschal.

### Slice 7 — Qdrant und Munin Scope Enforcement

**Red Tests:**

- Schema-Validator verlangt neue Keyword-/Geo-Indizes;
- Qdrant-Re-Enrichment ersetzt alle `spatial_*`-Felder atomar und ist nach Cursor-
  Resume idempotent;
- `about`, `occurrence`, `either` compilen erwartete Filter zusätzlich zur Corpus-Policy;
- Modell-Tool-Schema enthält `query`, aber keinen Scope/Region-Override;
- scoped Tool-Binding enthält weder GDELT noch RSS; ein dennoch konstruierter direkter
  Call wird vor HTTP fail-closed;
- Vision-Tool-Schema enthält keine Bild-URL und verwendet nur das attached image aus
  Runtime-State;
- `ToolRuntime` liefert den committed Run-Scope;
- scoped Graph-Run nutzt nur statische Templates;
- fehlendes Template failt closed;
- Qdrant-Ausfall/keine Treffer löst keine globale Suche aus;
- Run-Ergebnis echoed Scope-Key/Revision;
- UI-Scope-Wechsel etikettiert laufenden alten Run nicht um;
- `region + spatial_scope` ergibt 422.
- `use_legacy + spatial_scope` ergibt 422 und scoped ReAct fällt bei Fehler nicht in
  Legacy zurück.
- Country-Briefing resolved den Scope serverseitig; Legacy-Alias findet vorhandenes
  Dossier, und Doppelbestand wird geloggt statt automatisch gemerged.

**Gate:** Writer vor Backfill, Payload-Indizes vor Reindex, Coverage pro Corpus-Lane sichtbar.

### Slice 8 — weitere Layer, Admin-2 und datengetriebene 3D-Metrik

Dieser Slice startet erst, wenn V1-Performance und Truthfulness bewiesen sind.

Separate Tests/Gates:

- Layer-Capability-Matrix für jeden aktivierten Layer;
- Point-in-Boundary versus BBox korrekt beschriftet;
- Scope-Commit invalidiert alten Containment-Index vor dem ersten neuen Layer-Render;
- Track-Intersection clippt keine Trackpunkte;
- Admin-2-Cardinality bleibt im Pack-Limit oder verwendet einen neu reviewten Tiling-Vertrag;
- jede Extrusion besitzt Metrik, Einheit, Zeitbasis, Scale, Legende und Missing-Value-Semantik;
- keine dekorative Höhe/Arc.

---

## 25. Testkommandos und Verifikation

Aus den jeweiligen Service-Verzeichnissen:

```bash
# Frontend
cd services/frontend
npm run lint
npm run type-check
npm test

# Backend
cd services/backend
uv run pytest
uv run ruff check app/
uv run mypy app/

# Intelligence
cd services/intelligence
uv run pytest

# Data Ingestion
cd services/data-ingestion
uv run pytest
```

Zusätzliche E2E-/manuelle Matrix:

| Fall | Erwartung |
|---|---|
| frischer `/worldview`-Load | ein World-Commit, kein doppelter Query |
| Admin-Deep-Link | kein globaler CHRONIK-Flash |
| A→B→C schnell | nur C sichtbar/querybar |
| Browser Back/Forward | besucht URLs, keine History-Schleife |
| Breadcrumb Parent | semantischer Parent, eigener History-Eintrag |
| Dateline-Scope | kleiner Kamerafit, keine Weltumrundungs-BBox |
| Boundary-Netzfehler | semantic-only, kein altes Polygon |
| Neo4j/Qdrant-Ausfall | scoped Fehler, kein globales Ergebnis |
| Reduced Motion | keine Fluganimation |
| 12-h Soak/100 Zyklen | keine wachsenden Primitives/Listener/Caches |

---
