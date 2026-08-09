# HANDOFF — Spatial Scope Plan 06A abgeschlossen → Plan 06B

**Datum:** 2026-08-09

**Nächster Chat:** Plan 06B — CHRONIK Exact Scope, strikt testgetrieben

**Branch:** `feat/spatial-plan03`

**Repo:** `/home/deadpool-ultra/ODIN/OSINT`

**Geprüfter Ausgangs-HEAD:** `4f002ea` (`origin/feat/spatial-plan03`, Divergenz
`0/0` vor diesem Handoff)

**Runtime-Code-Commit:** `c947dd9`

**Basis:** `origin/main` bei `7704d8e`

**Status:** Plan 06A ist nach finalem unabhängigen Review mit **20/20 akzeptiert**.
Plan 06B darf implementiert werden. Backfill-Apply und Exact-Aktivierung bleiben bis
zur Erfüllung ihrer Betriebsgates gesperrt.

Dieses Dokument ersetzt für den nächsten Chat das Handoff vom 2026-08-07. Das alte
Dokument bleibt als ausführlicher historischer Vertrag erhalten:
[HANDOFF-spatial-scope-plan06b-2026-08-07.md](HANDOFF-spatial-scope-plan06b-2026-08-07.md).

## Pflichtstart im nächsten Chat

Vor jeder Änderung vollständig lesen:

1. `AGENTS.md`
2. `CLAUDE.md`
3. dieses Handoff
4. [Plan 06B](plans/2026-08-01-spatial-scope/06b-chronik-exact-scope.md)
5. [Spec 07 §14.2–14.5](specs/2026-07-31-spatial-scope-drilldown/07-chronik-query-contract.md)
6. [Spec 08 §15.2 und §15.5](specs/2026-07-31-spatial-scope-drilldown/08-neo4j-normalization.md)
7. [Spec 14 §26.1 und §26.3](specs/2026-07-31-spatial-scope-drilldown/14-rollout-and-acceptance.md)
8. [Plan-06A-Live-Evidence](../reports/2026-08-08-spatial-plan06a-neo4j-verification.md)

Dann Zustand neu prüfen:

```bash
git status --short --branch
git log -8 --oneline --decorate
git rev-list --left-right --count HEAD...origin/feat/spatial-plan03
```

Die aktuell sichtbaren Änderungen an diesen beiden Dateien sind fremd und dürfen
nicht geändert, gestaget oder zurückgesetzt werden:

- `docs/CONTAINER-STATUS.md`
- `scripts/spark/odin-spark-vllm.sh`

Kein PR und kein Merge nach `main` ohne ausdrücklichen Auftrag.

## Allererste 06B-Aufgabe: Read-Contract ausführbar machen

Work Order 1 beginnt mit einem RED-Test für den bislang nur dokumentierten
Konflikt-Ausschluss. Dies ist vor allen anderen Exact-Templates umzusetzen.

Der Test muss für jedes statische Event-Occurrence-Template der geschlossenen
Registry (`country`, `admin1`, `admin2`) beweisen:

- `l.spatial_conflict = false` ist Bestandteil des Cypher-Vertrags;
- Scope-Key und freigegebene `spatial_derivation_revision` sind gebundene Parameter;
- keine Property-Namen oder Cypher-Fragmente werden dynamisch zusammengesetzt;
- ein konfliktbehafteter Treffer wird auch dann ausgeschlossen, wenn er dieselbe
  Scope- und Derivationsrevision wie ein gültiger Treffer trägt;
- mehrere passende `OCCURRED_AT`-Locations liefern genau ein Top-Level-Event und
  verbrauchen das Zeilenlimit nicht mehrfach.

Der Konfliktfilter ist der **tragende** Sicherheitsmechanismus. Die nullwertige
Derivationsrevision neuer Conflicts ist nur Defense-in-Depth. Die fünf bestehenden,
vor `c947dd9` geschriebenen Conflicts tragen weiterhin eine nicht-null Revision und
wären ohne den expliziten Filter index- und query-fähig. Sie dürfen nicht still im
Rahmen von 06B repariert werden.

Erst nach diesem RED/GREEN-Nachweis mit dem restlichen Work Order 1 fortfahren:
statische vollständige Cypher-Templates, deterministischer Collapse vor `LIMIT`,
`count(DISTINCT ev)`, Enum-Auswahl und Unsupported für unbekannte Kind/Relation-
Kombinationen.

