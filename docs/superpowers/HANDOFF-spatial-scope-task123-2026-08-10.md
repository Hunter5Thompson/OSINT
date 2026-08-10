# HANDOFF — Spatial Scope TASK-123 — Plan-05D Readiness Code Gates

**Datum:** 2026-08-10

**Nächster Auftrag:** `TASK-123` testgetrieben schließen; Plan 05D noch nicht
ausführen

**Branch:** `feat/spatial-plan03`

**Repo:** `/home/deadpool-ultra/ODIN/OSINT`

**Start-HEAD vor diesem Handoff:** `78e019b`
(`docs(spatial): hand off Plan 05D readiness`)

**Remote-Basis vor diesem Handoff:** `origin/feat/spatial-plan03` bei `78e019b`

**Divergenz vor diesem Handoff:** ahead 0, behind 0

**Task-Status:** `TASK-123` ist offen. Kriterien 6 und 9 sind durch Plan 08
geschlossen und bleiben Regression-Gates. Kriterien 1–5, 7 und 8 sind offen.

## Verbindlicher Planentscheid

`TASK-123` ist **ein einzelner, begrenzter Implementierungsplan** mit einem
Mandatory Start Record, vier Code-Work-Orders und einem Abschlussrecord. Es sind
weder mehrere neue Pläne noch ein Plan 09 erforderlich.

Die Arbeit ist auch nicht vollständig „nur Kleinkram“:

- Inspector-Parität über Backend und Frontend ist ein mittleres Contract-Gate.
- Breadcrumb, Disclosure und Koordinaten sind ein kleines gemeinsames UI-Gate.
- Cesium-Palette und getrenntes Render-/Pick-LOD-Eigentum sind ein mittleres
  Adapter-Gate.
- Legacy-Diagnostik und Dateline-RBush-Spans sind ein kleines bis mittleres,
  lokal begrenztes Index-Gate.

Diese vier Work Orders teilen dasselbe Ziel und dieselbe Freigabebedingung:
beobachtbare Flag-on-Parität vor Entfernung des Legacy-Pfads. Sie erzeugen keine
eigenständigen Deployments, Datenmigrationen oder dauerhaften externen Zustände und
rechtfertigen daher keine zusätzlichen Pläne.

Plan 05D bleibt separat. Erst dort werden nach realer Default-on-Veröffentlichung,
vereinbartem Soak, geprüftem Artefakt-Rollback und expliziter Phase-D-Freigabe der
Legacy-Pfad und das Build-Flag gelöscht. Ein grünes `TASK-123` autorisiert diese
Löschung nicht.

**Es ist kein Rückbau erforderlich.** Der weiterhin aktive Legacy-Pfad und das
default-off Build-Flag sind bis zum Phase-D-Gate die beabsichtigte
Sicherheitsgrenze. `TASK-123` ergänzt Parität und Härtung, ohne Plan-08-Semantik,
Containment oder Registry zurückzunehmen. Scheitert ein Gate, wird es blockiert
übergeben; es wird nicht durch Rückbau oder vorzeitige Legacy-Löschung umgangen.

## Warum genau diese Plangrenze gilt

| Kriterien | Tatsächliche Schnittstelle | Größe | Entscheidung |
|---|---|---:|---|
| 1 + 2 | bestehende HTTP-Adapter und der committed `SpatialQueryRef` zwischen Almanac-Router und Inspector | mittel | ein gemeinsamer Paritäts-Work-Order |
| 3 + 4 + 5 | React-Presenter und vorhandener Koordinatenformatter im selben Frontend-Prozess | klein | ein gemeinsamer UI-Work-Order |
| 7 | interner Cesium-Asset-/Primitive-Adapter; keine API- oder Katalogänderung | mittel | ein lokaler Cesium-Work-Order |
| 8 | temporärer Legacy-RBush-Index; keine neue Containment-Quelle | klein–mittel | ein lokaler Legacy-Work-Order |
| Phase D | Release-Artefakte, Zielsystem, Soak, Rollback und irreversible Code-Löschung | extern | bleibt ausschließlich Plan 05D |

