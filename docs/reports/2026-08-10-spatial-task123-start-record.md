# Spatial Scope TASK-123 — Mandatory Start Record

**Datum:** 2026-08-10

**Branch:** `feat/spatial-plan03`

**Start-HEAD:** `a6e6416e499210b7509e8c017ee76e2b82100bfa`
(`a6e6416 docs(spatial): hand off TASK-123 gates`)

**Remote-Prüfung:** Nach `git fetch origin feat/spatial-plan03` beträgt die
Divergenz zwischen `HEAD` und `origin/feat/spatial-plan03` exakt `ahead 0,
behind 0`.

**Status:** Kriterien 6 und 9 sind aktuelle Regression-Passes. Kriterien 1–5, 7
und 8 benötigen Code. Plan 05D bleibt gesperrt und wird nicht ausgeführt.

## Worktree-Schutzgrenze

Beim Start waren genau diese fremden Einträge vorhanden:

```text
 M docs/CONTAINER-STATUS.md
 M scripts/spark/odin-spark-vllm.sh
?? docs/superpowers/plans/2026-08-10-task-104-phase2-qdrant-bm25-hybrid.md
```

Sie werden weder geändert noch formatiert, gestaged, zurückgesetzt oder
committed. Alle TASK-123-Staging-Sets werden vor jedem Commit wertgenau geprüft.

## Wertgenauer Status der neun Kriterien

| Kriterium | Status | Aktuelle Produktions- und Consumer-Evidenz |
|---:|---|---|
| 1 | `code required` | `SpatialCountryHeader` und `useSpatialCountryAlmanac` konsumieren Facts bereits per committed `SpatialQueryRef`; Signals und Briefing laufen im Legacy-Pfad noch über Country-ID-Routen und fehlen im Spatial-Panel. |
| 2 | `code required` | `MutuallyExclusiveCountryPath` beweist genau einen Renderer-/Click-Pfad, aber der produktive Flag-on-Inspector besitzt noch keine vollständige Paritätsmatrix und verliert derzeit Signals, Briefing, Save/Open und Capability-Anzeige. |
| 3 | `code required` | `SpatialScopeBreadcrumb` zeigt `scope.pending` sichtbar als rohes `Opening ...`; die Live-Region wird nur für Pending/Problem gemountet. |
| 4 | `code required` | Die Cartography-Disclosure in `LayersPanel` ist ein Link und ihr `aria-controls`-Ziel fehlt im geschlossenen Zustand. |
| 5 | `code required` | `formatCoords()` ist kanonisch und getestet, wird aber von Legacy- und Spatial-Country-Header nicht konsumiert; beide hängen hart `N`/`E` an. |
| 6 | `pass` | Produktionskette: `WorldviewPage` erzeugt den `SpatialContainmentController`; `scopeController` committet dessen Lifecycle; `containment.ts` importiert `createBoundaryGeometryIndex` aus `spatial/geometry.ts`; `EarthquakeLayer` konsumiert den darauf gebauten strikten Punktadapter. Der aktuelle fokussierte Consumer-Lauf ist 7 Dateien / 54 Tests grün und umfasst Geometry, Containment, Point-Adapter, Earthquake-Renderer und WorldView-Integration. |
| 7 | `code required` | Der Primitive-Builder besitzt drei harte Cesium-Farbstrings. Die Pick-Primitive ist stabil gepinnt, aber Child-Render-Geometrie verwendet noch den bevorzugten statt des kameraabhängigen LOD-Descriptors. |
| 8 | `code required` | Der Legacy-Hit-Test verwirft ungültige Features diagnoselos und indexiert Dateline-Geometrie mit einer globalen `[-180, 180]`-BBox. |
| 9 | `pass` | Produktionskette: `WorldviewPage` importiert und konsumiert `applyLayerSpatialPolicy` sowie `layerSpatialStatuses`; das Ergebnis gated Fetch/Render und wird an `LayersPanel` übergeben, das die Status-Badges rendert. Derselbe aktuelle Lauf (7 Dateien / 54 Tests) enthält Registry-, WorldView-Policy- und LayersPanel-Consumer-Tests. |

Ausgeführt wurde:

```text
npm test -- src/spatial/__tests__/geometry.test.ts \
  src/spatial/__tests__/containment.test.ts \
  src/spatial/__tests__/pointLayerSpatialAdapter.test.ts \
  src/spatial/__tests__/layerScopePolicy.test.ts \
  src/components/layers/__tests__/EarthquakeLayer.test.tsx \
  src/test/pages/worldviewPageSpatialPolicy.test.tsx \
  src/components/worldview/LayersPanel.test.tsx

Test Files  7 passed (7)
Tests      54 passed (54)
```

Ein isolierter Helper ist damit nicht die alleinige Pass-Evidenz: Beide Kriterien
reichen bis zu ihren produktiven WorldView-, Layer- und Presenter-Consumern.

## Beobachtbare Inspector-Paritätsmatrix und Produktentscheidungen

Die Matrix beschreibt den Zustand am Start. `migrieren` ist die versionierte
Produktentscheidung für TASK-123; keine sichtbare Legacy-Funktion wird still
entfernt.

