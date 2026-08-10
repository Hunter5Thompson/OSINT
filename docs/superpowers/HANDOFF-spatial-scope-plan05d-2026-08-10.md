# HANDOFF — Spatial Scope Plan 08 abgeschlossen → TASK-123 / Plan 05D Readiness

**Datum:** 2026-08-10

**Nächster Chat:** Zuerst `TASK-123` vollständig schließen und das Phase-D-Gate
belegen; erst danach Plan 05D strikt testgetrieben ausführen

**Branch:** `feat/spatial-plan03`

**Repo:** `/home/deadpool-ultra/ODIN/OSINT`

**Plan-08-Abschluss-HEAD vor diesem Handoff:** `9203b4f`

**Remote-Basis nach Fetch vor diesem Handoff:**
`origin/feat/spatial-plan03` bei `2efd953`

**Divergenz vor diesem Handoff-Commit:** ahead 5, behind 0

**Status:** Alle regulären Pläne 00A bis 08 sind innerhalb ihrer ausdrücklich
akzeptierten Grenzen implementiert und verifiziert. Genau ein kanonischer Plan
bleibt offen: der Sonderplan 05D. Er ist durch sieben Kriterien aus `TASK-123` sowie
fehlende Default-on-/Soak-/Rollback-/Release-Evidenz blockiert. Dieses Handoff
autorisiert keine Legacy-Löschung.

## TL;DR — wo die nächste Session beginnt

Es gibt keinen Plan 09. Der nächste Arbeitsblock ist das verpflichtende
Readiness-Paket vor
[Plan 05D — Phase-D Legacy Cleanup](plans/2026-08-01-spatial-scope/05d-phase-d-legacy-cleanup.md):

Die alleinige Detailquelle für die Umsetzung dieses Readiness-Pakets ist das
[dedizierte TASK-123-Handoff](HANDOFF-spatial-scope-task123-2026-08-10.md). Es
schneidet den Restumfang als einen Implementierungsplan mit vier Code-Work-Orders;
die weiter unten stehende Reihenfolge ist nur die historische Kurzfassung. Bei
Abweichungen gilt das dedizierte Handoff.

1. den aktuellen Code gegen alle neun Kriterien von `TASK-123` neu inventarisieren;
2. die bereits belegten Kriterien 6 und 9 unverändert erhalten;
3. Kriterien 1–5, 7 und 8 testgetrieben schließen oder mit einer expliziten,
   versionierten Produktentscheidung disponieren;
4. erst danach Default-on-Release, vereinbarten Soak, Artefakt-Rollback und die
   Phase-D-Freigabe belegen;
5. nur bei vollständig grünem Readiness-Record Plan 05D öffnen.

Fehlt externe Release-/Soak-/Rollback-Evidenz, endet die nächste Session mit einem
ehrlichen blockierten Readiness-Record. Sie darf nicht ersatzweise
`VITE_SPATIAL_SCOPE_ENABLED`, `CountryTarget`, `useCountryHitTest`, `_topoIndex` oder
den Legacy-Renderer löschen.

## Anzahl verbleibender Pläne

Der Implementierungsindex enthält 13 ausführbare Plan-Dokumente:
`00A`, `00B`, `01`, `02`, `03`, `04`, `05`, `05D`, `06A`, `06B`, `07A`, `07B` und
`08`. Davon sind zwölf innerhalb ihrer akzeptierten Grenzen abgeschlossen.

**Offen ist genau ein Plan: `05D`.**

Davon getrennt offen bleiben:

- das vorgelagerte Task-/Readiness-Paket `TASK-123`;
- die operativen Phase-C-/Phase-D-Nachweise;
- bewusst nicht aktivierte Plan-08-Zweige und eigenständige Produkt-Follow-ups.

Diese Punkte erhöhen nicht die Zahl der kanonischen Pläne, können aber Plan 05D
weiterhin blockieren.

## Pflichtstart in der nächsten Session

Vor jeder Änderung vollständig lesen:

1. `AGENTS.md`
2. `CLAUDE.md`
3. dieses Handoff
4. [Implementation-Planindex](plans/2026-08-01-spatial-scope-implementation.md)
5. [Plan 03](plans/2026-08-01-spatial-scope/03-cesium-country-migration.md)
6. [Plan 05D](plans/2026-08-01-spatial-scope/05d-phase-d-legacy-cleanup.md)
7. [Spec 03 — Frontend Core/Navigation](specs/2026-07-31-spatial-scope-drilldown/03-frontend-core-and-navigation.md)
8. [Spec 06 — Cesium-/Layer-Semantik](specs/2026-07-31-spatial-scope-drilldown/06-cesium-and-layer-semantics.md)
9. [Spec 11 — UX und 3D](specs/2026-07-31-spatial-scope-drilldown/11-ux-and-3d-metrics.md)
10. [Spec 13 — TDD-Slices](specs/2026-07-31-spatial-scope-drilldown/13-implementation-and-tdd-slices.md)
11. [Spec 14 §§26–29 — Rollout, Stop-Regeln und Acceptance](specs/2026-07-31-spatial-scope-drilldown/14-rollout-and-acceptance.md)
12. [Plan-03-Flag-on-Canary](../reports/2026-08-06-spatial-plan03-flag-on-canary.md)
13. [Plan-05-Admin-1-/Prefetch-Canary](../reports/2026-08-07-spatial-plan05-admin1-prefetch-canary.md)
14. [Plan-08 Mandatory Start Record](../reports/2026-08-10-spatial-plan08-start-record.md)
15. [Plan-08 Abschlussverifikation](../reports/2026-08-10-spatial-plan08-verification.md)
16. [Plan-08 Review-Remediation](../reports/2026-08-10-spatial-plan08-review-remediation.md)
17. `TASKS.md`, ausschließlich `TASK-123` als Source of Truth für den
    Legacy-Cleanup-Blocker

Dann den Zustand neu prüfen:

```bash
git status --short --branch
git log -12 --oneline --decorate
git fetch origin feat/spatial-plan03
git rev-list --left-right --count origin/feat/spatial-plan03...HEAD
```

Aktuell sind drei fremde Worktree-Einträge sichtbar. Nicht ändern, stagen,
zurücksetzen, formatieren oder in einen Commit aufnehmen:

- `docs/CONTAINER-STATUS.md`
- `scripts/spark/odin-spark-vllm.sh`
- `docs/superpowers/plans/2026-08-10-task-104-phase2-qdrant-bm25-hybrid.md`

Der für dieses Handoff autorisierte Push umfasst ausschließlich den bestehenden
Branch samt Plan-08- und Handoff-Commits. Er autorisiert keinen PR, Merge,
Deployment, Catalog-Publish, Neo4j-/Qdrant-Write oder Re-Enrichment-Apply.

## Abgenommener Plan-08-Stand

### Commits

```text
c1fe14e docs(spatial): record Plan 08 capability gate
4d4010a feat(worldview): scope registered point layers
65de156 docs(spatial): verify Plan 08 bounded completion
66e4cbf refactor(worldview): enforce spatial capability invariants
9203b4f docs(spatial): record Plan 08 review remediation
```

### Aktivierte Arbeit

- Die Registry umfasst exakt alle 16 `LayerVisibility`-Keys und treibt sowohl
  Runtime-Render-Gates als auch Analysten-Badges.
- Nur `earthquakes` wurde als neuer strikter `occurs-in`-Punktlayer aktiviert.
- Der feste katalogrevisionsgebundene Containment-Index invalidiert vor dem neuen
  semantischen Publish; `building` und `unavailable` besitzen keine alte
  `contains`-Funktion.
- Der Earthquake-Adapter filtert vor Viewport-Culling und Render-Cap, mutiert keine
  Semantikdaten und zählt `inside`, `outside`, `boundary-uncertain` und ungültige
  Koordinaten getrennt.
- `relation`, `stalePolicy` und `unsupportedBehavior` sind produktive Registry-
  Eingaben. Wertgenaue Invarianten verhindern widersprüchliche Zeilen; zusätzliche
  Runtime-Checks fallen geschlossen aus.
- Work Order 2 wurde mangels autoritativer Track-/Polygon-/Raster-Seams gestoppt.
- Admin-2 bleibt bei null Katalog-Scopes und fehlender Auswahl-/Coverage-Evidenz
  blockiert.
- 3D bleibt ohne akzeptierten Metric Record deferred.

### Katalogeinordnung

`spatial-v1-fe9828dcda05` ist der aktuelle veröffentlichte Katalog:

```text
verify/audit: pass
204 scopes = 1 world + 176 country + 27 admin1 + 0 admin2
41 assets, 4,509,895 bytes
38 containment descriptors
largest asset: 820,372 wire bytes / 2,654,336 estimated heap bytes
```

`spatial-v1-e76a16bff799` ist korrekt als historischer Plan-05-Canary mit 68
Render-LOD-Assets und denselben 38/38 Containment-Gates dokumentiert. Die
68→41-Differenz betrifft nicht die Containment-Fläche. Die 0-m-Fehlermessung gehört
zum historischen Canary; der aktuelle Runtime-Adapter liest `maxErrorMeters` aus
dem aktiven Deskriptor und schließt das Fehlerband konservativ aus.

### Verifikation am Plan-08-Abschluss-HEAD

```text
Frontend          106 files, 595/595 tests
ESLint            clean
TypeScript        clean
production build  successful (known chunk-size warning only)
Backend           574/574 tests; Ruff and strict MyPy clean
Intelligence      449/449 tests
Data Ingestion    1368 passed, 1 pre-existing skip, 17 deselected; Ruff clean
Catalog           verify and audit pass
Repository        git diff --check clean
```