Kriterium 1 überschreitet zwar die Backend-/Frontend-Grenze, aber nicht die
Plan-Grenze: beide Seiten besitzen bereits produktive und hermetisch testbare
Adapter. Signals, Briefing und Facts müssen denselben committed Scope-Token nutzen;
sie sind keine unabhängig ausrollbaren Features.

## Pflichtlektüre

Vor Änderungen vollständig lesen:

1. `AGENTS.md`
2. `CLAUDE.md`
3. dieses Handoff
4. `TASKS.md`, ausschließlich den Block `TASK-123` als Akzeptanz-Source-of-Truth
5. [Implementation-Planindex](plans/2026-08-01-spatial-scope-implementation.md)
6. [Plan 03](plans/2026-08-01-spatial-scope/03-cesium-country-migration.md)
7. [Plan 05D](plans/2026-08-01-spatial-scope/05d-phase-d-legacy-cleanup.md)
8. [Spec 03 — Frontend Core/Navigation](specs/2026-07-31-spatial-scope-drilldown/03-frontend-core-and-navigation.md)
9. [Spec 06 — Cesium-/Layer-Semantik](specs/2026-07-31-spatial-scope-drilldown/06-cesium-and-layer-semantics.md)
10. [Spec 11 — UX und 3D](specs/2026-07-31-spatial-scope-drilldown/11-ux-and-3d-metrics.md)
11. [Spec 13 — TDD-Slices](specs/2026-07-31-spatial-scope-drilldown/13-implementation-and-tdd-slices.md)
12. [Spec 14 §§26–29](specs/2026-07-31-spatial-scope-drilldown/14-rollout-and-acceptance.md)
13. [Plan-03 Flag-on-Canary](../reports/2026-08-06-spatial-plan03-flag-on-canary.md)
14. [Plan-05 Canary](../reports/2026-08-07-spatial-plan05-admin1-prefetch-canary.md)
15. [Plan-08 Start Record](../reports/2026-08-10-spatial-plan08-start-record.md)
16. [Plan-08 Verifikation](../reports/2026-08-10-spatial-plan08-verification.md)
17. [Plan-08 Review-Remediation](../reports/2026-08-10-spatial-plan08-review-remediation.md)

Dann den Zustand neu prüfen:

```bash
git status --short --branch
git log -12 --oneline --decorate
git fetch origin feat/spatial-plan03
git rev-list --left-right --count origin/feat/spatial-plan03...HEAD
```

Folgende fremde Worktree-Einträge waren beim Handoff sichtbar und dürfen weder
geändert noch gestaged, formatiert, zurückgesetzt oder committed werden:

- `docs/CONTAINER-STATUS.md`
- `scripts/spark/odin-spark-vllm.sh`
- `docs/superpowers/plans/2026-08-10-task-104-phase2-qdrant-bm25-hybrid.md`

## Mandatory Start Record — vor dem ersten RED

Zuerst
`docs/reports/2026-08-10-spatial-task123-start-record.md` anlegen und separat
committen. Der Record muss enthalten:

1. exaktes Start-HEAD, Remote-Divergenz und fremde Worktree-Einträge;
2. wertgenauen Status aller neun Kriterien: `pass`, `code required`,
   `product decision required` oder `external evidence required`;
3. Kriterien 6 und 9 mit aktuellen Produktionsimporten und Consumer-Tests als
   `pass`, nicht lediglich mit historischen Reports;
4. eine beobachtbare Paritätsmatrix des Legacy- und Flag-on-Inspectors;
5. die gewählte kanonische Route für Facts, Signals, Briefing-Generierung und –
   falls als freigegebene Funktion beibehalten – Briefing-Save;
6. die ausdrückliche Feststellung, dass ein authentisierter server-owned Run
   Receipt nicht Teil von `TASK-123` ist;
7. die Stop-Entscheidung für jede Funktion, die eine neue Produktentscheidung oder
   eine externe Abhängigkeit benötigen würde.

Ein isolierter Helper-Test ist keine ausreichende Pass-Evidenz. Der Record muss den
jeweiligen Produktionsconsumer benennen.