## Verbindlicher Plan-06A-Vertrag für 06B

Exact Queries konsumieren ausschließlich die materialisierten `:Location`-Felder:

```text
country_scope_key
admin1_scope_key
admin2_scope_key
spatial_catalog_revision
spatial_derivation_revision
spatial_conflict
```

Zusätzlich gelten:

- Exact bedeutet Scope-Key-Matching, nicht BBox-Näherung.
- Jede Query ist ein vollständiges statisches Template; alle Werte sind gebunden.
- Kein LLM-generiertes Cypher im Write- oder Exact-Template-Pfad.
- `spatial_conflict = false` ist für jeden Exact-Read verpflichtend.
- Nur freigegebene kompatible Derivationsrevisionen dürfen matchen.
- Country-only-Daten bleiben punktlos; kein erfundener Centroid oder Admin-Key.
- Konflikte, stale Revisionen, unlocated und unsupported bleiben getrennt sichtbar.
- Doppelte Locations dürfen weder Resultate noch Accounting aufblasen.
- Ein Exact-Ausführungsfehler darf nicht im selben Request still auf BBox oder global
  zurückfallen; der Vertrag verlangt `503/SPATIAL_FILTER_UNAVAILABLE`.
- Aktivierung ist serverseitig, allowlisted und pro Lane/Scope-Kind. Sie ist niemals
  clientgesteuert.

## Final verifizierter Stand von Plan 06A

Das abschließende Review hat Code, Tests, laufenden Container und Graph unabhängig
geprüft:

| Gate/Nachweis | Ergebnis |
|---|---|
| Data-Ingestion | `1,365 passed, 1 skipped, 17 deselected` |
| Ruff | clean |
| Branch ↔ Remote | `0/0`, HEAD `4f002ea` |
| Worktree | nur die zwei fremden Dateien |
| Conflict-Fix | zentral in `spatial_normalizer._result` |
| Laufender Writer | geladener Fix per `inspect.getsource` bestätigt |
| Legacy-Conflicts | exakt 5, alle mit nicht-null Derivationsrevision |
| Null Island | 0 über `lat/lon`, 0 über `geo = point(0,0)` |
| Plan-06A-Checkboxen | 20/20 |

Der zentrale Fix setzt `spatial_derivation_revision` nur, wenn ein Scope vorliegt und
kein Conflict besteht. Forward Writer und Backfill teilen damit dieselbe
Normalisierung. Die zusätzliche explizite Nullung in `_plan_update` ist redundant,
aber zulässige Defense-in-Depth. Der Conflict-Zweig steht vor `_targets_job`, sodass
Conflicts weiterhin geplant und nicht vom Target-Check verschluckt werden.

Die fünf Alt-Conflicts wurden bewusst nicht inline repariert: Ohne Backup- und
Repair-Gate wäre das eine ungenehmigte Datenmutation. Bis zu einer separat
freigegebenen Reparatur müssen die Exact-Queries sie nachweislich ausschließen.

## Noch offener Laufzeit-Beobachtungspunkt

Der Container wurde mit dem Fix neu gebaut; der geladene Quellcode und der
Conflict-Zweig sind durch Unit-Tests und eine Laufzeit-Probe belegt. Seit dem Rebuild
ist im live ingestierenden Graphen jedoch noch kein neuer natürlicher Conflict
aufgetreten. Deshalb ist folgender Nachweis noch **nicht** als erledigt zu behaupten:

> Beim ersten neuen, nach `c947dd9` geschriebenen Conflict prüfen, dass
> `spatial_derivation_revision IS NULL` gilt.

Das ist ein Beobachtungspunkt für die Live-Evidence. Er ändert weder die Akzeptanz
von 06A noch ersetzt er den verpflichtenden Read-Filter.

## Historische Evidence, nicht als aktuelle Baseline lesen

Die vier Dry-run-Dateien sind ein eingefrorener Snapshot vor der anschließenden
kontinuierlichen Forward-Writer-Akkumulation:

- [GDELT dry-run](../reports/2026-08-08-spatial-plan06a-gdelt-raw-dry-run.json)
- [RSS dry-run](../reports/2026-08-08-spatial-plan06a-rss-pipeline-dry-run.json)
- [Military Aircraft dry-run](../reports/2026-08-08-spatial-plan06a-military-aircraft-dry-run.json)
- [Backend Incident dry-run](../reports/2026-08-08-spatial-plan06a-backend-incident-dry-run.json)