Der 30k-Point-Benchmark besitzt echtes Drei-Klassen-Accounting und blieb innerhalb
seiner Zeit-/Heap-Budgets. Er ist ausdrücklich eine Node/Vitest-Filter-/Heap-Messung,
keine GPU-/Production-Browser-Frame-Messung.

## TASK-123 — historischer Kurzstand

Kriterien 6 und 9 sind durch Plan 08 erfüllt. Sie bleiben Regression-Gates, werden
aber nicht neu implementiert:

- gemeinsamer `spatial/geometry.ts`-Containment-Seam ist produktiv;
- `LAYER_SPATIAL_CAPABILITIES` besitzt Runtime- und Badge-Consumer.

Sieben Kriterien bleiben offen und bilden den nächsten testgetriebenen Arbeitsblock.

### 1. Kanonische Inspector-Datenpfade

Signal-Liste und Munin-Briefing müssen aus dem committed
`scope_key + catalog_revision` über kanonisch aufgelöste Adapter kommen. Almanac,
Displayname und Legacy-Country-Felder sind keine Identitätsquelle. Ein späterer
Briefing-Save darf keine `SpatialRunApplicationV1` aus Browserdaten rekonstruieren;
echte persistierte Run-Attribution benötigt weiterhin einen authentisierten,
server-owned Receipt.

### 2. Produktparität vor Löschung

Ein Flag-on/Legacy-Paritätstest inventarisiert jede freigegebene Inspector-Funktion.
Jede fehlende Funktion wird entweder migriert oder durch eine explizite
Produktentscheidung verworfen. Schweigende Funktionsverluste blockieren 05D.

### 3. Breadcrumb-Sprache und Accessibility

Kein roher Scope-Key als sichtbares Opening-Label. Statussprache bleibt konsistent;
die Live-Region ist vorab gemountet und Screenreader-, Tastatur- und Focus-Verhalten
werden getestet.

### 4. Cartography-Disclosure

Der Disclosure-Trigger verwendet Button-Semantik. `aria-expanded` und
`aria-controls` referenzieren einen stabil vorhandenen Container.

### 5. Gemeinsame Koordinatenformatierung

Negative Breite/Länge erscheinen als S/W und nicht als negative N/E-Werte. Legacy-
und Spatial-Header konsumieren denselben Formatter.

### 7. Palette, Render-LOD und Pick-Invarianz

Scope-Primitive-Farben liegen in einer zentralen Cesium-kompatiblen
Hlíðskjalf-Palette. Child-Outlines folgen dem Kamera-LOD; ausschließlich die
Pick-Surface bleibt auf `childrenLods[preferredLod]` gepinnt. Ein 100-Swap-Test
belegt stabile Pick-Identität und gebundene Leases.

### 8. Legacy-Diagnostik bis zur tatsächlichen Löschung

Solange der Legacy-Pfad produktiv bleibt, werden ungültige Koordinaten beim Indexbau
einmalig und begrenzt diagnostiziert. Dateline-Features verwenden minimale geteilte
Longitude-Spans im RBush statt `[-180, 180]`; Tests belegen beidseitige Treffer und
Pruning außerhalb der realen Spans.

## Historische Kurzfolge vor 05D

### Schritt 0 — Mandatory Readiness Record

Für jedes der neun `TASK-123`-Kriterien exakt einen Status erfassen:
`pass`, `code required`, `product decision required` oder `external evidence
required`. Bestehende Tests zählen nur, wenn sie die aktuelle Runtime-Verkabelung
und nicht lediglich einen isolierten Helper prüfen.

### Work Order 1 — Parität und kanonische Inspector-Adapter

1. RED: Flag-on/Legacy-Paritätsmatrix sowie Scope-/Revision-/Stale-Response-Tests.
2. GREEN: fehlende Signal-/Briefing-Consumer über bestehende kanonische Adapter
   verdrahten; keine zweite Scope-Auflösung.
3. REFACTOR: Almanac bleibt Präsentationsdatenquelle, niemals Identität.
4. VERIFY: fokussierte Frontend-/Backend-Tests und statische Contract-Checks.
5. COMMIT: `feat(worldview): close spatial inspector parity`

### Work Order 2 — Breadcrumb, Disclosure und Koordinaten

1. RED: Opening-Label, vorab gemountete Live-Region, Focus/Keyboard,
   `aria-expanded`/`aria-controls` sowie N/S/E/W-Fixtures.
2. GREEN: kleinste gemeinsame Presenter-/Formatter-Änderung.
3. REFACTOR: keine doppelte Legacy-/Spatial-Formatlogik.
4. VERIFY: fokussierte A11y-/Header-/Layers-Tests plus Frontend-Gates.
5. COMMIT: `fix(worldview): close spatial accessibility parity`

