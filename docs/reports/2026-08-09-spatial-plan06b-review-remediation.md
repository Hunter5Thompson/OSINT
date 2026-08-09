# Spatial Plan 06B — Review-Remediation

**Datum:** 2026-08-09
**Scope:** CHRONIK Exact-Scope-Reads; keine Aktivierung, kein Graph-Write

## Implementierte Review-Korrekturen

1. Die Aktivierungsregistry ist pro
   `(lane, scope_kind, derivation_revision)` eindeutig. Mehrere Country-Scopes können
   gleichzeitig freigegeben werden; der aufgelöste Token wählt den passenden
   Revisionsdatensatz aus der Lane/Kind-Menge.
2. Exact-Accounting misst `candidate_count` unabhängig als alle unterschiedlichen
   Events mit dem angefragten Scope-Key. Included, Conflict, Stale und Unsupported
   partitionieren und reconciliieren genau diese scope-relative Menge.
3. Der globale Unlocated-Full-Window-Scan ist aus Exact entfernt. Unlocated-Coverage
   ist ein scope-spezifisches Promotion-Gate; ohne vollständige Evidenz bleibt der
   Scope approximate. Damit ist `complete` für als abgedeckt attestierte Scopes
   erreichbar.
4. Exact-Histogramme lesen Event- und Incident-Notables über getrennte statische
   Scope-Key-Templates. Damit bleibt das Incident-Tier-1-Ranking strukturell
   erhalten, sobald Incident-Locations dieselbe Scope-Coverage besitzen. Das ist
   aktuell nicht der Fall: 0 von 11.793 Incidents besitzen eine scope-keyed Location;
   eine heutige Promotion würde deshalb weiterhin alle Incident-Notables verlieren.
5. `excluded_unsupported_count` ist kein interner Totwert mehr. Der Count-Compiler
   misst den nicht klassifizierbaren Scope-Key-Zustand; Backend-Wire-Modell,
   Frontend-Decoder und Statusanzeige berichten ihn.
6. Sample-, Event-Notable- und Incident-Notable-Collapse bevorzugen eine passende
   koordinatentragende Location vor dem stabilen ID-/Name-Tiebreaker. Geo liest nur
   koordinatentragende Matches.
7. Alle Exact-Resultsets eines Requests laufen in einer gemeinsamen read-only
   Neo4j-Transaktion. Accounting-Vertragsfehler besitzen ein eigenes Logsignal. Der
   Stale-Grenzwert liegt validiert in Deployment-Settings; Subqueries verwenden die
   Neo4j-5.23+-Form `CALL () { ... }`.

## Verifikation

- Backend: `553 passed`
- Backend-Qualität: Ruff sauber; strict MyPy sauber über 88 Module
- Frontend: TypeScript sauber; ESLint sauber; `559 passed`
- Live Neo4j: 18/18 statische Exact-Templates via `EXPLAIN` erfolgreich,
  `READ_ONLY`, jeweils mit Indexoperator
- Read-only Accounting-Smoke gegen Produktionsdaten:
  - `country:USA`: candidate/included `13316/13316`, alle Exclusions `0`
  - `country:IND`: candidate/included `1696/1696`, alle Exclusions `0`
  - beide Partitionen reconciliert
- Keine Mutation, kein Backfill-Apply, keine Registry-Aktivierung

ADMIN2 bleibt operativ nicht promotierbar: syntaktische und indexseitige Evidenz
ersetzt keine Daten-Coverage.

## Offene Promotionsgates

- **Incident-Coverage:** `event_occurrence.coverage_complete` attestiert derzeit
  nicht separat die vom Histogramm gelesenen Incidents. Vor jeder Promotion muss
  Incident-Location-Coverage pro Scope-Kind separat gemessen und attestiert werden.
  Die aktuelle Quote `0/11793` blockiert eine ehrliche Promotion.
- **Attestierte Completeness:** Exact misst unlocated Records nicht zur Request-Zeit;
  `excluded_unlocated_count=0` und damit `complete` vertrauen vollständig der
  serverseitig konfigurierten Coverage-Evidenz. Vor Promotion müssen diese Evidenz,
  ein erwartbarer Candidate-Baseline-Bereich und ein Accounting-Smoke für die
  konkrete Lane/Kind/Derivation dokumentiert sein. Ein Runtime-Warnsignal für eine
  aktive Registry bei `candidate_count == 0` ist ein sinnvoller Folge-Guard, aber in
  diesem Commit nicht implementiert.
- **Geo-Kosten:** Das Exact-Geo-Template ist schmal, aber unbegrenzt. Für
  `country:USA` werden aktuell 13.156 Zeilen für höchstens 200 Antwort-Dots gelesen;
  zusammen mit den übrigen Snapshot-Reads entstehen rund 27.000 Zeilen pro
  Histogramm-Request. Vor Promotion ist ein `PROFILE` mit echten Parametern nötig;
  Transaktionsdauer und Zeilenbudget müssen akzeptiert oder durch serverseitige
  Aggregation/Begrenzung reduziert werden.

## Deployment-Reihenfolge

`excluded_unsupported_count` ist innerhalb `schema_version=1` für den neuen
Frontend-Decoder verpflichtend. Deshalb muss bei einem gestaffelten Rollout zuerst
das Backend ausgerollt und das Feld in CHRONIK-Antworten verifiziert werden; erst
danach darf das Frontend folgen. Beim Rollback gilt die umgekehrte Reihenfolge. Ein
Frontend-vor-Backend-Rollout würde bis dahin jeden Timeline-Response als
Contract-Fehler verwerfen.

Nicht blockierende Folgepunkte: Das Histogramm-Bündel trägt derzeit einen nur vom
Sample-Template benötigten `limit=1`-Parameter mit. Außerdem zählt der bestehende
Approximate-Geo-Pfad Event/Location-Zeilen, während Exact pro Event kollabiert;
`geo_located_count` ist über einen Moduswechsel daher noch nicht vergleichbar.
