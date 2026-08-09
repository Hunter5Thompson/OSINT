# HANDOFF — Spatial Scope Plan 06B abgeschlossen → Plan 07A

**Datum:** 2026-08-09

**Nächster Chat:** Plan 07A — Qdrant Spatial Payload, strikt testgetrieben

**Branch:** `feat/spatial-plan03`

**Repo:** `/home/deadpool-ultra/ODIN/OSINT`

**Plan-06B-Abschluss-HEAD:** `bd3c10b`

**Remote-Stand vor diesem Handoff:** `origin/feat/spatial-plan03` bei `bd3c10b`,
Divergenz `0/0`

**Status:** Plan 06B ist implementiert, unabhängig nachreviewt und abgenommen. Die
Exact-Registry bleibt leer/default-off; es gab keine CHRONIK-Aktivierung und keine
Datenmutation. Als Nächstes folgt **Plan 07A**, danach **Plan 07B**.

## Reihenfolge: Ja, jetzt kommt Plan 07

Der kanonische Slice 7 ist in zwei zwingend aufeinanderfolgende Teilpläne geteilt:

1. **07A — Qdrant Spatial Payload:** Payload-/Indexvertrag, deterministische
   Projektion, Filter-Compiler und restartbares Re-Enrichment. Benötigt den
   Plan-06A-Assignment-Vertrag.
2. **07B — Munin Scope Enforcement:** gepinnter Run-Scope, capability-bound Tools
   und fail-closed Qdrant-/Graph-Zugriffe. Benötigt die Implementierungen von 06B
   **und** 07A.

Die drei noch offenen operativen Promotionsgates von 06B blockieren die
testgetriebene Implementierung von 07A nicht. Sie verbieten weiterhin eine
behauptete oder reale Exact-Promotion. Slice 7 ist erst nach 07A **und** 07B fertig.

Der globale Planindex ist statusseitig nicht vollständig nachgezogen: Sein Header
nennt noch Plan 03 als aktiv und seine Tabelle führt 06A/06B als `PLANNED`. Für den
aktuellen Stand sind die abgenommenen Plan-Checkboxen, Commits und Reports
maßgeblich; die Abhängigkeitsreihenfolge des Index bleibt dagegen gültig.

## Pflichtstart im nächsten Chat

Vor jeder Änderung vollständig lesen:

1. `AGENTS.md`
2. `CLAUDE.md`
3. dieses Handoff
4. [Implementation-Planindex](plans/2026-08-01-spatial-scope-implementation.md)
5. [Plan 07A](plans/2026-08-01-spatial-scope/07a-qdrant-spatial-payload.md)
6. [Spec 09 — Qdrant-Retrieval](specs/2026-07-31-spatial-scope-drilldown/09-qdrant-retrieval.md)
7. [Spec 02 §7.5 — Katalog- versus Derivationsrevision](specs/2026-07-31-spatial-scope-drilldown/02-scope-identity-and-boundary-policy.md)
8. [Spec 12 §22 — Observability](specs/2026-07-31-spatial-scope-drilldown/12-errors-security-and-observability.md)
9. [Spec 13 Slice 7](specs/2026-07-31-spatial-scope-drilldown/13-implementation-and-tdd-slices.md)
10. [Spec 14 §§26–27 — Rollout und Stop-Regeln](specs/2026-07-31-spatial-scope-drilldown/14-rollout-and-acceptance.md)
11. [Plan 06A](plans/2026-08-01-spatial-scope/06a-neo4j-normalization-and-backfill.md)
12. [Plan-06A-Live-Evidence](../reports/2026-08-08-spatial-plan06a-neo4j-verification.md)
13. [Plan-06B-Review-Remediation](../reports/2026-08-09-spatial-plan06b-review-remediation.md)

Dann Zustand neu prüfen:

```bash
git status --short --branch
git log -12 --oneline --decorate
git rev-list --left-right --count HEAD...origin/feat/spatial-plan03
```

Die aktuell sichtbaren Änderungen an diesen Dateien sind fremd und dürfen nicht
geändert, gestaget oder zurückgesetzt werden:

