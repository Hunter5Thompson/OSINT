# Graph Integrity & Geo-Connectivity — Design Spec

**Date:** 2026-06-14
**Status:** Draft (brainstorm-approved, pending user review)
**Scope cut:** Integrität + Geo. Actor-Graph-Enrichment (Relationen aus RSS/Fulltext
extrahieren) ist **explizit raus** → eigenes Feature/Spec.

---

## 1. Kontext & Problem

Ein Live-Audit des Produktions-Neo4j (753.441 Knoten / 17,2 Mio. Kanten) zeigt: Der
**Retrieval-Korpus** (Document ↔ Theme ↔ Entity ↔ Source) ist exzellent verdrahtet
(0 verwaiste Dokumente, 5 verwaiste Entities von ~20k). Der **Reasoning- und
Geo-Layer** dagegen hat vier konkrete Lücken:

| # | Befund | Messwert (Ist) |
|---|--------|----------------|
| P1 | Events ohne Geo → Globe-Event-Layer leer | 510 von 184.633 Events mit `OCCURRED_AT` (**0,28 %**) |
| P2 | Incidents komplett isoliert | **1.952 / 1.952 verwaist** (haben `lat`/`lon` nur als Property) |
| P3 | Legacy-Parallelkanten im Actor-Graph | ~63 Kanten = ~12 echte Fakten (z.B. `ALLIED_WITH` 9× = 1 Fakt) |
| P4 | Entity-Dubletten + Mention-Noise | `Ukraine`/`ukraine` getrennt; `FIRMS` (49k) / `NASA` (42k) dominieren MENTIONS |

### Verifizierte Ursachen (Code-Level, 2026-06-14)

- **P1-GDELT:** Rohspalten `action_geo_lat/long/fullname/country_code/feature_id`
  existieren in `gdelt_raw/polars_schemas.py` (Float64), werden aber in
  `gdelt_raw/transform.py::canonicalize_events` **verworfen** und sind im Writer-Contract
  `gdelt_raw/schemas.py::GDELTEventWrite` (`extra="forbid"`) **nicht erlaubt**.
  **Empirisch bestätigt:** das gespeicherte `gdelt_parquet/events/` enthält 19 Spalten,
  **keine Geo-Spalte** — Geo ist nur in den rohen Export-CSVs, die in einem
  `TemporaryDirectory` landen und nach Verarbeitung gelöscht werden (`gdelt_raw/run.py`).
- **P1-RSS:** Der Extractor (`intelligence/codebook/extractor.py`) liefert
  `locations:[{name, country}]`, **aber keine Koordinaten**; Event-Knoten haben
  überhaupt keine Geo-Property.
- **P2:** `backend/app/cypher/incident_write.py::INCIDENT_UPSERT` setzt `lat`/`lon`/
  `location` nur als Properties — kein `Location`-Knoten, kein `OCCURRED_AT`.
- **P3:** Die Actor-Relation-Templates (`nlm_ingest/write_templates.py`) nutzen heute
  bereits `MERGE` (idempotent) → die Parallelkanten sind **Legacy** von vor der
  Dedup-Umstellung. ABER: Endpunkte werden nur über `name` gematcht
  (`MATCH (source:Entity {name:$source})`), nicht über `(name,type)` → bei
  namensgleichen Entities unterschiedlichen Typs droht Fanout.
- **P4:** `Entity`-MERGE-Key ist `{name, type}` ohne Constraint; `canonicalize.py` deckt
  nur die kuratierte Militär-Alias-Map ab. Zur Constraint-Wahl: Composite-Property-
  *Uniqueness* **ist** in Neo4j möglich — Enterprise-only sind nur **Key-Constraints**
  (Uniqueness *plus* Existenzgarantie; das in `schemas.py` erwähnte NODE KEY). Wir wählen
  dennoch einen Single-Prop-`entity_key` (s. 2.4) — nicht weil Composite unmöglich wäre,
  sondern wegen **einfacher Writer-Semantik** und unzweideutigem Single-Property-Relation-
  Matching; er wirkt als Pseudo-Node-Key.

