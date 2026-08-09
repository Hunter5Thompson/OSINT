# Spatial Plan 06B — Review-Remediation

**Datum:** 2026-08-09
**Scope:** CHRONIK Exact-Scope-Reads; keine Aktivierung, kein Graph-Write

## Geschlossene Review-Funde

1. Die Aktivierungsregistry ist pro
   `(lane, scope_kind, derivation_revision)` eindeutig. Mehrere Country-Scopes können
   gleichzeitig freigegeben werden; der aufgelöste Token wählt den passenden
   Revisionsdatensatz aus der Lane/Kind-Menge.
2. Exact-Accounting misst `candidate_count` unabhängig als alle unterschiedlichen
   Events mit dem angefragten Scope-Key. Included, Conflict, Stale und Unsupported
   partitionieren und reconciliieren genau diese scope-relative Menge.
3. Der globale Unlocated-Full-Window-Scan ist aus Exact entfernt. Unlocated-Coverage
   ist ein scope-spezifisches Promotion-Gate; ohne vollständige Evidenz bleibt der
   Scope approximate. Damit ist `complete` für tatsächlich abgedeckte Scopes
   erreichbar.
4. Exact-Histogramme lesen Event- und Incident-Notables über getrennte statische
   Scope-Key-Templates. Incident-Tier-1-Ranking bleibt erhalten.
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
- Keine Mutation, kein Backfill-Apply, keine Registry-Aktivierung

ADMIN2 bleibt operativ nicht promotierbar: syntaktische und indexseitige Evidenz
ersetzt keine Daten-Coverage. Ein Accounting-Smoke bleibt bis zur ersten konkret
promotierten Lane/Kind/Derivation offen.
