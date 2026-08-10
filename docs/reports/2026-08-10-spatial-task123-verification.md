# Spatial Scope TASK-123 — Abschlussverifikation

**Datum:** 2026-08-10

**Branch:** `feat/spatial-plan03`

**Start-HEAD:** `a6e6416e499210b7509e8c017ee76e2b82100bfa`
(`a6e6416 docs(spatial): hand off TASK-123 gates`)

**Mandatory Start Record:**
`87a2c18 docs(spatial): record TASK-123 readiness gates`

**Code-Work-Orders:**

1. `3827f4c feat(worldview): close spatial inspector parity`
2. `95054a3 fix(worldview): close spatial accessibility parity`
3. `9d422c1 fix(worldview): align spatial palette and render lod`
4. `6b6cf9b fix(worldview): harden legacy spatial diagnostics`

**Abschlussrecord:** `docs(spatial): close TASK-123 readiness gates`
(der Commit, der diesen Record und den TASKS-Status enthält)

**Status:** Alle neun TASK-123-Kriterien sind mit Produktionsconsumer- und
Testevidenz erfüllt. TASK-123 ist abgeschlossen. Plan 05D wurde nicht ausgeführt
und bleibt durch Default-on-Release, Soak, Artefakt-Rollback und die explizite
Phase-D-Entscheidung blockiert.

## Ergebnis und Scope-Grenze

TASK-123 blieb genau der im Handoff definierte begrenzte Implementierungsplan:
Mandatory Start Record, vier testgetriebene Code-Work-Orders und dieser
Abschlussrecord. Es wurde kein Plan 09 erfunden und keine Legacy-Löschung
vorgezogen.

Der Flag-on-Country-Inspector besitzt nun die freigegebene sichtbare
Legacy-Parität. Alle datenliefernden Spatial-Inspector-Operationen verwenden den
exakt committed `SpatialQueryRef` aus `scope_key + catalog_revision`. Breadcrumb,
Cartography-Disclosure und Koordinaten erfüllen die Accessibility- und
Darstellungsverträge. Cesium trennt kameraabhängige Child-Render-Geometrie von der
fest gepinnten Preferred-LOD-Pick-Geometrie. Der weiterhin produktive Legacy-
Hit-Test meldet ungültige Geometrie begrenzt und indexiert Dateline-Polygone über
minimale Spans.

Unverändert erhalten blieben insbesondere:

- `VITE_SPATIAL_SCOPE_ENABLED` und der wechselseitige Flag-on/Flag-off-Pfad;
- `CountryTarget`, `useCountryHitTest`, `_topoIndex` und der Legacy-Renderer;
- die in Plan 08 aktivierte Containment- und Layer-Capability-Architektur;
- die Legacy-Country-ID-Routen für den noch vorhandenen Legacy-Inspector.

## Acceptance-Matrix: neun von neun