---

## 2. Scope

**In Scope:** Geo-Connectivity (Events + Incidents), Edge-Dedup, Entity-Integrität,
Mention-Noise — jeweils **Forward-Fix** (Nachwuchs verhindern) **und** **Backfill/Cleanup**
(Bestand heilen).

**Out of Scope (eigene Spec):**
- Actor-Graph-Enrichment: Relationen aus RSS/Think-Tank-Fulltext extrahieren.
- Stadt-Präzises Geocoding für RSS-Events (dieser Spec: nur Country-Centroid).
- Re-Ingestion/Re-Extraktion bestehender RSS-Events zur Geo-Anreicherung.

---

## 3. Ansatz

**A — Idempotentes Migrations-Modul + Writer-Forward-Fixes (gewählt).**
Neues, getestetes `graph_integrity/`-Paket in `data-ingestion` mit re-runnable Jobs
(`report`, Geo-Backfills, Rel-Dedup, Entity-Merge, Noise-Cleanup) per CLI — gespiegelt am
bestehenden `nlm_ingest/migrate.py` + `BACKFILL_EXTRACTED_FROM`-Muster. Ergänzt um
Forward-Fixes in den Live-Writern, damit der bereinigte Zustand stabil bleibt.

- **B — nur Forward-Fix:** verworfen. Bestand (184k Events, 1.952 Incidents) bliebe kaputt.
- **C — Big-Bang Re-Ingestion:** verworfen. GPU-Tage, riskant, gegen Budget.

**Leitprinzip (durchgängig):** strikte Trennung **„Bestand heilen" (Phase 3)** vs.
**„Nachwuchs verhindern" (Phase 2)**. Forward-Fixes werden **vor** den Backfills
deployt, damit während/nach dem Backfill keine neuen Dubletten/Waisen entstehen.

**Querschnitts-Constraints (aus CLAUDE.md):**
- Kein LLM-generiertes Cypher auf dem Write-Path; nur deterministische, parameter-
  gebundene Templates.
- Read-Path bleibt READ-ONLY; alle Schreib-Jobs leben in `data-ingestion`.
- TDD: Tests zuerst (Red → Green → Refactor).
- Jeder Backfill: scoped, idempotent, re-runnable, mit `--dry-run`.

---

## 4. Phasen

> **Plan-Tranchen.** Der Implementierungsplan wird in **zwei Tranchen** geschnitten, um
> Risiko zu senken und den sichtbaren Globe-Win früh zu liefern:
> - **Tranche 1 — Report + Geo:** Phase 1 (`report`) · 2.1/2.2/2.3 (GDELT-/Incident-/RSS-
>   Geo-Forward-Fix) · 3.1/3.2 (Incident-/GDELT-Geo-Backfill) · Geo-Acceptance.
> - **Tranche 2 — Integrität:** 2.4/2.5 (entity_key + typisierte Relationen, Mention-
>   Stopliste) · 3.3/3.4/3.5 (Rel-Dedup, entity_key-Preflight+Merge, Noise-Cleanup) ·
>   Integritäts-Acceptance. Enthält die strikte entity_key-Reihenfolge (3.4) gekapselt.
>
> Der `report` (Phase 1) entsteht in T1 und wird in T2 um die Integritäts-Metriken erweitert.

### Phase 1 — Measure / Report (zuerst)

Ein deterministischer Read-only-Befehl `graph_integrity report`, der die Acceptance-
Baseline liefert und nach jedem Schritt re-runnable ist:

- **Orphan-Rate** pro Label (`MATCH (n:L) WHERE NOT (n)--()`).
- **Geo-Coverage:** Events/Incidents mit `OCCURRED_AT → :Location` / total.
- **Duplicate-Relation-Ratio:** pro `(startNode, type, endNode)` Gruppen mit `count > 1`.
- **Duplicate-Entity-Groups:** Entities, die nach Normalisierung (`canonicalize._normalize`)
  auf denselben Key fallen, aber getrennte Knoten sind.