- `docs/CONTAINER-STATUS.md`
- `scripts/spark/odin-spark-vllm.sh`

Kein PR, Merge nach `main`, Live-Index-Apply oder Re-Enrichment-Apply ohne
ausdrücklichen Auftrag.

## Verbindlicher Plan-06A-Vertrag für Qdrant

Die reine Normalisierung lebt in
`services/data-ingestion/graph_integrity/spatial_normalizer.py`. Der 07A-Projector
darf ausschließlich strukturierte `RawLocationIdentity`-/Assignment-Evidenz und den
reviewten Katalogindex konsumieren. Der normalisierte Vertrag liefert unter anderem:

```text
country_scope_key
admin1_scope_key
admin2_scope_key
latitude / longitude
spatial_basis
spatial_precision
spatial_catalog_revision
spatial_derivation_revision
spatial_conflict
spatial_conflict_scope_keys
```

Dabei gelten unverändert:

- `spatial_catalog_revision` ist Audit-Provenance des letzten Enrichments.
- Der Plan-06A-Scalar `spatial_derivation_revision` bezeichnet nur den terminal
  ausgewählten Scope. Der Qdrant-Projector darf ihn nicht als recordweite
  Filterdimension oder als Revision seiner Ancestors kopieren.
- Query-Compiler vergleichen niemals Record-Katalogrevision mit der
  Request-Katalogrevision.
- Kompatibilität wird pro Scope über die reviewte Menge kompatibler
  Derivationsrevisionen und im Qdrant-Filter ausschließlich über atomare
  Scope-/Revisions-Pair-Tokens entschieden.
- Bei Conflicts bleibt `spatial_derivation_revision` null. Der 07A-Projector darf
  ihre Audit-Keys nur unter `spatial_conflict_scope_keys`, niemals in den
  filterbaren About-/Occurrence-Arrays publizieren.
- Country-only-Evidenz erzeugt keinen erfundenen Punkt.
- Child-Zuordnungen materialisieren alle nicht-globalen Ancestors; `world` wird im
  Payload nicht gespeichert.
- Kein Ortsname-, Querytext- oder Substring-Raten.

## Verbindlicher Plan-07A-Payloadvertrag

Relationen bleiben getrennt:

```text
spatial_about_scope_revision_tokens       keyword[]
spatial_occurrence_scope_revision_tokens  keyword[]
geo                               geo point or geo point[]
spatial_basis                     keyword[]
spatial_precision                 keyword
spatial_catalog_revision          keyword
spatial_projection_revision       keyword
spatial_derivation_version        keyword
spatial_conflict                  bool
spatial_conflict_scope_keys       keyword[]
```

Zusätzlich bleiben die rohen, auditierbaren Codefelder aus Spec 09 erhalten. Die
zehn oben genannten Felder besitzen gemäß Spec 09 §16.2 Payload-Indizes mit exakt
den Typen Keyword/Geo/Bool. Bestehende neun Corpus-/Fulltext-Indizes dürfen bei der
Erweiterung nicht verloren gehen.

`occurrence` darf nur aus einer strukturierten Event-/Sensor-Location oder einer
belastbaren Koordinate entstehen. `about` darf nur aus einer explizit extrahierten,
eindeutig gecrosswalkten Geo-Entität oberhalb des versionierten Confidence-Gates
entstehen. Audit-Derivationen dürfen mehr enthalten als die filterbaren Arrays; der
deterministische Projector entscheidet, nicht das Retrieval-LLM.

Ein Re-Enrichment ersetzt **alle** `spatial_*`-Felder eines Points atomar. Es darf
niemals Arrays aus Lauf A mit scalar Revisionen aus Lauf B mischen.

## BLOCKING Design-Gate vor Work Order 1: Ancestor-Key plus scalar Revision

Beim Erstellen dieses Handoffs wurde ein bisher nicht dokumentierter Widerspruch
zwischen dem realen 06A-Vertrag und Spec 09 nachgewiesen:

1. Der Katalog erzeugt die Derivationsrevision pro Scope; `scope_path` ist Teil des
   Hashes. Im aktiven Manifest besitzen 176 Country-Scopes 176 unterschiedliche
   Revisionen und 27 Admin1-Scopes 27 unterschiedliche Revisionen.
2. Ein auf Admin1 aufgelöstes Assignment materialisiert Country- und Admin1-Key,
   trägt aber als scalar `spatial_derivation_revision` nur die Revision des tiefsten
   ausgewählten Scopes.
3. Spec 09 legt Country- und Admin1-Key gemeinsam in ein Relation-Array und verlangt
   gleichzeitig, dass der Filter den scalar Revisionswert gegen die
   Compatibility-Menge des angefragten Scopes prüft.

Konkrete aktive Evidenz:

```text
country:UKR
  spatial-derive-v1-d30efa07e141

admin1:iso3166-2:UA-14
  spatial-derive-v1-4d1de888e0c7
```

Ein UA-14-Point würde also `country:UKR` und `admin1:...:UA-14` im
Occurrence-Array tragen, aber nur `4d1de888e0c7` als scalar Revision. Der in Spec 09
gezeigte Country-Filter verlangt `d30efa07e141` und verwirft den Point trotz korrekt
materialisiertem Country-Ancestor. Damit erfüllt die vorgesehene V1-Projektion ihr
eigenes Ziel „Country-Queries ohne Runtime-Hierarchiejoin“ nicht.

Das ist kein Randfall und darf nicht durch eines der folgenden Manöver kaschiert
werden:

- Revisionsprädikat entfernen;
- Child-Revisionen pauschal in Parent-Kompatibilität aufnehmen;
- Derivationsrevision wieder globalisieren;
- nur Country-only-Records testen;
- den Fehler als `partial coverage` etikettieren, obwohl das Schema den gültigen
  Ancestor nicht ausdrücken kann.

Vor Definition der finalen Payload-Indizes braucht es deshalb eine reviewte
Spec-/Plan-Entscheidung für eine **gepaarte Scope-/Revisionsrepräsentation pro
Relation und Ancestor**. Belastbare Richtungen sind beispielsweise relation-spezifische
Nested-Assignments oder ein kanonischer kombinierter
`scope_key + derivation_revision`-Keyword pro Ancestor; dies ist noch keine
freigegebene Designentscheidung. Getrennte unkorrelierte Arrays benötigen mindestens
einen bewiesenen Pairing-/Collision-Vertrag.

Der erste RED-Nachweis muss einen Admin1-abgeleiteten Point sowohl über seinen
Admin1-Token als auch über den Country-Parent-Token finden und jeweils inkompatible
Revisionen ausschließen. Erst wenn dieser Vertrag reviewed und Spec 09/Plan 07A
entsprechend korrigiert sind, ist Work Order 1 ausführbar.

Der gleiche scalar-Revision-/Ancestor-Key-Sachverhalt betrifft grundsätzlich auch
die spätere Neo4j-Country-Promotion für Locations, die tiefer als Country aufgelöst
sind. Plan 06B bleibt inert; vor einer realen Promotion muss diese Population im
Candidate/Stale-Smoke explizit enthalten sein oder der Vertrag korrigiert werden.

### Design-Gate-Auflösung 2026-08-10

Das Gate wurde mit drei unabhängigen Interface-Entwürfen sowie einem lokalen
Qdrant-Contract-Proof reviewed. Normativ gilt nun Spec 09 in der korrigierten Form:

```text
spatial_about_scope_revision_tokens[]
spatial_occurrence_scope_revision_tokens[]

sr1|<canonical non-global ScopeKey>|<DerivationRevision>
```

Die Relation bleibt durch zwei getrennte Felder sichtbar; Scope und genau dessen
Revision bleiben innerhalb jedes Keyword-Tokens atomar. `|` ist in beiden
Komponentengrammatiken verboten, womit das Encoding injektiv ist. Der falsche
Qdrant-Scalar `spatial_derivation_revision` entfällt. Ein separater
`spatial_projection_revision`-Fingerprint dient ausschließlich restartbarer
Job-/Idempotenzsteuerung und niemals der fachlichen Scope-Compatibility.

