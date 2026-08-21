# HANDOFF — Spatial Scope nach Plan 05 → Plan 06A

**Datum:** 2026-08-07

**Nächster Chat:** Plan 06A — Neo4j Normalization and Backfill

**Branch:** `feat/spatial-plan03` (auf `origin` gepusht, kein PR, kein Merge)

**Arbeitsverzeichnis:** `/home/deadpool-ultra/ODIN/OSINT`

**Ausgangs-HEAD:** `46131a8` (`fix(spatial): harden Plan 05 invariants`)

**Basis:** `origin/main` bei `7704d8e`

## TL;DR — wo der nächste Chat beginnt

Die Spatial-Scope-Pläne 00A, 00B, 01, 02, 03, 04 und 05 sind implementiert,
reviewt, getestet und mit allen 159 Plan-Checkboxen abgeschlossen. Der komplette
Stand liegt ausschließlich auf `feat/spatial-plan03`; `main` ist unverändert. Plan 05
endete in den Commits `6a929a3` und `46131a8` und ist zusätzlich auf einem echten
Firefox/WebGL2-Pfad geprüft.

Der nächste Chat startet ausschließlich mit
`docs/superpowers/plans/2026-08-01-spatial-scope/06a-neo4j-normalization-and-backfill.md`,
Work Order 1, RED. Plan 06A materialisiert kanonische Spatial-Felder auf
`:Location`; er aktiviert noch keine exakten CHRONIK-Abfragen.

Kein PR und kein Merge nach `main`, bis der gesamte vereinbarte Spatial-Track
implementiert und übergreifend getestet ist und der Nutzer ausdrücklich freigibt.
Zwischenstände und Handoffs dürfen auf den Feature-Branch gepusht werden.

Pro Plan-Task des Gesamttracks beginnt ein neuer Chat. Der abschließende Chat eines
Tasks erstellt deshalb immer das versionierte Handoff für den unmittelbar folgenden
Task.

## Pflichtstart für den nächsten Chat

1. Vollständig lesen:
   - `AGENTS.md`
   - `CLAUDE.md`
   - dieses Handoff
   - `docs/superpowers/plans/2026-08-01-spatial-scope/06a-neo4j-normalization-and-backfill.md`
   - die dort gerouteten Spec-Abschnitte 02 §7.5, 08, 12 §22 und 13 Slice 6
2. Branch und Fremdänderungen prüfen:
   ```bash
   git status --short --branch
   git log -3 --oneline --decorate
   ```
3. Die beiden unten genannten fremden Working-Tree-Dateien nicht stageen, ändern,
   zurücksetzen oder committen.
4. Work Order 1 testgetrieben beginnen: zuerst
   `tests/test_spatial_normalizer.py`, dann die minimale pure Implementierung.
5. Pro Work Order einen eigenen Conventional Commit erstellen und pushen. Vor dem
   nächsten Plan-Chat ein neues, fortgeschriebenes Handoff anlegen; dieses Dokument
   nicht still umdeuten.

## Autoritative Dokumente

- Gesamtplan-Verzeichnis:
  `docs/superpowers/plans/2026-08-01-spatial-scope/`
- Nächster Ausführungsplan:
  `docs/superpowers/plans/2026-08-01-spatial-scope/06a-neo4j-normalization-and-backfill.md`
- Identität und Boundary Policy:
  `docs/superpowers/specs/2026-07-31-spatial-scope-drilldown/02-scope-identity-and-boundary-policy.md`
- Neo4j-Normalisierung:
  `docs/superpowers/specs/2026-07-31-spatial-scope-drilldown/08-neo4j-normalization.md`
- Fehler, Security und Observability:
  `docs/superpowers/specs/2026-07-31-spatial-scope-drilldown/12-errors-security-and-observability.md`
- Implementierungs-Slices:
  `docs/superpowers/specs/2026-07-31-spatial-scope-drilldown/13-implementation-and-tdd-slices.md`
- Rollout und Acceptance:
  `docs/superpowers/specs/2026-07-31-spatial-scope-drilldown/14-rollout-and-acceptance.md`
- Plan-05-Canary:
  `docs/reports/2026-08-07-spatial-plan05-admin1-prefetch-canary.md`
- Plan-03-Canary:
  `docs/reports/2026-08-06-spatial-plan03-flag-on-canary.md`
- Aufgabenregister, besonders das offene `TASK-123`:
  `TASKS.md`

Bei Widersprüchen gelten die aktuellen Plan-/Spec-Dateien und `AGENTS.md`; dieses
Handoff beschreibt den Übergabestand, ersetzt aber keinen Planvertrag.