Ihre `Already = 0`-Werte sind keine aktuelle Graph-Baseline. Der Graph ingestiert
weiter; kleine Abweichungen zwischen Messzeitpunkten sind erwartet. Vor einem Apply
müssen neue, vollständig reviewte Dry-runs für alle vorgesehenen Zielrevisionen
erzeugt werden.

Zum letzten dokumentierten Nachlauf hatte der Graph 17.344 Locations, darunter 6.114
GDELT-Locations. 1.418 Locations trugen die aktuelle Katalogrevision. Davon waren 921
aufgelöste Crosswalk-, 32 aufgelöste Coordinate-, 438 ungelöste und 22 fail-closed
Coordinate-Locations sowie die fünf Legacy-Conflicts. Maßgeblich sind der Zeitstempel
und die Erläuterungen im Evidence-Report, nicht diese Zahlen als dauerhafte Sollwerte.

## Offene Betriebsgates

Sie blockieren einen Backfill-Apply beziehungsweise die Exact-Aktivierung, aber nicht
die testgetriebene Implementierung der 06B-Work-Orders:

1. aktuellen Backup-/Restore-Punkt vor jeder weiteren Datenmutation erstellen und
   dokumentieren;
2. neue Dry-runs für jede tatsächlich vorgesehene Zielrevision reviewen;
3. die 140 unresolved GDELT- und 10 unresolved RSS-Zeilen des historischen Snapshots
   fachlich bewerten; aktuelle Counts neu messen;
4. `backend_incident` als Cross-Service-Writer integrieren und belegen;
5. die neun Military-Aircraft-Locations ohne stabile IDs behandeln; die Lane ist noch
   keine vollständige Promotion-Evidence;
6. Apply-Reports und reconciliertes Accounting erzeugen;
7. die fünf Legacy-Conflicts nur über ein explizit freigegebenes Repair-Gate ändern
   oder dauerhaft durch den getesteten Read-Contract ausschließen;
8. jede Lane/Kind-Kombination erst nach Coverage-, Revision-, Indexplan- und
   Accounting-Nachweis serverseitig aktivieren;
9. den ersten natürlich auftretenden Post-Fix-Conflict als Laufzeit-Beobachtungspunkt
   prüfen.

Der Neo4j-5.26.23-Nachweis und alle vier Spatial-Indizes waren zuletzt `ONLINE`; die
realen `EXPLAIN`-Pläne nutzten die vorgesehenen Indizes. Vor Aktivierung muss 06B die
Staging-`EXPLAIN`- und Accounting-Smokes dennoch für jede konkret zu promotende
Lane/Kind-Kombination erneut ausführen.

## Relevante Commits

| Zweck | Commit |
|---|---|
| Pure Normalizer | `3f62b43` |
| Forward Writer | `2dae8a7` |
| Spatial-Indizes | `cfe20b2` |
| Backfill/Re-Enrichment | `51f15f9` |
| Review-Fixes | `2aee913` |
| Plan-06A-Evidence | `f92915d` |
| Forward-Conflict-Revision | `c947dd9` |
| Korrigierte Live-Evidence | `4f002ea` |

## Arbeitsweise und Gates für Plan 06B

- Strikt TDD pro Work Order: RED festhalten, minimal GREEN, dann REFACTOR.
- Nach jedem Work Order die im Plan genannte fokussierte Suite ausführen.
- Vor Abschluss des Backend-Slices vollständig aus `services/backend`:

```bash
uv run pytest
uv run ruff check app/
uv run mypy app/
```

- Bestehende fremde Änderungen nicht in Commits aufnehmen.
- Aussage und Evidence trennen: keine Aktivierung oder Live-Wirkung behaupten, die
  nicht gegen den tatsächlich laufenden Container und Graphen geprüft wurde.
- `TASK-123` bleibt offen, bis die gesamten Slice-6-/06B-Exit-Gates erfüllt sind.

## Übergabeziel

Der nächste Agent beginnt mit dem ausführbaren Conflict-Ausschluss im ersten RED-Test
von Work Order 1. Danach setzt er Plan 06B in der vorgegebenen Reihenfolge um. Exact
wird erst aktiviert, wenn alle betroffenen Lane/Kind-Kombinationen ihre operativen
Gates nachweislich erfüllen. Bis dahin bleibt der bestehende Modus ehrlich
`bbox_approximate`.