- **Mention-Noise:** Top-N Entities nach MENTIONS-Grad, markiert gegen die Stopliste.

Output: JSON + Tabellen-Print. Dient als **Vorher/Nachher-Vergleich** in Phase 4.

**Acceptance P1:** `report` läuft read-only, liefert alle fünf Metriken, reproduzierbar.

---

### Phase 2 — Forward-Fixes (Nachwuchs verhindern)

#### 2.1 GDELT-Event-Geo durch den Contract ziehen
Die kanonische Pipeline muss Geo **persistieren**, sonst ist jeder Backfill Wegwerf-Arbeit.
Kette: `filter` (Geo-Spalten behalten) → `transform.canonicalize_events` (Geo selektieren)
→ `schemas.GDELTEventWrite` (Geo-Felder ergänzen) → `polars`-Parquet-Schema (Geo-Felder)
→ `writers/neo4j_writer.py` (`MERGE (:Location)` + `MERGE (ev)-[:OCCURRED_AT]->(l)`).
Geo-Quelle: `action_geo_*` (Aktionsort des Events). Properties `name=action_geo_fullname`,
`country=action_geo_country_code`, `lat`, `lon`, `geo_basis="gdelt_actiongeo"`.
Events ohne `action_geo_lat` (GDELT lässt das zu) bleiben bewusst ungeolokalisiert.

> **Location-Identität (verbindlich, einheitlich für ALLE Schreibpfade).** Eine
> Location wird über die Property **`loc_key`** ge-MERGEt (Single-Prop-UNIQUE-Constraint),
> niemals über `name` (das verursacht genau die Dubletten, die wir bei Entities beheben).
> Deterministische Ableitung pro `geo_basis`:
> - `gdelt_actiongeo`: `loc_key = build_location_id(feature_id, country_code, fullname)`
>   (= `gdelt:loc:<feature_id>`, Fallback `gdelt:loc:<cc>:<slug>`).
> - `country_centroid`: `loc_key = "centroid:<iso2>"` (genau ein Knoten pro Land).
> - `incident_report`: `loc_key = "incident:<slug(location)>"` falls Ortsname vorhanden,
>   sonst `"geo:<lat|3>,<lon|3>"` (auf 3 Nachkommastellen gerundet).
> Die 65 Bestands-Location-Knoten (per `name` gemerged) bekommen im Backfill (3.x) ein
> `loc_key` rückgefüllt (`name:<slug(name)>`), bevor der Constraint angelegt wird.
> `name`/`country`/`lat`/`lon`/`geo_basis` bleiben beschreibende Properties.

**Acceptance 2.1:** Neue GDELT-Slices erzeugen Events **mit** `OCCURRED_AT`; Parquet-
Contract enthält Geo-Felder; Writer-Test prüft Location (per `loc_key`) + Edge.

#### 2.2 Incident-Writer
`INCIDENT_UPSERT` (in `backend/app/cypher/incident_write.py`) erweitern: zusätzlich
`MERGE (l:Location {...})` aus den vorhandenen `lat`/`lon`/`location` +
`MERGE (i)-[:OCCURRED_AT]->(l)` mit `l.geo_basis="incident_report"`. Parameter-gebunden,
idempotent.

**Acceptance 2.2:** Ein neu geschriebener Incident ist **nicht** verwaist (`OCCURRED_AT`
vorhanden).

#### 2.3 RSS-Event-Geo via Country-Centroid (coarse)
Gebündelte statische Tabelle **ISO-3166-Country → Zentroid** (~250 Zeilen, im Repo, keine
externe Dep). Im RSS-Write-Path: aus `location.country` der Extraktion den Zentroid
auflösen, `MERGE (:Location)` + `OCCURRED_AT` mit **`geo_basis="country_centroid"`** und
`geo_precision="country"`, damit UI/Analytik Länderzentrum nie mit Stadtpräzision
verwechselt. Mehrdeutige/fehlende Country → kein Edge (ehrlich leer).