| Kriterium | Ergebnis | Code- und Produktionsconsumer-Evidenz | Testevidenz |
|---:|---|---|---|
| 1 | `pass` | Backend: ein Resolver `_resolve_committed_country_scope()` für Facts, Signals, Briefing und Save; neue Routen `/api/almanac/country[/signals|/briefing|/briefing/save]`. Frontend: `api.ts`, `useSpatialCountryAlmanac`, `useSpatialCountrySignals`, `useSpatialCountryBriefing`, `SpatialCountryAlmanacPanel` und `SpatialCountryHeader` reichen denselben committed Query durch. Kein Country-ID-, Displayname-, aktive-Revision- oder World-Fallback. | 22/22 fokussierte Backendtests; aktueller Frontend-Paritätslauf 4 Dateien / 21 Tests; Full Gates grün. Stale/invalid/non-country/unknown/missing catalog fail-closed sowie A→B-Races für Facts, Signals, Briefing-Chunks und Save sind abgedeckt. |
| 2 | `pass` | Der produktive `InspectorPanel` rendert im Spatial-Country-Pfad Titel, Capital, fünf Facts-Tabs, Signals, Briefing-Generierung/-Status/-Ergebnis, Save/Open und fünf Capability-Badges. Keine freigegebene Legacy-Funktion wurde entfernt. | Produktionskompositions-, Hook-, API- und Paneltests; ursprünglicher fokussierter GREEN-Lauf 28/28, aktueller enger Paritäts-Recheck 21/21. |
| 3 | `pass` | `SpatialScopeBreadcrumb` hält genau eine höfliche, atomare Live-Region stabil gemountet. Pending verwendet neutrales `Opening spatial scope…`, Unavailable eine konsistente Meldung; rohe Scope-Keys erscheinen nicht als sichtbares Opening-Label. Native Buttons bewahren den Fokus über den Commit. | Gemeinsamer Accessibility-Lauf 5 Dateien / 36 Tests einschließlich Idle→Pending→Unavailable→Idle und Focus. |
| 4 | `pass` | `CartographyProvenance` verwendet `button type="button"`; `aria-expanded` und `aria-controls` verweisen in beiden Zuständen auf denselben stabil gemounteten, geschlossen `hidden` gesetzten Region-Container. | Derselbe 36/36-Lauf enthält Semantik-, Zielstabilitäts- und Focustests. |
| 5 | `pass` | Legacy- und Spatial-`CountryHeader` sowie der ohne Scope-Ausweitung bereinigte `InspectorPanel` konsumieren `formatCoords()`. Negative Breite/Länge werden als S/W und nicht als negative N/E-Werte ausgegeben. | Formatter-, Header- und Inspector-Fixtures für N/E und S/W im 36/36-Lauf. |
| 6 | `pass` | Plan-08-Produktionskette bleibt intakt: `WorldviewPage` besitzt den `SpatialContainmentController`; `containment.ts` importiert `createBoundaryGeometryIndex` aus `spatial/geometry.ts`; der strikte Punktadapter wird von `EarthquakeLayer` konsumiert. Work-Order 4 exportierte und korrigierte nur die bereits vorhandene minimale Longitude-Span-Primitive für gemeinsame Nutzung; Containment-Port, Lifecycle, Pick-Identität und State-Revision-Vertrag blieben unverändert. | Aktueller Regressionlauf: 7 Dateien / 55 Tests für Geometry, Containment, Point-Adapter, Registry, Earthquake, WorldView-Policy und LayersPanel. |
| 7 | `pass` | `hlidskjalfCesiumPalette.ts` besitzt die drei typisierten Rollen `activeFill`, `scopeOutline`, `childPickSurface` aus den kanonischen `--steel`-/`--stone`-Tokens. Adapter und Builder führen `childRenderAsset` und `childPickAsset` getrennt; nur Render-Primitives wechseln kameraabhängig, die Pick-Primitive bleibt auf `childrenLods[preferredLod]`. Gleiche Asset-IDs werden lease-seitig dedupliziert. | 3 Dateien / 26 Tests. Der 100-Swap-Test belegt 101 Builds, unveränderte Pick-Objektidentität, einen Container, Primitive-High-Water ≤3, Listenerzahl 1 und höchstens 2 aktive Leases; 202/202 Leases freigegeben. |
| 8 | `pass` | `buildCountryIndex()` konsumiert `minimalLongitudeSpans()` aus der gemeinsamen produktiven `spatial/geometry.ts`. Dateline-Polygone erhalten westliche/östliche Nodes statt `[-180,180]`. Der echte Hook übergibt einen strukturierten Console-Diagnostic-Consumer; maximal zehn Rejections werden je Feature-Index gemeldet, weitere einmal mit `suppressedCount` zusammengefasst. Events enthalten weder Namen, M49-Werte, Koordinaten noch Geometrien. | 2 Dateien / 18 Tests: exakte Spans `[-180,-179]` und `[179,180]`, leere RBush-Kandidatenmenge bei 0°, Treffer bei ±179.5°, Diagnose-Limit/-Payload sowie MultiPolygon-, Hole-, Boundary- und Invalid-Click-Regressionen. |
| 9 | `pass` | Plan-08-Produktionsconsumer bleiben intakt: `WorldviewPage` konsumiert `applyLayerSpatialPolicy()` und `layerSpatialStatuses()` für Fetch/Render-Gates; `LayersPanel` rendert die daraus erzeugten Badges. `LAYER_SPATIAL_CAPABILITIES` ist damit keine tote zweite Wahrheitsquelle. | Derselbe aktuelle 7-Dateien-/55-Tests-Regressionlauf umfasst Registry-Invarianten, WorldView-Policy und sichtbare Badge-Consumer. |