Der erste RED enthielt einen gültigen UA-14-Point, einen vertauschten
Parent-/Child-Poison-Point und einen inkompatiblen Point. Die gewählte Repräsentation
findet nur den gültigen Point sowohl für `country:UKR` als auch für
`admin1:iso3166-2:UA-14`. Der gemeinsame Vertrag ist
`contracts/qdrant-spatial-payload-v1.json`. Diese Auflösung ersetzt die ursprüngliche
scalar Payloadannahme und gibt Work Order 1 frei.

## Read-only Qdrant-Ausgangsbaseline

Am 2026-08-09 wurde der laufende Qdrant ausschließlich lesend geprüft:

| Merkmal | Stand |
|---|---:|
| Qdrant | `1.13.2` |
| Collection | `odin_intel`, Status `green` |
| Points | `1.023.349` |
| Indexed vectors | `1.021.023` |
| Vector | unnamed, `1024`, `Cosine` |
| Sparse vectors | keine |
| vorhandene Payload-Indizes | 9 |
| vorhandene Spatial-Payload-Indizes | 0 |

Vorhanden sind ausschließlich die bisherigen Indizes für `source`,
`telegram_channel`, `notebook_id`, `feed_name`, `url`, `fulltext_article_id`,
`fulltext_status`, `superseded_by_fulltext` und `fulltext_retry_epoch`.

Diese Momentaufnahme ist **keine** Spatial-Coverage-Evidenz. Ein fehlender
Payload-Index beweist nicht, dass kein einzelner Point das Feld trägt. Die aktiven,
im 07A-Dateiscope genannten GDELT- und NLM-Payload-Builder schreiben im aktuellen
Code jedoch noch keine `spatial_*`-Felder.

Die Collection ist Produktionsbestand mit mehr als einer Million Points. Weder
`scripts.ensure_payload_indexes` noch irgendein Re-Enrichment darf für einen
Code-/Unit-Test oder beiläufig im Runtime-Start gegen diese Collection ausgeführt
werden.

## Bestehende Code-Seams

### Intelligence

- `rag/qdrant_schema.py` besitzt `PAYLOAD_INDEXES`, prüft aktuell aber nur fehlende
  Feldnamen und noch keine falschen bestehenden Payload-Typen.
- `scripts/ensure_payload_indexes.py` ist der einzige autorisierte
  Index-Migrationspfad. Er erzeugt nur fehlende Indizes mit `wait=True` und ist
  bereits idempotent.
- `rag/retriever.py` führt einen read-only Schema-Preflight aus und warnt bei
  fehlenden Indizes. Die Analysis-/Realtime-Corpus-Policy kommt aus
  `rag/corpus_policy.py`.
- `rag/indexer.py` und die Retriever-Signaturen tragen noch Legacy-`region` und
  Dict-Filter. Plan 07A ergänzt den reinen, qdrant-client-basierten Spatial-Compiler;
  Plan 07B entfernt später den Modell-Override aus dem Tool-Schema.

### Data Ingestion

- `qdrant_doctor/schema.py` validiert bisher nur Vector-/Hybrid-Schema, nicht die
  Payload-Indexverträge.
- `gdelt_raw/writers/qdrant_writer.py::build_payload` baut GKG-Dokumentpayloads und
  kennt zwar `linked_event_ids`, aber keine Spatial-Zuordnung.
- Die strukturierte GDELT-Occurrence-Evidenz liegt auf den Eventzeilen und wird im
  Neo4j-Writer bereits über den Plan-06A-Normalizer verarbeitet. Sie darf für Qdrant
  nicht aus Titel, Theme oder Ortsnamen rekonstruiert werden.
- `nlm_ingest/ingest_qdrant.py::build_claim_points` schreibt Claim-Points. Claims
  tragen derzeit nur Entity-Namen; typisierte Entity-Art und Confidence liegen in
  `Extraction.entities`. About-Projektion muss diese strukturierte Evidenz verwenden
  und eindeutig crosswalken, niemals Namen per Substring matchen.