**Commit:** `docs(spatial): record TASK-123 readiness gates`

## Inventar der offenen Gates

### Kriterien 1 + 2 — Inspector-Identität und Parität

Aktueller Befund:

- `SpatialCountryHeader` besitzt bereits einen committed `SpatialQueryRef` und
  verwirft ein Query, dessen `scopeKey` nicht zur Selection passt.
- `useSpatialCountryAlmanac` lädt Facts über
  `scope_key + catalog_revision` und besitzt Abort-/Generation-Gates.
- `SpatialCountryAlmanacPanel` rendert zurzeit nur Facts.
- Der Legacy-Panel rendert zusätzlich Signals, Munin-Briefing, Save/Open und die
  Capability-Liste.
- Backend-Facts nutzen `GET /api/almanac/country` mit der exakten Revision.
- Legacy-Signals und -Briefing nutzen weiterhin
  `/api/almanac/countries/{country_id}/...`.
- `_country_spatial_context()` löst diese Legacy-ID gegen den aktiven Katalog auf;
  das ist kein Beweis für die vom Browser committed Revision.

Tragende Dateien:

- `services/backend/app/routers/almanac.py`
- `services/backend/tests/test_spatial_almanac_router.py`
- `services/backend/tests/test_briefing_endpoint.py`
- `services/frontend/src/services/api.ts`
- `services/frontend/src/hooks/useSpatialCountryAlmanac.ts`
- `services/frontend/src/hooks/useCountryBriefing.ts`
- `services/frontend/src/components/globe/spotlight/CountryHeader.tsx`
- `services/frontend/src/components/globe/spotlight/CountryAlmanacPanel.tsx`
- `services/frontend/src/spatial/WorldviewCountryPath.tsx`
- `services/frontend/src/spatial/__tests__/worldviewMigration.test.tsx`

### Kriterien 3 + 4 + 5 — UI-Semantik

Aktueller Befund:

- `SpatialScopeBreadcrumb` zeigt während Navigation den rohen Wert
  `scope.pending` als sichtbares `Opening ...` und mountet Statusregionen nur bei
  Bedarf.
- Der Cartography-Trigger in `LayersPanel` ist ein Link; sein über
  `aria-controls` referenzierter Container existiert im eingeklappten Zustand
  nicht.
- `formatCoords()` in `src/lib/coords.ts` rendert N/S/E/W bereits korrekt und ist
  getestet.
- Legacy- und Spatial-Country-Header umgehen diesen Formatter und hängen auch bei
  negativen Werten hart `N` und `E` an.

Tragende Dateien:

- `services/frontend/src/spatial/SpatialScopeBreadcrumb.tsx`
- `services/frontend/src/spatial/__tests__/worldviewMigration.test.tsx`
- `services/frontend/src/components/worldview/LayersPanel.tsx`
- zugehörige `LayersPanel`-Tests
- `services/frontend/src/lib/coords.ts`
- `services/frontend/src/lib/__tests__/coords.test.ts`
- `services/frontend/src/components/globe/spotlight/CountryHeader.tsx`

### Kriterium 7 — Palette und getrenntes LOD-Eigentum

Aktueller Befund:

- `buildScopePrimitives.ts` enthält drei harte Farbstrings statt eines zentralen,
  typisierten Hlíðskjalf-Cesium-Palettenmoduls.
- Der 100-Swap-Test belegt bereits stabile Pick-Primitive-Identität und einen
  stabilen Container.
- `swapCameraLod()` wählt das aktive Outline-LOD nach Kamera, übergibt für
  Child-Geometrie aber weiterhin `childrenLods[preferredLod]`.
- Dadurch ist die Pick-Surface korrekt gepinnt, die Child-Outlines folgen dem
  Kamera-LOD jedoch nicht. Render-Child und Pick-Child besitzen derzeit noch
  dieselbe Asset-Rolle.

Tragende Dateien:

- `services/frontend/src/spatial/cesium/CesiumSpatialScopeAdapter.ts`
- `services/frontend/src/spatial/cesium/buildScopePrimitives.ts`
- `services/frontend/src/spatial/__tests__/cesiumAdapter.test.ts`
- `services/frontend/src/spatial/__tests__/geometry.test.ts`
- `services/frontend/src/theme/hlidskjalf.css`