Kriterien 6 und 9 wurden nicht als isolierte Helper-Passes gewertet. Ihr fokussierter
Abschlusslauf reichte erneut bis zu WorldView, produktivem Layer und Presenter.

## Verbindliche Inspector-Produktentscheidungen

Die Paritätsmatrix des
[Mandatory Start Record](2026-08-10-spatial-task123-start-record.md) wurde ohne
stille Funktionsentfernung umgesetzt:

| Beobachtbare Funktion | Entscheidung im Start Record | Abschluss |
|---|---|---|
| Inspector-Titel | `beibehalten`; Selection-Label bleibt Präsentation | produktiver Spatial-Consumer vorhanden; keine Identity-Ableitung aus dem Label |
| Capital und Koordinaten | `beibehalten`; Facts plus gemeinsamer Formatter | umgesetzt |
| Facts und fünf Tabs | `beibehalten`; committed Query | umgesetzt |
| Active ODIN Signals | `migrieren`; exakte Signals-Route | umgesetzt |
| Briefing-Generierung und Streamingstatus | `migrieren`; exakte Briefing-Route | umgesetzt |
| Briefing-Ergebnis | `migrieren`; Generation-/Selection-Guard | umgesetzt |
| Save in Briefing Room | `migrieren`; admin-geschützter exakter Scope | umgesetzt |
| Open in Briefing Room | `migrieren`; Link nur aus querygleichem Save | umgesetzt |
| Capability-Anzeige | `migrieren`; reine Präsentation | umgesetzt |
| Loading/Unavailable | `migrieren`; getrennt und fail-closed | umgesetzt |

Save bleibt bewusst erhalten. `build_hydration_patch()` verwirft weiterhin eine
browsergelieferte `SpatialRunApplicationV1`; TASK-123 erklärt sie nicht zur
vertrauenswürdigen Attestierung. Ein authentisierter server-owned Briefing-Run-
Receipt war für die freigegebene Parität nicht erforderlich und bleibt ein
ausdrückliches Nicht-Ziel.

## Strikte TDD-Evidenz je Work-Order

### Work-Order 1 — Inspector-Parität

RED vor Produktionscode:

```text
Backend:  5 failed, 17 passed (fehlende kanonische Routen/Verträge)
Frontend: 5 Testdateien fehlgeschlagen (fehlende API-, Hook- und Consumer-Parität)
```

GREEN/REFACTOR/VERIFY:

```text
focused backend                  22/22
focused frontend (WO-Lauf)       28/28
full backend                    579/579 + Ruff + MyPy (88 Source Files)
full frontend                   602/602 + ESLint + TypeScript + Build
commit                          3827f4c
```

### Work-Order 2 — Accessibility und Koordinaten

```text
RED                              9 failed, 27 passed
focused GREEN                    5 Dateien, 36/36
full frontend                   603/603 + ESLint + TypeScript + Build
commit                          95054a3
```

### Work-Order 3 — Palette und LOD-Eigentum

```text
RED palette                      fehlendes Palettenmodul
RED adapter                      7 failed, 10 passed
focused GREEN/REFACTOR           3 Dateien, 26/26
full frontend                   609/609 + ESLint + TypeScript + Build
commit                          9d422c1
```

### Work-Order 4 — Legacy-Diagnostik und Dateline

```text
RED                              3 failed, 15 passed
focused GREEN/REFACTOR           2 Dateien, 18/18
full frontend                   612/612 + ESLint + TypeScript + Build
commit                          6b6cf9b
```

Kein bestehender Test wurde entfernt, abgeschwächt oder übersprungen, um einen
Work-Order grün zu machen.

## Abschließende Service-Gates

Die Befehle liefen aus den jeweiligen Serviceverzeichnissen einschließlich
`npm install` beziehungsweise `uv sync`:

| Service | Abschlussergebnis |
|---|---|
| Frontend | 109 Testdateien, 612/612 Tests; ESLint sauber; TypeScript strict sauber; Vite-Produktionsbuild erfolgreich (320 Module) |
| Backend | 579/579 Tests; Ruff `All checks passed`; MyPy ohne Findings in 88 Source Files |
| Intelligence | 449/449 Tests |
| Data Ingestion | 1368 bestanden, 1 bestehender conditional Skip, 17 deselected |
| Gesamt | 3008 bestandene Tests über die vier Services |

Der Data-Ingestion-Skip ist
`tests/test_gdelt_integration.py::test_full_forward_tick_against_real_stores`
beziehungsweise dessen bestehendes `skipif`, wenn die Dev-Compose-Services nicht
laufen. Seine Bereinigung war im
Handoff ausdrücklich außerhalb von TASK-123. Die 17 Deselections stammen aus der
bestehenden Testkonfiguration; es wurde keine Selektion für TASK-123 gelockert.

`npm install` meldete 427 auditierte Pakete und 9 Dependency-Hinweise (2 moderate,
7 high). Es wurde kein automatisches `npm audit fix` mit unkontrollierten
Versionsänderungen ausgeführt. Der Build meldet den bekannten Hinweis auf Chunks
über 500 kB; Build und Tests bleiben grün. Vitest meldet außerdem einmal die
bekannte jsdom-Navigationsmeldung `Not implemented: navigation to another Document`.

## Branch-, Worktree- und Delivery-Audit

Der abschließende Fetch vor Erstellung dieses Record-Commits bestätigte:

```text
origin/feat/spatial-plan03  a6e6416e499210b7509e8c017ee76e2b82100bfa
Code-HEAD                   6b6cf9b3dd8524aa3ddb034a9b039b4bdbc5ee47
Divergenz vor Record        ahead 5, behind 0
Divergenz mit Record        ahead 6, behind 0
```

Die beim Mandatory Start vorhandenen fremden Worktree-Einträge sind noch exakt
vorhanden und blieben außerhalb jedes Staging-Sets und Commits:

```text
 M docs/CONTAINER-STATUS.md
 M scripts/spark/odin-spark-vllm.sh
?? docs/superpowers/plans/2026-08-10-task-104-phase2-qdrant-bm25-hybrid.md
```

Weder `services/data-ingestion/uv.lock` noch ein Frontend-Lockfile wurde durch die
Abschluss-Synchronisation verändert. Es erfolgte kein Push, Pull Request, Merge,
Deployment, Katalog-Publish, Datenbank-/Katalog-Write oder Legacy-Delete.

## Bekannte Verifikationsgrenzen und Plan-05D-Gate

- Die Frontendtests sind hermetische Vitest/jsdom-Tests. Der Cesium-Builder wird
  real konstruiert, der 100-Swap-Test nutzt jedoch einen kontrollierten Runtime-
  Adapter; daraus wird kein neuer Production-Browser-/GPU-Soak behauptet.
- Die Backend- und Service-Suiten verwenden ihre vorhandenen Testdoubles und
  lokalen Fixtures; es gab keinen Live-Produktionslauf und keine operative
  Datenbankmutation.
- Kein server-owned Briefing-Run-Receipt, keine Graph-Allowlist-Erweiterung, keine
  `SpatialApplication`-Namensbereinigung und kein sichtbares
  `SpatialRunApplicationV1`-Rendering wurden hinzugefügt.
- Admin-2, 3D, gestoppte Plan-08-Zweige und Data-Ingestion-Skip-Bereinigung bleiben
  außerhalb von TASK-123.
- Plan 05D bleibt trotz abgeschlossenem TASK-123 gesperrt: Es fehlen weiterhin eine
  reale Default-on-Veröffentlichung, der vereinbarte Soak, ein getesteter
  Artefakt-Rollback und die ausdrückliche Phase-D-Produktentscheidung.

TASK-123 schließt damit ausschließlich seine neun Readiness-Kriterien. Es erteilt
keine Freigabe für Plan 05D, Legacy-Löschung oder Deployment.