## Fertiger Stand — Pläne 00A bis 05

| Plan | Status | Checkboxen |
|---|---|---:|
| 00A Catalog Policy and Contracts | abgeschlossen | 20/20 |
| 00B Boundary Builder and Feasibility | abgeschlossen | 25/25 |
| 01 Frontend Core and Navigation | abgeschlossen | 23/23 |
| 02 Backend Catalog and HTTP | abgeschlossen | 22/22 |
| 03 Cesium Country Migration | abgeschlossen | 25/25 |
| 04 CHRONIK BBox Scope | abgeschlossen | 24/24 |
| 05 Admin-1 and Prefetch | abgeschlossen | 20/20 |

Der Branch enthält vor diesem Handoff 49 Commits gegenüber `origin/main`. Wichtige
Landmarks:

- `4e57706` — genehmigtes Spatial-Design und Pläne
- `9ad898a` — Foundation-Pläne 00A–02 geschlossen
- `4439a46` — Plan-03-Lifecycle-Review-Follow-ups
- `bde6dc3` — Plan-04-Review-Follow-ups
- `6a929a3` — Plan-05 Admin-1 und Prefetch als geprüfter Baseline-Commit
- `46131a8` — Descriptor-, High-Water-, Policy-, LOD- und Report-Härtung

## Plan-05-Abschlussnachweis

- Immutable Katalogrevision: `spatial-v1-e76a16bff799`
- 204 Scopes, darunter alle 27 ausgewählten ukrainischen Admin-1-Kinder
- 68 Assets, exakt 5.355.159 Bytes
- Containment 38/38 bestanden, maximaler Fehler 0 m
- Zwei Offline-Builds und veröffentlichter Workspace-Katalog byteidentisch
- Backend: 505 Tests; Ruff und striktes Mypy grün
- Data-Ingestion: 1.265 bestanden, 1 explizit übersprungen, 17 deselected; Ruff grün
- Frontend flag-off und flag-on: jeweils 559/559 Tests in 102 Dateien
- ESLint und TypeScript grün; beide Production-Builds erfolgreich
- Firefox 153.0.3/WebGL2: Cold Visual p95 292 ms, Maximum 641 ms
- Warm Core Commit: 7–20 ms; 100-Transition-Soak ohne monotones Wachstum

Wichtige Interpretation des Canary-Berichts:

- `SpatialCanaryProbe` ist DEV-gated. Die Browserzahlen stammen vom Vite-DEV-Build
  mit React-StrictMode-Verhalten, nicht von einem instrumentierten Production-Bundle.
- Die ursprüngliche Cache-High-Water-Zahl 8 wurde nach Eviction erhoben und beweist
  keinen transienten Peak. Seit `46131a8` wird unmittelbar nach Decode und vor
  Eviction auf Foreground- und Prefetch-Pfaden gemessen. Der Regressionstest sieht
  bei `maxEntries=1` transient 2 Einträge/3.200 Bytes und nach Release wieder
  1 Eintrag/1.472 Bytes. Der Browser-Canary wurde mit diesem korrigierten Zähler nicht
  erneut ausgeführt; der Report behauptet deshalb keinen Browser-Peak.
- Content-adressierte Assets dürfen dieselben Bytes unter unterschiedlichen
  Referenzsemantiken (`role`, `lod`, `maxError`) verwenden. Hart bleiben Asset-ID,
  Media-Type, Byte-/Vertex-/Feature-Counts und das Wire-Budget `maxError <= 50`.
- Eine laufende Hover-Anfrage wird auch nach bereits gestartetem Asset-Request durch
  einen Click auf Foreground-Retry-Rechte angehoben; ein Integrationstest deckt den
  anschließenden 429-Retry ab.
- GLOBE und LOCAL fallen nur noch über die benachbarte REGIONAL-Stufe zurück; kein
  direkter GLOBE→LOCAL- oder LOCAL→OVERVIEW-Sprung.

## Verbleibende Reihenfolge des Gesamttracks

1. **Plan 06A — jetzt:** Pure Normalisierung, aktive Forward Writer, Neo4j-Indizes,
   restartbarer Backfill/Re-Enrichment und Coverage-Handoff.
2. **Plan 06B:** Erst nach 06A-Exit; exakte CHRONIK-Templates, Coverage Accounting
   und serverseitige Aktivierung je Lane/Scope-Kind.
3. **Plan 07A:** Benötigt den 06A-Assignment-Vertrag; Qdrant-Payloads, Indizes,
   Filtercompiler und restartbares Re-Enrichment.