### Kriterium 8 — Legacy-Diagnostik und Dateline-Pruning

Aktueller Befund:

- `prepareLegacyGeometry()` unwrappt Dateline-Ringe korrekt für Containment.
- Bei Dateline-Überquerung erhält RBush trotzdem eine globale BBox
  `[-180, 180]`.
- `buildCountryIndex()` verwirft ungültige Geometrie still.
- Bestehende Tests prüfen beidseitige Dateline-Treffer und Fail-closed, aber weder
  minimale Index-Spans noch eine begrenzte strukturierte Diagnose.

Tragende Dateien:

- `services/frontend/src/components/globe/hooks/useCountryHitTest.ts`
- `services/frontend/src/components/globe/hooks/__tests__/useCountryHitTest.test.ts`
- `services/frontend/src/spatial/geometry.ts` als einzige gemeinsame
  Produktionsquelle, wo ihre bestehenden Primitive passen

## Work Order 1 — kanonische Inspector-Parität (Kriterien 1 + 2)

### RED

1. Backend-Contracttests für Signals und Briefing mit exaktem
   `scope_key + catalog_revision` schreiben.
2. Falsche oder stale Revision, Nicht-Country-Scope und fehlender Katalog müssen
   über die bestehenden Spatial-Problems fail-closed enden; kein Retry gegen die
   aktive Revision und kein Country-ID-Fallback.
3. Frontendtests beweisen, dass Selection A nach Wechsel zu B weder verspätete
   Signals noch Briefing-Chunks oder Save-Zustand rendern kann.
4. Eine Flag-on-Paritätsmatrix auf der produktiven Worldview-/Inspector-Komposition
   inventarisiert Facts/Tabs, Titel, Capital, Signals, Briefing-Generierung,
   Briefing-Ergebnis, Save/Open und Capability-Anzeige. Jeder Unterschied erhält
   entweder einen Consumer oder eine versionierte Produktentscheidung.

### GREEN

1. Im Almanac-Router genau einen internen Resolver für den exakten committed
   Country-Scope verwenden. Facts, neue kanonische Signals-/Briefing-Routen und –
   falls beibehalten – Save konsumieren dieses Ergebnis.
2. Die Legacy-ID-Routen unverändert für den noch vorhandenen Legacy-Pfad lassen;
   Spatial-Routen dürfen nicht über `_country_spatial_context()` auf die jeweils
   aktive Revision ausweichen.
3. Frontend-API und Hooks nehmen denselben `SpatialQueryRef`; Displayname,
   Almanac-ID, ISO3 und M49 bleiben ausschließlich Präsentations-/Adapterdaten.
4. Der Spatial-Panel erhält die laut Paritätsmatrix freigegebenen Consumer. Abort,
   Generation und Selection-Key werden vor jedem State-Commit geprüft.
5. Ein beibehaltenes Save speichert unter dem kanonisch aufgelösten Scope, darf aber
   weiterhin keine browsergelieferte `SpatialRunApplicationV1` als vertrauenswürdig
   persistieren.

### REFACTOR / VERIFY

- Keine zweite Scope-Auflösung im Frontend und kein neuer generischer API-Layer.
- Bestehende Legacy-Tests bleiben unverändert tragend, bis Plan 05D sie löscht.
- Kein Test darf durch Entfernen oder Abschwächen bestehender Assertions grün
  gemacht werden.
- Fokussierte Backend-, Hook-, Panel- und Worldview-Tests ausführen; danach beide
  vollständigen Service-Gates.

**Commit:** `feat(worldview): close spatial inspector parity`

## Work Order 2 — Accessibility und Koordinaten (Kriterien 3 + 4 + 5)

### RED

1. Breadcrumb-Test: sichtbarer Pending-Text enthält einen aufgelösten Kurzlabel
   oder neutralen Status, niemals den rohen Scope-Key.
2. Die höfliche Live-Region existiert bereits im Idle-Zustand; Navigation,
   Unavailable und Rückkehr zu Idle ändern ihren Text ohne Remount.