**Event↔Location-Zuordnung:** Die Extraktion liefert `locations` auf **Dokument-Ebene**,
nicht pro Event. Regel: ein Event erbt die Country seines Quell-Dokuments; bei mehreren
extrahierten Locations gewinnt die **erste mit gesetztem Country** (Extraktor-Reihenfolge =
Salienz). Dokument ohne Country → Event bleibt ungeolokalisiert.

**Acceptance 2.3:** Neues RSS-Event mit Country bekommt `OCCURRED_AT` auf eine als
`country_centroid` markierte Location.

#### 2.4 Entity-Key + typisierte Relation-Endpunkte (behebt P3 + P4-Constraint)
- Deterministischer `entity_key = canonical_name + "|" + canonical_type` als Property auf
  jedem `Entity`. **Single-Prop-UNIQUE-Constraint** auf `entity_key` (Community-fähig,
  umgeht das NODE-KEY-Limit aus `schemas.py`).
- `UPSERT_ENTITY` MERGEt auf `{entity_key}` und setzt `name`/`type`/`aliases`.
- **Alle** `RELATION_TEMPLATES` matchen Endpunkte auf `{entity_key}` (statt nur `name`) →
  kein Fanout mehr bei namensgleichen Entities unterschiedlichen Typs.
- Der Relation-Caller mappt `(source,target)` **vor** dem Write über `canonicalize_entity`
  auf denselben `entity_key`.

> **⚠️ Reihenfolge-Blocker:** Der Writer-Switch (MERGE auf `entity_key`) darf **erst
> live gehen, nachdem der `entity_key`-Preflight (3.4 Schritt 1) auf ALLEN Bestands-
> Entities gelaufen ist**. Sonst findet der neue Writer die bestehenden, `entity_key`-losen
> Entities nicht und legt Dubletten an — genau das Problem, das wir beheben. Die
> verbindliche Ausführungsreihenfolge steht in 3.4. Das UNIQUE-Constraint kommt zuletzt.

**Acceptance 2.4:** Nach Preflight MERGEt der Write-Path auf `entity_key` und trifft
bestehende Entities (kein neuer Dublettenknoten); ein Relation-Write trifft genau ein
Endpunkt-Paar; doppelter Write erzeugt keine zweite Kante. Constraint wird in 3.4 verifiziert.

#### 2.5 Mention-Noise-Stopliste
Kuratierte Stopliste (`FIRMS`, `NASA`, `NASA FIRMS`, …) im RSS/GDELT-Write-Path. Sie
blockiert **ausschließlich** `(:Document)-[:MENTIONS]->(:Entity)` für Boilerplate-Entities.
**Unangetastet:** `FROM_SOURCE`, `Source`-Knoten, jede Dokument-Provenienz — diese Namen
sind als Quelle/Attribution wertvoll, nur als Akteur-Mention sind sie Rauschen.

**Acceptance 2.5:** Neue Dokumente erzeugen keine MENTIONS auf Stoplisten-Entities;
Source-/Provenienz-Kanten unverändert.

---

### Phase 3 — Backfills / Cleanup (Bestand heilen)

Alle Jobs: `--dry-run` (zählt nur), scoped, idempotent, re-runnable.

#### 3.1 Incident-Geo-Backfill
Bestehende 1.952 Incidents: aus vorhandenen `lat`/`lon`/`location`
`MERGE (:Location)` + `OCCURRED_AT` (`geo_basis="incident_report"`). Reine Bestands-
heilung des in 2.2 etablierten Schemas.