4. **Plan 07B:** Erst nach 06B und 07A; Scope-Token im Backend/LangGraph und
   fail-closed Tool-Enforcement.
5. **Plan 08:** Erst nach dem V1-Start-Gate und einem expliziten Auswahlrecord;
   Layer, ausgewählte Admin-2-Theater und höchstens eine begründete 3D-Metrik sind
   unabhängig aktivierbar. Keine dekorative oder unbelegte Aktivierung.
6. **Gesamt-Gate:** Alle betroffenen Service-Suites, statische Checks, Katalog-,
   Neo4j-, Qdrant-, Browser-/Soak- und Truthfulness-Nachweise zusammenführen. Erst
   danach darf der Nutzer über einen PR beziehungsweise Merge nach `main` entscheiden.

### Plan 05D bleibt separat und gesperrt

Plan 05D ist ausdrücklich kein normaler Folgeslice. Seine harten Voraussetzungen sind
ein abgeschlossener Default-on-Release, ein vereinbarter Soak ohne Rollback-Trigger,
ein getesteter Artifact-Rollback und die explizite Phase-D-Releaseentscheidung. Vor
diesen Nachweisen darf kein Chat den Legacy-Country-Pfad oder
`VITE_SPATIAL_SCOPE_ENABLED` löschen. 05D wird später als eigener Deployment-Cleanup
mit eigenem Handoff/PR behandelt.

## Plan 06A — konkreter Arbeitsvertrag

Plan 06A besitzt vier Work Orders und derzeit 20 offene Checkboxen:

1. **Pure deterministic normalizer**
   - Neue strikte `RawLocationIdentity`-/Ergebnismodelle.
   - Explizite allowlist-basierte Code-System-Adapter.
   - Source-Code-Präzedenz, Konfliktkandidaten, Basis, Präzision sowie getrennte
     Catalog-/Derivation-Revisionsfelder.
   - Freie Namen werden niemals zu Scope-Keys; `(0,0)` ist ein valider Punkt und darf
     nicht durch Truthiness verloren gehen.
2. **Forward writers and atomic transaction**
   - Alle aktiven `:Location`-Produzenten zunächst per `rg` inventarisieren.
   - Mit GDELT raw beginnen; normalisierte Spatial-/Audit-/Conflict-Felder und
     `geo=point(...)` in derselben parametergebundenen Transaktion schreiben.
   - Ununterstützte Lanes explizit reporten, niemals still überspringen.
3. **Index migration and plan smoke**
   - Drei Composite-Range-Indizes plus genau ein bestehender Point-Index,
     ausschließlich `IF NOT EXISTS`.
   - `location_geo` konsolidieren statt duplizieren; `EXPLAIN`-Nachweis je Scope-Kind.
4. **Backfill and recurring re-enrichment**
   - Explizites `--dry-run/--apply`, stabile Cursor/Checkpoints, idempotenter Restart,
     machine-readable Accounting und Revision-aware Carry-forward.
   - Alte Rohfelder bleiben erhalten; nur deterministische Ergebnisse werden
     angewendet.

Plan-06A-Exit verlangt zusätzlich zur Implementierung reale Betriebsnachweise:
Forward Writer vor Apply deployt, Backup/Restore-Point vorhanden, Staging-Dry-run
reviewt, Country-Coverage mindestens 95 %, stale compatible-revision rate höchstens
1 % und Query-Pläne über die vorgesehenen Indizes. Keine Live-/Staging-Schreibaktion,
kein Deployment und kein Backup-Eingriff ohne die dafür nötige Nutzerfreigabe. Falls
diese externe Freigabe im Chat fehlt, Code und hermetische Tests vollständig bauen,
aber das Exit-Gate ehrlich offen lassen.

## Architektur- und Sicherheitsregeln, die nicht verhandelbar sind

- Neo4j-Writes verwenden ausschließlich deterministische Cypher-Templates und
  Parameterbindung. Kein LLM-generiertes Cypher, keine Werteinterpolation.
- Backend bleibt vollständig async; Frontend bleibt TypeScript-strikt ohne `any`.
- Keine zweite Geo-/Crosswalk-Wahrheit erstellen. Plan 06A muss die geprüften
  Catalog-Crosswalk- und Containment-Artefakte wiederverwenden.
- Keine unbekannten Codes oder Konflikte auf World/Country defaulten. Fail closed und
  Konfliktstatus materialisieren.