- `contracts/qdrant-provenance-v1.json` ist das bestehende Muster für einen
  sprach-/service-neutralen Vertrag.

Der Live-Corpus enthält wesentlich mehr Source-Typen als GDELT und NLM. Vor Work
Order 2 muss deshalb eine explizite Lane-/Writer-Inventur festhalten, welche Writer
Spatial-Evidenz unterstützen. Nicht unterstützte Lanes melden
`spatial derivation unavailable`; sie erfinden keine Keys und verschwinden nicht aus
dem Coverage-Report. Das ist keine Erlaubnis, opportunistisch alle Collector in 07A
umzubauen.

## Allererste 07A-Aufgabe: Contract-RED, danach Work Order 1

Noch keine Writer-, Index- oder Live-Migration anfassen. Zuerst das oben beschriebene
Ancestor-/Revision-RED festhalten, die Repräsentation reviewen lassen und die
normativen Dokumente korrigieren. Nicht blind die derzeitige scalar Spec
implementieren.

Danach einen gemeinsamen, eingecheckten JSON-Vertragsvektor für Payload-Indizes
anlegen und ihn aus beiden Service-Test-Suites lesen. Kein Runtime-Import zwischen
Services.

Die ersten fehlschlagenden Tests müssen beweisen:

1. Alle neun bestehenden Payload-Indizes bleiben erhalten.
2. Alle zehn Spatial-Indizes aus Spec 09 §16.2 sind mit dem exakten Qdrant-Typ
   vorhanden.
3. Ein vorhandener Index mit falschem Typ wird fail-closed abgelehnt und nicht als
   „vorhanden“ akzeptiert.
4. Die autorisierte Migration erzeugt ausschließlich fehlende Indizes, wartet auf
   Abschluss und ist beim zweiten Lauf ein No-op.
5. Intelligence-Search-Preflight und Ingestion-Writer/Doctor sind read-only in Bezug
   auf Indexerzeugung; nur das explizite Migrationskommando schreibt.
6. Bestehende Vector-/Corpus-Policy-Verträge bleiben unverändert grün.

Erst das RED festhalten, dann minimal GREEN und REFACTOR. Der vorgesehene Commit ist:

```text
build(qdrant): add spatial payload indexes
```

## Danach: verbindliche Work-Order-Reihenfolge

0. **Ancestor-/Revision-Vertrag** — relation-spezifische Paarung festlegen und mit
   Parent-/Child-RED belegen.
1. **Payload-/Indexvertrag** — geteilte JSON-Vektoren, lokale Validatoren,
   autorisierte idempotente Migration.
2. **Deterministische Payload-Projektion** — Relationstrennung, Provenance,
   Ancestors, Conflict-Ausschluss und explizite unsupported Lanes; Writer vor
   Re-Enrichment.
3. **Filter-Compiler und Policy-Komposition** — `world -> None`,
   `about/occurrence/either`, kompatible Derivationsrevisionen und unveränderte
   Analysis-/Realtime-Policy als verschachteltes zusätzliches `must`.
4. **Restartbares atomisches Re-Enrichment** — zuerst Dry-run, Cursor-/Resume- und
   Idempotenznachweis, dann nur nach Review ein ausdrücklich freigegebener Apply.

`combine_filters` darf das bestehende Filterobjekt weder mutieren noch dessen
`should`-/`must_not`-Semantik durch flaches Zusammenführen verändern. Eine leere,
partielle, unsupported oder technisch fehlgeschlagene Spatial-Suche löst niemals
einen ungefilterten Retry aus.

## Mutations- und Promotionsgates

Folgende Arbeiten sind ohne neue ausdrückliche Freigabe **nicht** Teil des Starts:

- Payload-Indizes auf der laufenden `odin_intel`-Collection anlegen;
- bestehende Points re-enrichen oder reindexieren;
- die Collection löschen, neu erstellen oder Payloads partiell überschreiben;
- irgendeine Neo4j-/Qdrant-Exact-Capability aktivieren;
- Plan 07B vor dem 07A-Exit beginnen.