3. Keyboard- und Focus-Test belegen native Buttons und stabilen Fokus nach Commit.
4. Cartography-Test belegt einen Button, korrektes `aria-expanded` und einen bei
   beiden Zuständen vorhandenen `aria-controls`-Zielcontainer.
5. Header-Fixtures belegen Nord/Ost und Süd/West für Legacy und Spatial.

### GREEN

- Breadcrumb-Statussprache vereinheitlichen und genau eine stabil gemountete
  Live-Region verwenden.
- Disclosure als `button type="button"` implementieren; Detailscontainer stabil
  mounten und im geschlossenen Zustand semantisch verbergen.
- Beide Country-Header an `formatCoords()` mit gemeinsamer Präzision anschließen.
  Keine neue zweite Formatterfunktion anlegen.

### REFACTOR / VERIFY

- Falls `InspectorPanel` ohne Scope-Ausweitung denselben Formatter konsumieren kann,
  seine lokale Duplikation entfernen; andernfalls als explizites Follow-up notieren.
- Fokussierte Breadcrumb-, Layers-, Header- und Formattertests, danach vollständige
  Frontend-Gates.

**Commit:** `fix(worldview): close spatial accessibility parity`

## Work Order 3 — Hlíðskjalf-Palette und LOD-Eigentum (Kriterium 7)

### RED

1. Primitive-Builder-Test fordert zentrale typisierte Cesium-Farbtoken statt harter
   Hexwerte im Builder.
2. Adaptertest protokolliert für Overview/Regional/Local getrennt das aktive
   Render-Asset, das Child-Render-Asset und das bevorzugte Pick-Asset.
3. Child-Outlines müssen dem Kamera-LOD samt deterministischem Fallback folgen;
   ausschließlich die Pick-Surface bleibt auf `childrenLods[preferredLod]`.
4. Der bestehende 100-Swap-Test wird um Asset-Leases, gebundene Primitive-High-Water,
   Listenerzahl und unveränderte Pick-Objektidentität ergänzt.

### GREEN

- Ein kleines lokales Palettenmodul an der Cesium-Grenze anlegen und die drei
  Farbrollen dort typisieren.
- Render-Child- und Pick-Child-Deskriptoren als getrennte Rollen behandeln.
- Bei identischer Asset-ID Leases deduplizieren; bei Kamerawechsel ausschließlich
  Render-Primitives austauschen.
- Einen Container und dieselbe Pick-Primitive behalten. Containment und semantische
  State-Revision dürfen kein Kamera-LOD als Eingabe erhalten.

### REFACTOR / VERIFY

- Keine allgemeinen Theme-Abstraktionen und keine Katalogschemaänderung.
- Adapter-, Geometry- und Primitive-Tests sowie vollständige Frontend-Gates und
  Produktionsbuild ausführen.

**Commit:** `fix(worldview): align spatial palette and render lod`

## Work Order 4 — begrenzte Legacy-Diagnostik (Kriterium 8)

### RED

1. Ungültige Geometrie erzeugt genau eine strukturierte, payload-arme Diagnose pro
   verworfenem Feature innerhalb des festgelegten Limits; Überschreitungen werden
   gezählt oder zusammengefasst.
2. Eine Dateline-Geometrie erzeugt minimale westliche/östliche RBush-Spans statt
   eines globalen Eintrags.
3. Treffer bei `179.x` und `-179.x` bleiben grün; eine Abfrage bei `0` wird bereits
   durch RBush geprunt und ruft Containment für dieses Feature nicht auf.
4. MultiPolygon-, Hole-, Boundary- und Invalid-Click-Verhalten bleibt unverändert.

### GREEN

- Für Dateline-Features höchstens die erforderlichen geteilten Longitude-Spans mit
  demselben Feature-Index und derselben vorbereiteten Geometrie eintragen.
- Die bestehende Ring-/Containment-Semantik wiederverwenden; keine dritte
  Polygonimplementierung hinzufügen.
- Eine kleine echte Diagnostic-Schnittstelle mit Produktions- und Testconsumer
  verwenden. Keine Rohkoordinaten oder vollständigen Geometrien loggen.