- Rohcodes, Rohkoordinaten und Provenance bleiben erhalten.
- TDD ist Pflicht: dokumentierter RED-Lauf, minimale GREEN-Implementierung,
  Refactor und fokussierte sowie vollständige Verification.
- `pytest.mark.skip` nur mit TODO-Kommentar und Ticketreferenz.
- Live-Backfill ist eine operator-gated Datenmutation: vor Apply exakte Zielmenge,
  Backup/Restore und Dry-run prüfen.
- Nur einen lokalen LLM-Modus gleichzeitig auf der RTX 5090 betreiben; für Plan 06A
  ist kein LLM zur Spatial-Normalisierung zulässig oder nötig.

## Offener Cross-Slice-Blocker: TASK-123

`TASKS.md` führt `TASK-123: Spatial Plan-03 Review-Follow-ups vor Legacy-Cleanup`
weiterhin als **OFFEN**. Nicht voreilig schließen. Mehrere Kriterien gehören bewusst
in spätere Slices:

- Inspector-Signale/Munin-Briefing und Scope-Truthfulness: Plan 07B
- produktiver Consumer oder Entfernung von `LAYER_SPATIAL_CAPABILITIES`: Plan 08/05D
- produktive Nutzung oder Entfernung von `spatial/geometry.ts`: Plan 08/05D
- vollständige Legacy-/Spatial-Parität, A11y- und Cleanup-Nachweise: vor Plan 05D

Ein Teil der Lifecycle-/LOD-/Legacy-Härtung ist bereits implementiert, aber der Task
ist erst geschlossen, wenn jedes einzelne Akzeptanzkriterium nachweislich erfüllt oder
mit dokumentierter Produktentscheidung anders disponiert ist.

## Working-Tree-Hygiene

Beim Erstellen dieses Handoffs existieren genau zwei vorbestehende, fremde lokale
Änderungen:

- `docs/CONTAINER-STATUS.md`
- `scripts/spark/odin-spark-vllm.sh`

Sie gehören nicht zum Spatial-Track. Nicht stageen, committen, zurücksetzen,
überschreiben oder in Formatierungs-/Bulk-Rewrites einbeziehen. Vor jedem Commit die
Staging-Liste explizit prüfen.

Lockfiles sind grundsätzlich gitignored, außer
`services/data-ingestion/uv.lock`. Service-Kommandos aus dem jeweiligen
Service-Verzeichnis ausführen.

## Baseline-Kommandos

```bash
cd services/data-ingestion
uv sync
uv run pytest
uv run ruff check .

cd ../backend
uv sync
uv run pytest
uv run ruff check app/
uv run mypy app/

cd ../frontend
npm install
npm run lint
npm run type-check
npm test
VITE_SPATIAL_SCOPE_ENABLED=true npm test
npm run build
VITE_SPATIAL_SCOPE_ENABLED=true npm run build
```

Für Plan 06A zunächst die im Plan genannten fokussierten Tests ausführen; fokussierte
Qualitätschecks laufen vor jedem Work-Order-Commit, die vollständigen betroffenen
Service-Gates am Exit.

## Definition of Done für den nächsten Handoff

Vor dem Wechsel von Plan 06A zu Plan 06B muss der nächste Chat:

- alle vier Plan-06A-Work-Orders testgetrieben implementiert haben;
- alle 20 Checkboxen nur bei tatsächlich erfülltem Nachweis schließen;
- die vier vorgesehenen Conventional Commits erstellt und gepusht haben;
- fokussierte und vollständige Data-Ingestion-Gates mit exakten Zahlen dokumentieren;
- Migration-/Query-Plan-, Coverage-, Dry-run- und Backup-Nachweise entweder anhängen
  oder als konkretes externes Gate offen ausweisen;
- `TASKS.md` nur mit belegtem Status aktualisieren;
- ein neues `HANDOFF-spatial-scope-plan06b-<datum>.md` mit Branch-HEAD, Testzahlen,
  offenen Betriebs-Gates und allen Fremdänderungen erstellen, committen und pushen;
- weder PR noch Merge nach `main` auslösen.

## Git- und Merge-Status

- Remote: `git@github.com:Hunter5Thompson/OSINT.git`
- Feature-Branch: `feat/spatial-plan03`
- Remote-Branch: `origin/feat/spatial-plan03`
- Vor diesem Handoff waren lokaler und Remote-HEAD identisch bei `46131a8`.
- Es existiert kein PR aus diesem Chat und kein Merge nach `main`.
- Der Nutzer hat ausdrücklich entschieden: erst den Gesamtplan einbauen und testen,
  dann separat über den Main-Merge entscheiden.