Vor einem späteren Qdrant-Apply gelten mindestens:

1. autorisierte Indizes vor Re-Enrichment;
2. reviewter Dry-run und machine-readable Coverage pro Corpus-Lane;
3. restartbarer Cursor und lane+target-projection-revision Checkpoint;
4. atomischer Ersatz aller `spatial_*`-Felder;
5. sichtbares Conflict-/Stale-/Unsupported-Accounting;
6. Stale-Anteil über 0 sichtbar, über 1 % promotionsblockierend;
7. keine ungefilterte Retry- oder Fallback-Route.

Eine reine Katalog-Carry-forward-Revision mit identischer Derivationsrevision darf
keinen Corpus-Rewrite auslösen.

## Plan-06B-Stand, den 07A nicht neu öffnen soll

Plan 06B landete in diesen Commits:

| Zweck | Commit |
|---|---|
| statische Exact-Templates | `504c5d1` |
| Exact-Accounting | `8503128` |
| serverseitige Aktivierungsregistry | `b6f7345` |
| Review-Härtung | `eb7d807` |
| Promotions-/Deploy-Dokumentation | `db62cba` |
| ADMIN1-Coverage-Hinweis | `bd3c10b` |

Verifiziert wurden Backend `553 passed`, Ruff und strict MyPy über 88 Module sowie
Frontend `559 passed`, TypeScript und ESLint. Alle 18 statischen Neo4j-Templates
bestanden live `EXPLAIN` read-only und index-backed. Die Registry blieb leer.

Noch offen und **nicht** als erledigt zu markieren:

- Incident-Location-Coverage: aktuell `0/11793` scope-keyed Incidents;
- Candidate-Baseline und unlocated-Coverage-Attestierung pro konkreter Promotion;
- echtes `PROFILE`/Zeilenbudget für den unbegrenzten Exact-Geo-Read.

Zusätzlich wurde bei dieser Übergabe der oben belegte
Ancestor-Key/scalar-Revision-Widerspruch gefunden. Er ändert nichts an der
Default-off-Abnahme von 06B, ist aber vor jeder Promotion einer Parent-Lane mit
tiefer aufgelösten Locations zu schließen.

Diese Punkte sind Promotionsvorbereitung, keine Aufforderung, sie in 07A nebenbei zu
reparieren.

## Test- und Commitdisziplin für 07A

- Strikt TDD pro Work Order: RED sichtbar machen, minimal GREEN, dann REFACTOR.
- Fokussierte Tests aus Plan 07A aus den jeweiligen Service-Verzeichnissen starten.
- Vor 07A-Abschluss vollständig:

```bash
cd services/intelligence
uv run pytest

cd services/data-ingestion
uv run pytest
```

- Die 06B-Abnahme änderte Intelligence/Data-Ingestion nicht; ihre kompletten Suites
  wurden für dieses Doc-only Handoff nicht erneut ausgeführt.
- `uv.lock` ist nur in `services/data-ingestion` getrackt. Keine unbeabsichtigten
  Lockfile-/Dependency-Änderungen aufnehmen.
- Fremde Worktree-Änderungen nie mitstagen.
- Jeder Commit entspricht genau der im Plan genannten Work Order.
- Code-Evidence, Dry-run-Evidence und Live-Apply-Evidence strikt trennen.

## Übergabeziel

Der nächste Agent beginnt ausschließlich mit dem RED für einen Admin1-abgeleiteten
Point, der über Child- und Parent-Token korrekt filterbar bleiben muss. Er stoppt
danach am Design-Gate, bis die gepaarte Scope-/Revisionsrepräsentation reviewed ist,
und startet erst dann Work Order 1. Nach grünem 07A-Exit übergibt er Plan 07B einen
reinen kompilierten Qdrant-Filter, unveränderte Corpus-Policy-Komposition und einen
belastbaren Coverage-/Stale-/Unsupported-Vertrag. Bis zu einem separat reviewten
Apply bleibt die laufende Qdrant-Collection unverändert.