#### 3.2 GDELT-Event-Geo-Backfill (definierte Rohdatenquelle)
**Quelle ist festgelegt:** Re-Fetch der rohen Export-Slices (nicht das geo-freie Parquet).
Slice-Liste aus den vorhandenen Parquet-Partitionen
(`events/date=YYYYMMDD/{slice_id}.parquet` → `slice_id`). Pro Slice:
`http://data.gdeltproject.org/gdeltv2/{slice_id}.export.CSV.zip` laden, mit dem
bestehenden `polars_schemas`-Parser lesen, `event_id = build_event_id(global_event_id)`
bauen, **nur** für bereits in Neo4j vorhandene Events ohne Geo `MERGE (:Location)` +
`OCCURRED_AT` schreiben (`action_geo_*`, `geo_basis="gdelt_actiongeo"`).
Wiederverwendung des bestehenden Parser-/ID-Codes; kein neuer Download-Pfad nötig außer
der Slice-URL. Rate-Limit-bewusst, resumebar (State pro Slice).

#### 3.3 Relationship-Dedup (dedizierte Query)
**Abgrenzung:** Die bestehende `migrations/neo4j_duplicate_merge.cypher` dedupliziert
Kanten nur als Seiteneffekt von `apoc.refactor.mergeNodes(..., mergeRels:true)` — reine
Parallelkanten bleiben unberührt. Daher **eigene** Query (Muster der Migration
wiederverwenden, **nicht** als Lösung).

**Scope-Allowlist (kritisch):** Dedup läuft **ausschließlich** über die Actor-Relation-
Typen `ALLIED_WITH, SUPPLIES_TO, COMPETES_WITH, MEMBER_OF, OPERATES_IN, TARGETS, COMMANDS,
NEGOTIATES_WITH, SANCTIONS`. **Nicht** angefasst werden Beobachtungs-/Mengen-semantische
Kanten wie `SPOTTED_AT` (Aircraft→Location, je Sichtung eine legitime Kante), `OCCURRED_AT`,
`MENTIONS`, `ABOUT`, `FROM_SOURCE`, `DESCRIBES` — ein globales `(start,type,end)`-Dedup
würde dort echte Mehrfachbeobachtungen zerstören.

Pro `(startNode, type, endNode)` Gruppe (nur Allowlist-Typen) mit `count > 1` eine Kante
als Survivor behalten, Properties mergen (`confidence = max`, `first_seen = min`,
`last_seen = max`, `evidence = union`), Rest löschen. Idempotent (zweiter Lauf findet keine
Gruppen mehr).

#### 3.4 entity_key-Preflight + kuratierte Entity-Merges (strikte Reihenfolge)

Diese Schritte haben eine **verbindliche Ausführungsreihenfolge**, die die naive
Phasen-Folge bewusst durchbricht (Preflight ist ein Backfill, läuft aber **vor** dem
Forward-Fix 2.4). Single-Workstation-Ablauf: Ingestion stoppen → Schritte 1–5 → Ingestion
wieder an.