### REFACTOR / VERIFY

- Indexdiagnostik bleibt ausschließlich beim temporären Legacy-Pfad und wandert
  nicht in den Spatial-Catalog.
- Fokussierte Legacy-Hit-Test- und Geometry-Suite, dann vollständige Frontend-Gates.

**Commit:** `fix(worldview): harden legacy spatial diagnostics`

## Abschlussrecord und Freigabegrenze

Nach allen vier Work Orders
`docs/reports/2026-08-10-spatial-task123-verification.md` erstellen. Der Record muss:

1. alle neun Kriterien mit Code-, Test- und Produktionsconsumer-Evidenz abhaken;
2. Kriterien 6 und 9 als unveränderte Regression-Gates erneut belegen;
3. jede Produktentscheidung aus der Paritätsmatrix zitieren;
4. die Grenzen der Tests offen nennen;
5. `TASK-123` in `TASKS.md` erst jetzt auf abgeschlossen setzen;
6. ausdrücklich festhalten, dass Plan 05D weiterhin durch externe
   Release-/Soak-/Rollback-/Freigabeevidenz blockiert ist.

**Commit:** `docs(spatial): close TASK-123 readiness gates`

## Stop-Regeln

Sofort stoppen und einen ehrlichen Blocker-Record schreiben, wenn:

- eine Inspector-Funktion nur über Displayname, ISO3, M49 oder Almanac-ID als
  Identität migrierbar wäre;
- ein Spatial-Request bei Scope-/Revisionsfehler auf World, die aktive Revision oder
  eine Legacy-ID zurückfallen müsste;
- Briefing-Parität einen authentisierten server-owned Run Receipt voraussetzt;
- die LOD-Korrektur Pick-Identität, einen Container oder gebundene Leases nicht
  halten kann;
- Dateline-Pruning nur durch eine neue unabhängige Containment-Implementierung
  erreichbar wäre;
- eine Produktfunktion still entfernt statt explizit entschieden werden soll;
- fremde Worktree-Änderungen berührt werden müssten.

Ein Stop in einem Work Order rechtfertigt nicht die Ausführung der übrigen
Legacy-Löschung und öffnet Plan 05D nicht.

## Ausdrückliche Nicht-Ziele

Nicht in `TASK-123` ziehen:

- authentisierter server-owned Briefing-Run-Receipt;
- Graph-Allowlist für weitere scoped Intents;
- FE-Namensbereinigung von `SpatialApplicationV1` /
  `SpatialRunApplicationV1`;
- analystensichtbares Rendering von `SpatialRunApplicationV1`;
- Data-Ingestion-Skip-Bereinigung;
- Plan-08-Work-Order 2, Admin-2 oder 3D;
- Default-on-Deployment, Soak oder Artifact-Rollback;
- Löschung von `VITE_SPATIAL_SCOPE_ENABLED`, `CountryTarget`,
  `useCountryHitTest`, `_topoIndex` oder Legacy-Renderer;
- PR, Merge, Deployment, Katalog-Publish oder Datenbank-Write.

## Verifikation

Kommandos aus den Serviceverzeichnissen ausführen:

```bash
cd services/frontend && npm run lint && npm run type-check && npm test && npm run build
cd services/backend && uv run pytest && uv run ruff check app/ && uv run mypy app/
cd services/intelligence && uv run pytest
cd services/data-ingestion && uv run pytest
```

Backend und Frontend sind für die Codeänderungen tragend. Intelligence und Data
Ingestion sind Whole-program-Regression-Gates beim Abschlussrecord; der bekannte
vorbestehende Data-Ingestion-Skip wird nicht in diesem Task bereinigt.

Vor jedem Commit:

```bash
git diff --check
git diff --cached --check
git diff --cached --name-status
```

Jeder Work Order folgt RED → minimal GREEN → REFACTOR → vollständiger lokaler
VERIFY. Fremde Dateien bleiben aus jedem Staging-Set. Kein Push, PR oder Merge ohne
neuen ausdrücklichen Nutzerauftrag.