### Work Order 3 — Palette und LOD-Eigentum

1. RED: zentrale Farbtoken, Outline-LOD-Wechsel und 100-Swap-Pick-/Lease-Invarianz.
2. GREEN: Render-Outlines kameraabhängig wählen; Pick-Asset unverändert lassen.
3. REFACTOR: Cesium-Werte bleiben an der Cesium-Grenze, UI-Tokens typisiert.
4. VERIFY: Adapter-/Primitive-/Soak-Tests und Produktionsbuild.
5. COMMIT: `fix(worldview): align spatial palette and render lod`

### Work Order 4 — Legacy-Dateline-Diagnostik

1. RED: ungültige Feature-Diagnose genau einmal/gebunden, Dateline-Treffer auf beiden
   Seiten und RBush-Pruning außerhalb minimaler Spans.
2. GREEN: bestehende gemeinsame Geometrieprimitive wiederverwenden; keine dritte
   Containment-Implementierung.
3. REFACTOR: Diagnose ist strukturiert und enthält keine sensitiven Rohpayloads.
4. VERIFY: Legacy-Hit-Test, Geometry- und Full-Frontend-Suite.
5. COMMIT: `fix(worldview): harden legacy spatial diagnostics`

### Work Order 5 — TASK-123- und Phase-D-Entscheid

1. Alle neun Kriterien wertgenau gegen Code, Tests und Produktentscheidungen
   abhaken.
2. `TASK-123` erst dann auf abgeschlossen setzen.
3. Separaten Plan-05D-Readiness-Record mit Release-Artefakt, Default-on-Status,
   Soak-Zeitraum, Metriken, Rollback-Rehearsal und expliziter Phase-D-Freigabe
   erstellen.
4. Fehlt eines dieser externen Gates, 05D als blockiert übergeben.
5. COMMIT: `docs(spatial): gate Plan 05D legacy cleanup`

## Plan 05D — nur nach bestandenem Readiness-Gate

Der bestehende Plan bleibt unverändert maßgeblich:

1. statisch und verhaltensseitig das Delete-Set beweisen;
2. Composition Root dauerhaft auf Spatial stellen;
3. Legacy-Identität, Renderer, `_topoIndex` und Build-Flag entfernen;
4. Produktionsbundle auf Abwesenheit aller Legacy-Symbole prüfen;
5. Forward→Previous→Forward-Artefakt-Rollback im Zielsystem proben;
6. erst danach Spec 14 Phase D und §29 schließen.

Ein grüner Unit-Testlauf allein autorisiert keinen dieser Schritte.

## Nicht in den Readiness-Lauf ziehen

Die folgenden bekannten Produkt-Follow-ups benötigen eigene Produktentscheidungen
und sind nicht automatisch Teil von `TASK-123` oder Plan 05D:

- Graph-Allowlist für zusätzliche scoped Intents;
- sprachliche/typseitige Entflechtung von `SpatialApplicationV1` und
  `SpatialRunApplicationV1` sowie Request-Namensbereinigung;
- analystensichtbares Rendering von `SpatialRunApplicationV1`;
- authentisierter server-owned Briefing-Run-Receipt;
- Aufräumen des vorbestehenden Data-Ingestion-Skips;
- erneute Öffnung der gestoppten/blockierten/deferred Plan-08-Zweige.

Falls Work Order 1 tatsächlich eine dieser Produktentscheidungen benötigt, stoppt
der betroffene Teil und fordert die Entscheidung an; er wird nicht still erweitert.

## Verifikation und Abschlussregeln

Für jeden Code-Work-Order gilt RED → minimal GREEN → Refactor. Kommandos laufen aus
den Service-Verzeichnissen:

```bash
cd services/frontend && npm run lint && npm run type-check && npm test && npm run build
cd services/backend && uv run pytest && uv run ruff check app/ && uv run mypy app/
cd services/intelligence && uv run pytest
cd services/data-ingestion && uv run pytest
```

Vor jedem Commit:

```bash
git diff --check
git diff --cached --check
git diff --cached --name-status
```

Plan 05D verlangt zusätzlich echte Deployment-/Browser-/Rollback-Evidenz aus dem
Zielsystem. Hermetische Tests dürfen diese nicht simulieren oder ersetzen.

## Session-Abschluss

Plan 08 ist merge-fähig und vollständig abgenommen. Der Branch wird auf ausdrückliche
Nutzerfreigabe zusammen mit diesem Handoff gepusht. Es erfolgt kein PR, Merge,
Deployment oder Datenbank-/Katalog-Write. Die nächste Session beginnt beim Mandatory
Readiness Record und behandelt jede fehlende Evidenz als Stop-Gate.