1. **`canonicalize.py` erweitern** um die kuratierten Country/Location-Einträge
   (`ukraine`→`Ukraine` etc.) — Code-Change, ohne den der Preflight die Dubletten nicht auf
   denselben Key bringt. **Kein** blindes Lowercase-Merge („Name != Identity").
2. **entity_key-Preflight:** `entity_key = canonicalize_entity(name,type)` für **alle** ~20k
   Bestands-Entities berechnen und als Property setzen. Kuratierte Dubletten teilen sich
   danach denselben `entity_key`.
3. **Kuratierter Merge:** Knoten mit identischem `entity_key` via `apoc.refactor.mergeNodes`-
   Muster kollabieren (Properties/Aliases/Relationen zusammenführen).
4. **Writer-Switch live nehmen** (2.4): ab jetzt MERGEt der Write-Path auf `entity_key` und
   trifft die bereinigten Bestandsknoten.
5. **UNIQUE-Constraint** auf `entity_key` anlegen (zuletzt — vorher würde er an
   Bestandskollisionen brechen). Analog: `loc_key`-UNIQUE-Constraint erst nach
   Location-`loc_key`-Rückfüllung (s. 2.1 / Risiken).

#### 3.5 Mention-Noise-Cleanup
Bestehende `MENTIONS`-Kanten auf Stoplisten-Entities löschen. Stoplisten-Entities, die
danach **verwaist** sind, optional entfernen — aber nur, wenn keine `FROM_SOURCE`-/
Provenienz-Kante daran hängt.

---

### Phase 4 — Acceptance

Konkrete Vorher/Nachher-Metriken via `graph_integrity report` (Phase 1):

| Metrik | Ist (2026-06-14) | Ziel |
|--------|------------------|------|
| Event Geo-Coverage | 0,28 % | GDELT-Events mit `action_geo` ~vollständig; RSS-Events mit Country verortet |
| Incident-Orphans | 1.952 | **0** |
| Actor-Edge-Dup-Ratio | ~63 Kanten / ~12 Fakten | 1 Kante pro `(start,type,end)` |
| Entity-Dup-Groups (kuratiert) | > 0 | 0 für die kuratierte Liste |
| MENTIONS auf Stopliste | FIRMS 49k, NASA 42k | 0 |

**Zusätzlich verpflichtend:**
- **Idempotenz-Test:** jeder Backfill zweimal laufen → zweiter Lauf ist No-Op (0 changes).
- **Dry-run:** jeder Backfill unterstützt `--dry-run` mit korrekter Zählung.
- **Rollback-Hinweis:** Pre-Backfill `neo4j-admin database dump` (oder Volume-Snapshot);
  jeder Cleanup-Job dokumentiert, was er löscht. Edge-Dedup/Entity-Merge sind **nicht**
  trivial reversibel → Dump ist Pflicht vor Phase 3.3/3.4.

---

## 5. Komponenten & Dateien (Überblick)

**Neu:** `services/data-ingestion/graph_integrity/` — `report.py`, `geo_incident.py`,
`geo_gdelt.py`, `rel_dedup.py`, `entity_merge.py`, `mention_cleanup.py`, `cli.py`,
`country_centroids.py` (statische ISO→Zentroid-Tabelle), Tests.

**Geändert (Forward-Fix):**
- `gdelt_raw/filter.py`, `transform.py`, `schemas.py`, `polars_schemas.py` (Parquet-
  Contract + Geo behalten), `writers/neo4j_writer.py` (Location + OCCURRED_AT).
- `backend/app/cypher/incident_write.py` (Location + OCCURRED_AT).
- `data-ingestion/pipeline.py` + `nlm_ingest/write_templates.py` (`entity_key`,
  typisierte Relation-Endpunkte, Country-Centroid, Stopliste).
- `data-ingestion/canonicalize.py` (kuratierte Country/Location-Einträge).

---

## 6. Risiken & offene Punkte

- **GDELT-Re-Fetch-Verfügbarkeit:** historische Export-Slices sind öffentlich, aber
  einzelne sehr alte Slices könnten fehlen → Backfill muss fehlende Slices überspringen
  und im Report ausweisen (kein harter Abbruch, keine stille Truncation).
- **Location-Identität:** In 2.1 verbindlich auf `loc_key` festgelegt (einheitlich für alle
  Schreibpfade). Restrisiko: der bestehende `LINK_EVENT_LOCATION` (merged auf `name`) muss
  auf `loc_key` umgestellt **und** die 65 Bestandsknoten rückgefüllt werden, **bevor** der
  UNIQUE-Constraint greift — andernfalls Constraint-Abbruch an Bestandskollisionen.
- **entity_key-Migration-Reihenfolge** (3.4): Constraint erst nach Merge — sonst Abbruch.
- **Stopliste-Pflege:** bewusst klein/kuratiert halten; Erweiterung nur mit Beleg, dass
  ein Name Boilerplate und kein echter Akteur ist.

---

## 7. Bezug zu bestehender Arbeit

- Knüpft an `canonicalize.py` + die Entity-Resolution-Policy an („Name != Identity",
  nur kuratierte Merges).
- P1-Geo schließt die im Temporal-Tracking dokumentierte Lücke (`geo_events=0`, Globe-
  Dots leer) — Slice-1-Geo-Backfill wird hiermit konkret.
- Out-of-Scope-Actor-Enrichment ist die natürliche Folge-Spec, sobald der Geo-/Integritäts-
  Unterbau steht.
