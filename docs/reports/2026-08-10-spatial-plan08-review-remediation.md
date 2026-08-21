# Spatial Scope Plan 08 — Review-Remediation

**Datum:** 2026-08-10

**Branch:** `feat/spatial-plan03`

**Code-Commit:** `66e4cbf refactor(worldview): enforce spatial capability invariants`

**Status:** Beide Wartbarkeitshinweise geschlossen; kein Korrektheitsdefekt und
keine Capability-Promotion

## Ergebnis

Die Registry bleibt die geschlossene Wahrheit für alle 16 `LayerVisibility`-Keys.
Die drei zuvor nur deklarativ gelesenen Felder sind jetzt Teil der zentralen
Runtime-Ableitung:

- `relation` erscheint in jedem erzeugten Status-Claim;
- `stalePolicy` wählt den Containment-, Response-Token-, Präsentations- oder
  Not-applicable-Pfad;
- `unsupportedBehavior` entscheidet zwischen Verbergen, sichtbarem globalem Kontext
  und sichtbarer Scope-Präsentation.

Widersprüchliche Policy-Kombinationen fallen geschlossen auf `scope unavailable`.
Insbesondere bleibt `behavior: unsupported` außerhalb von `world` verborgen, selbst
wenn jemand `supportedKinds` versehentlich erweitert.

Die doppelte Kodierung von `behavior: unsupported` und `supportedKinds: ["world"]`
bleibt bewusst erhalten: Die erste Angabe ist der semantische Layer-Modus, die
zweite die explizit reviewbare Coverage-Menge. Ein wertgenauer Invariantentest
koppelt beide jetzt an `precision: global`, `stalePolicy: not-applicable` und
`unsupportedBehavior: hide`. Entsprechende Invarianten gelten für `strict`,
`global-context` und `scope-presentation`; der frühere reine Präsenztest entfiel.

## Katalogeinordnung

Es gibt keinen Widerspruch zwischen Start Record und Abschlussverifikation:

- `spatial-v1-e76a16bff799` ist der historische Plan-05-Canary mit 204 Scopes,
  68 Assets und 38/38 Containment-Gates;
- `spatial-v1-fe9828dcda05` ist der aktuelle veröffentlichte Katalog mit 204 Scopes,
  41 Assets und denselben 38 Containment-Deskriptoren;
- die Differenz 68 → 41 betrifft Render-LODs, nicht die Containment-Fläche.

Die 0-m-Ableitungsfehlermessung gehört zum historischen Canary. Für den aktuellen
Katalog wurden in Plan 08 `verify` und `audit` ausgeführt. Das ändert die
Laufzeitsicherheit nicht: `maxErrorMeters` kommt aus dem aktiven Deskriptor und das
Fehlerband wird als `boundary-uncertain` aus der Included-Menge entfernt.

## TDD- und Verifikationsevidenz

Der neue Runtime-Claim-Test lief vor der Implementierung gezielt rot:

```text
Test Files  1 failed (1)
Tests       1 failed | 19 passed (20)
Expected "intersects" in the flights runtime claim
```

Nach der zentralen Ableitung:

```text
focused policy suite   20/20
frontend suite         106 files, 595/595
ESLint                 clean
TypeScript             clean
production build       successful
git diff --check       clean
```

Der Build enthält nur den bekannten Chunk-Size-Hinweis. Die Benchmark-Suite lief
innerhalb ihrer bestehenden Budgets; aus diesem Review-Lauf wird keine neue
Browser-/GPU- oder Ableitungsfehler-Baseline behauptet.

## Bewusste Grenzen

- Keine Backend-, Intelligence- oder Data-Ingestion-Datei wurde verändert. Der
  vorbestehende Data-Ingestion-Skip bleibt ein separater Aufräumlauf.
- Work Order 2 bleibt gestoppt, Admin-2 bleibt mangels Auswahl-/Coverage-Evidenz
  blockiert und 3D bleibt deferred.
- Es gab keinen Katalog-Publish, keine Neo4j-/Qdrant-Mutation, keinen Push, PR,
  Merge oder Deployment.
- Die drei vorbestehenden fremden Worktree-Pfade blieben außerhalb beider Commits.