| Beobachtbare Funktion | Legacy, Flag off | Spatial, Flag on am Start | Entscheidung und kanonischer Consumer |
|---|---|---|---|
| Inspector-Titel | Country-Target-Name | kanonische Selection-Label | `beibehalten`; Spatial bleibt Selection-Präsentation, nie Identitätsquelle |
| Capital und Koordinaten | Legacy-Almanac | Spatial-Facts | `beibehalten`; Facts aus demselben committed Query, Koordinaten über gemeinsamen Formatter |
| Facts und fünf Tabs | vorhanden | vorhanden | `beibehalten`; `GET /api/almanac/country` über den committed Query |
| Active ODIN Signals | vorhanden | fehlt | `migrieren`; kanonische Signals-Route mit exakt demselben Query |
| Briefing-Generierung und Streamingstatus | vorhanden | fehlt | `migrieren`; kanonische Briefing-Route mit exakt demselben Query |
| Briefing-Ergebnis | vorhanden | fehlt | `migrieren`; generation- und selection-key-gesicherter Spatial-Hook/Panel-Consumer |
| Save in Briefing Room | vorhanden | fehlt | `migrieren`; admin-geschützte kanonische Save-Route nach exakter serverseitiger Scope-Auflösung |
| Open in Briefing Room | nach erfolgreichem Save vorhanden | fehlt | `migrieren`; Link ausschließlich aus dem für denselben Query bestätigten Save-Ergebnis |
| Capability-Anzeige | fünf Capability-Badges | fehlt | `migrieren`; reine Präsentation im gemeinsamen Panel, keine Identity- oder Capability-Promotion |
| Loading-/Unavailable-Zustände | pro Consumer sichtbar | nur Facts sichtbar | `migrieren`; jeder Spatial-Consumer bleibt getrennt sichtbar und fail-closed |

## Kanonische Route und Identitätsentscheidung

Alle Spatial-Inspector-Operationen verwenden genau einen internen Backend-Resolver
für `scope_key + catalog_revision`. Er löst ausschließlich einen Country-Scope der
angeforderten, bedienten Revision auf und liefert das vorhandene Almanac-Objekt plus
den daraus abgeleiteten serverseitigen Scope-Token. Kein Spatial-Request retryt
gegen die aktive Revision oder fällt auf Country-ID, ISO3, M49, Displayname oder
`world` zurück.

Gewählte Adapter:

| Funktion | Spatial-Route |
|---|---|
| Facts | `GET /api/almanac/country?scope_key=&catalog_revision=` |
| Signals | `GET /api/almanac/country/signals?scope_key=&catalog_revision=&limit=` |
| Briefing-Generierung | `POST /api/almanac/country/briefing?scope_key=&catalog_revision=` |
| Briefing-Save | `POST /api/almanac/country/briefing/save?scope_key=&catalog_revision=` |

Frontend-API, Hooks und Panel erhalten für alle vier Funktionen denselben
`SpatialQueryRef`. Der Selection-Key muss vor jedem State-Commit weiterhin dem
Query-Scope entsprechen. Die alten `/countries/{country_id}/...`-Routen bleiben
für den wechselseitig gemounteten Legacy-Pfad unverändert.

Save bleibt als freigegebene Funktion erhalten. Er speichert unter dem exakt
serverseitig aufgelösten kanonischen Scope. Der bestehende Sicherheitsvertrag von
`build_hydration_patch()` bleibt unverändert: Eine browsergelieferte
`SpatialRunApplicationV1` wird nicht als vertrauenswürdig persistiert.

## Run-Receipt- und Stop-Entscheidungen

Ein authentisierter, server-owned Briefing-Run-Receipt ist ausdrücklich **nicht Teil
von TASK-123**. Die beschlossene Parität benötigt ihn nicht: Generierung erhält den
serverseitig aufgelösten Scope-Token; Save übernimmt nur den bestehenden,
admin-geschützten und gegen browsergelieferte Spatial-Attestierung gehärteten
Persistenzvertrag. Sollte die Parität später einen vertrauenswürdigen Run-Receipt
verlangen, stoppt dieser Zweig statt einen Browser-Receipt zu akzeptieren.

Folgende Grenzen werden wertgenau gestoppt beziehungsweise nicht geöffnet:

- Plan 05D: `external evidence required` und `product decision required` für reale
  Default-on-Veröffentlichung, vereinbarten Soak, getesteten Artefakt-Rollback und
  explizite Phase-D-Freigabe. Keine Legacy-/Flag-Löschung in TASK-123.
- Graph-Allowlist-Follow-ups, sichtbares `SpatialRunApplicationV1`, die
  `SpatialApplication`-Namensbereinigung, Data-Ingestion-Skip-Bereinigung,
  Admin-2, 3D und gestoppte Plan-08-Zweige: außerhalb dieses Plans.
- Keine der in der Paritätsmatrix beibehaltenen Inspector-Funktionen benötigt eine
  neue externe Abhängigkeit oder offene Produktentscheidung. Trifft bei der
  Umsetzung dennoch eine Stop-Regel aus dem Handoff zu, wird sie mit harter Evidenz
  dokumentiert und nicht durch Fallback, Testabschwächung oder Funktionsentfernung
  umgangen.

Es erfolgen kein Deployment, Katalog-Publish, Datenbank-Write, Push, PR oder Merge.
