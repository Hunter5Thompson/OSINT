# Design: NotebookLM-Report-Integration in den Extract/Ingest-Pfad

**Status:** Approved (Brainstorming abgeschlossen 2026-05-31)
**Vorgänger:** [`2026-04-03-notebooklm-odin-ingestion-design.md`](2026-04-03-notebooklm-odin-ingestion-design.md)

## Kontext

`export.py` zieht inzwischen pro Notebook neben dem Podcast-Audio auch
*completed* Slide-Decks (PDF) und *completed* Reports (Markdown). Die Reports
landen aber nur auf der Platte — der NLM-Pipeline-Pfad
(`export → transcribe → extract → ingest`) verarbeitet ausschließlich das
Audio-Transkript. Reports sind damit toter Datenbestand.

Diese Story führt **Reports als vollwertige, eigenständige Extraktionsquelle**
durch den bestehenden Pfad: gleiche Qwen/Claude-Extraktion, Schreiben nach
Neo4j **und** Qdrant, mit erhaltener Quell-Herkunft (Provenance).

**Bewusst ausgeklammert (YAGNI):**
- **Slide-Decks/Vision/OCR** — NotebookLM-Slide-PDFs sind gerenderte Bild-Folien
  (0 Zeichen Textebene, 1 Bild/Seite). Das erfordert OCR/Vision und ist eine
  eigene spätere Story.
- **Dokument-Chunking / neue Retrieval-Strategie** — Embedding erfolgt pro Claim,
  nicht pro gechunktem Dokument. Chunking wird separat evaluiert.
- **Cross-Source-Claim-Dedup** über die bestehende `claim_hash`/MERGE-Semantik
  hinaus.

## Architektur-Überblick

```
load_sources(notebook) → [ExtractionSource(transcript), ExtractionSource(report), …]
        │  (pro Quelle, source_kind + stabile source_id)
        ▼
extract_with_qwen(source) → Extraction(source_kind, source_id)
        │
        ├─► Neo4j: Claim -[:EXTRACTED_FROM {source_kind, source_id}]-> Document
        └─► Qdrant odin_intel: 1 Point je Claim (UUIDv5-ID, source-spezifisch)
```

Eine Quelle ist die Einheit. Ein Notebook mit Audio + Report ergibt zwei
`Extraction`-Objekte mit unterschiedlicher Herkunft.

## Änderung 1: `nlm_ingest/schemas.py`

Neues Quell-Modell:

```python
class ExtractionSource(BaseModel):
    notebook_id: str
    source_id: str                                  # Artifact-ID; "transcript" fürs Audio-Transkript
    source_kind: Literal["transcript", "report"]
    text: str
```

`Extraction` erhält zwei Felder zur Herkunft, die durch den Ingest gereicht werden:

```python
class Extraction(BaseModel):
    ...
    source_kind: Literal["transcript", "report"]
    source_id: str
```

## Änderung 2: `nlm_ingest/sources.py` (neu)

```python
def load_sources(data_dir: Path, notebook_id: str) -> list[ExtractionSource]:
    """Alle auf der Platte vorhandenen, extrahierbaren Quellen eines Notebooks."""
```

- **Transkript:** `transcripts/{nid}.json` vorhanden → `ExtractionSource(source_kind="transcript", source_id="transcript", text=Transcript.full_text)`.
- **Reports:** je `notebooks/{nid}/report_{artifact_id}.md` → `ExtractionSource(source_kind="report", source_id=<artifact_id aus Dateiname>, text=<md>)`.

Klar abgegrenzte, isoliert testbare Einheit. Reihenfolge deterministisch
(Transkript zuerst, Reports nach `source_id` sortiert).

## Änderung 3: `nlm_ingest/extract.py`

`extract_with_qwen` und `review_with_claude` nehmen statt eines `Transcript`-
Objekts eine `ExtractionSource` (sie nutzen heute ohnehin nur `full_text` +
`notebook_id`):

```python
async def extract_with_qwen(source: ExtractionSource, metadata, client, vllm_url, vllm_model, prompt_version="v1") -> Extraction:
    # nutzt source.text[:16_000], source.notebook_id
    # setzt Extraction.source_kind = source.source_kind, source_id = source.source_id

async def review_with_claude(extraction, source: ExtractionSource, claude_client, claude_model) -> Extraction:
    # nutzt source.text
```

`extract_context` bleibt unverändert.

## Änderung 4: Extract-CLI (`nlm_ingest/cli.py`, `extract`)

- **Target-Auswahl** keyt auf *vorhandene Quell-Dateien* (`load_sources(...)` nicht
  leer) und `extract ∈ {pending, failed, running}` — **nicht** mehr hart auf
  `transcribe == "completed"`. Damit werden report-only Notebooks (Audio
  `skipped`) zu legitimen Extract-Targets.
- Iteriert pro Notebook über **alle** Quellen aus `load_sources`.
- Persistiert je Quelle **`extractions/{nid}.{source_id}.json`** (kollisionsfrei —
  mehrere Reports überschreiben sich nicht).
- **Idempotenz:** eine Quelle wird übersprungen, wenn ihre
  `extractions/{nid}.{source_id}.json` bereits existiert. So wird beim Retry kein
  bereits erfolgreich extrahierter Quell-Text erneut durch das LLM geschickt
  (Budget-schonend). Erzwungene Neu-Extraktion: Datei löschen.
- **Phasen-Aggregation (b1):** `extract` wird für das Notebook nur `completed`,
  wenn für **alle** entdeckten Quellen eine gültige Extraktionsdatei vorliegt.
  Schlägt mindestens eine Quelle fehl → Phase `failed` (retrybar); bereits
  geschriebene Quell-Dateien bleiben liegen und werden beim Retry per
  Idempotenz-Check übersprungen.

## Änderung 5: Export-Audio-Status (`nlm_ingest/export.py` + `export`-CLI)

`_export_audio` unterscheidet drei Ausgänge:

| Ausgang | Bedingung | Folge |
|---|---|---|
| `downloaded` | Audio-Artefakt da, Download ok | wie bisher |
| `absent` | `list_audio()` liefert **keinen Eintrag** (kein Audio-Artefakt jeglichen Status) | `transcribe = skipped` |
| `failed` | Audio-Artefakt vorhanden (auch `failed`-Status), aber Download/Stat schlägt fehl | `transcribe` bleibt `failed`/`pending` |

> **Abgrenzung:** Ein vorhandenes, aber selbst `failed`-Status-Audio-Artefakt zählt
> **nicht** als `absent` — es existiert ein Artefakt, also bleibt `transcribe` ein
> echter `failed`/`pending`-Zustand (regenerierbar). Solche Notebooks bleiben
> trotzdem nicht stecken: `extract` läuft über die vorhandenen Report-Quellen
> (Target keyt auf Quell-Dateien, nicht auf `transcribe`).

`export_all` liefert dazu ein Feld `audio_status: Literal["downloaded","absent","failed"]`
je Notebook. Die `export`-CLI setzt **`transcribe="skipped"` ausschließlich bei
`audio_status == "absent"`** (Korrektur 1/b2). Ein Download-Fehler darf niemals zu
`skipped` werden — sonst verschluckt die Pipeline echte Fehler.

`_export_audio` ruft dafür vor dem Download `client.artifacts.list_audio(nid)`,
um Existenz von Download-Fehler zu trennen.

## Änderung 6: `nlm_ingest/state.py` — Status `skipped` + DAG-Gating

**Status-Enum** erweitern um `skipped`:
`CHECK(status IN ('pending','running','completed','failed','skipped'))`.
`skipped` ist **terminal**. (SQLite-Migration siehe Abschnitt „Migration".)

**`validate_retry` von linear auf explizites DAG umstellen (P1#1).** Heute fordert
`validate_retry` *alle* `PHASE_ORDER[:idx]` als `completed`
([state.py:108](../../../services/data-ingestion/nlm_ingest/state.py)). Das ist
falsch: ein fehlgeschlagenes `transcribe` blockiert sonst `retry extract`/`retry
ingest` valider Report-Quellen. Stattdessen pro Phase explizite Vorbedingungen:

```python
PHASE_PREREQS = {
    "transcribe": ["export"],
    "extract":    ["export"],          # NICHT transcribe — Reports sind audio-unabhängig
    "ingest":     ["extract"],
}
# Vorbedingung erfüllt, wenn prereq-Status in {"completed", "skipped"}.
```

`transcribe` ist damit **keine** Vorbedingung für `extract`. Die Existenz einer
extrahierbaren Quelle wird zur Laufzeit über `load_sources(...)` geprüft (nicht im
DAG kodiert). `get_all_status`/Target-Filter behandeln `skipped` als terminal
(nicht ausstehend).

## Änderung 6b: Quell-Reconciliation im Export-Schritt (P1#2, P1#3)

Phasen-Target-Filter (`status ∈ {pending,failed,running}`) verarbeiten **neue
Quellen nach einem abgeschlossenen Lauf nicht** — kommt später ein Report dazu
oder wird Audio nachträglich erzeugt, bleibt `extract=completed` und die neue
Quelle versickert. Der Export-Schritt wird daher zum **Reconciler**.

Nach `export_all` pro Notebook (`reconcile_phases(db, data_dir, nid, audio_status, current_sources)` in `state.py`):

1. **Quell-Inventar bilden:** vorhandene Audio (`audio_status`) + Report-Artefakte
   (`source_id`s aus `notebooks/{nid}/report_*.md`).
2. **Neuer/zusätzlicher Report** (`source_id` ohne `extractions/{nid}.{source_id}.json`):
   `extract` und `ingest` → `pending` zurücksetzen. Die Idempotenz (Skip
   existierender Extraktionsdateien) verhindert Doppelarbeit an alten Quellen.
3. **Audio erscheint nach vorherigem `transcribe=skipped`:** `transcribe`
   (und nachgelagert `extract`, `ingest`) → `pending`.
4. **Keinerlei extrahierbare Quelle** (kein Audio-Artefakt **und** kein Report —
   z. B. Slide-only-Notebook, das per [export.py](../../../services/data-ingestion/nlm_ingest/export.py)
   nur wegen eines Slide-Decks registriert wurde): **`transcribe`, `extract` und
   `ingest` terminal auf `skipped`** (P1#3). Eine spätere Vision-Quelle setzt sie
   via Reconciliation wieder auf `pending`.

Reconciliation ist idempotent und setzt nur bei *tatsächlicher* Inventar-Änderung
zurück (kein Reset bei unverändertem Stand).

## Änderung 7: Graph-Write — Provenance (`nlm_ingest/write_templates.py`, `ingest_neo4j.py`)

`LINK_CLAIM_DOCUMENT` trägt die Herkunft **im MERGE-Pattern** (nicht via `SET`),
damit Audio- und Report-Herkunft desselben Claims als getrennte Kanten
koexistieren (kein last-write-wins):

```cypher
MATCH (c:Claim {statement_hash: $statement_hash})
MATCH (d:Document {notebook_id: $notebook_id})
MERGE (c)-[r:EXTRACTED_FROM {source_kind: $source_kind, source_id: $source_id}]->(d)
```

`_build_statements(extraction, source_name)` reicht `extraction.source_kind` und
`extraction.source_id` durch. `UPSERT_DOCUMENT.type` wird notebook-neutral
(`"notebooklm"` statt `"notebooklm_podcast"`), da der Document-Knoten das
Notebook repräsentiert; die Quelle steht auf der Kante.

> **Write-Path-Disziplin:** weiterhin nur deterministische Templates,
> Parameter-Binding, keine LLM-generierten Cypher. Änderung vom
> **graph-rag-auditor** gegenprüfen lassen.

## Änderung 8: Qdrant-Write für NLM (neu) — `nlm_ingest/ingest_qdrant.py` (neues Modul)

Der NLM-Ingest schreibt heute **nur** Neo4j. Diese Änderung ergänzt einen
Embed→`odin_intel`-Schritt für **beide** Quellen (Transkript + Report), damit
NLM-Inhalte im RAG-Read-Pfad sichtbar werden.

**Eigenes Modul `ingest_qdrant.py`** (P2#5) — saubere Trennung vom Neo4j-Writer
(`ingest_neo4j.py` bleibt graph-fokussiert). Der Ingest-CLI ruft beide.

**Collection-Preflight (Pflicht, P2#5):** vor dem ersten Write
`validate_collection_schema(...)` aufrufen
([qdrant_doctor/schema.py](../../../services/data-ingestion/qdrant_doctor/schema.py)),
analog zu `_ensure_collection` in
[feeds/base.py:35](../../../services/data-ingestion/feeds/base.py). Schema-Drift
wird so beim Write erkannt, nicht erst zur Query-Zeit.

**Einheit: pro Claim.** Je Claim ein Point:

- **Point-ID:** `uuid5(NAMESPACE, f"{notebook_id}|{source_kind}|{source_id}|{claim_hash}")`
  — deterministisch (Retries idempotent), **quell-spezifisch** (identischer Claim
  aus Report und Transkript bleibt als zwei Evidenz-Points sichtbar, keine
  Provenance-Überschreibung). `NAMESPACE` = projektfeste UUID-Konstante.
- **Vektor:** bestehendes TEI-`/embed` (1024-dim) auf `claim.statement`.
- **Payload** (schema-kompatibel zum bestehenden `odin_intel`; der Read-Pfad liest
  `title/source/content` in
  [qdrant_search.py](../../../services/intelligence/agents/tools/qdrant_search.py)
  und `entities` für den Graph-Context in
  [retriever.py:178](../../../services/intelligence/rag/retriever.py)):

```python
{
  "title":         <notebook-title>,
  "source":        <source_name>,
  "region":        "N/A",                       # P2#6: explizit "N/A", NICHT None
                                                 # (r.get("region","N/A") defaultet nur bei fehlendem Key)
  "content":       claim.statement,
  "entities":      [{"name": n} for n in claim.entities_involved],  # P2#6: Graph-Context-Injection
  "notebook_id":   extraction.notebook_id,
  "source_kind":   extraction.source_kind,
  "source_id":     extraction.source_id,
  "claim_type":    claim.type,
  "claim_hash":    <claim_hash>,                # zusätzlich im Payload
  "content_hash":  <claim_hash>,                # P2#6: konsistent mit base._build_point
  "ingested_at":   <iso>,                       # P2#6
  "ingested_epoch": <ts>,                       # P2#6 (optional, wie RSS-Pfad)
}
```

- **Keine** neue Retrieval-Strategie, **kein** Chunking, **kein** Cross-Source-Dedup.
- Abgelehnte Claims (`confidence == 0` nach Claude-Review) werden — wie beim
  Neo4j-Write — nicht embedded.
- TEI-/Qdrant-Konfiguration aus `config.py` (`qdrant_url`, `qdrant_collection`,
  TEI-Embed-URL); keine hardcoded URLs.

## Änderung 9: Ingest-CLI (`nlm_ingest/cli.py`, `ingest`)

- Liest **alle** `extractions/{nid}.{source_id}.json` eines Notebooks (Glob), nicht
  mehr nur `{nid}.json`.
- Schreibt je Extraction nach Neo4j **und** Qdrant.
- **Phasen-Aggregation (b1):** `ingest` wird nur `completed`, wenn **alle**
  Extraktionsdateien des Notebooks erfolgreich (Neo4j + Qdrant) geschrieben
  wurden; sonst `failed` (retrybar).

## Migration (P1#4)

Es existieren bereits lokale Daten aus dem alten audio-only Pfad. Eine
deterministische, idempotente, einmalige Migration ist Teil dieser Story:

1. **SQLite-Status-Enum.** SQLite kann einen `CHECK` **nicht** per `ALTER`
   erweitern → **Tabellen-Rebuild in einer Transaktion**:
   neue `phase_status`-Tabelle mit erweitertem `CHECK` anlegen, Daten kopieren,
   alte droppen, umbenennen. In einer Transaktion, idempotent (nur wenn der alte
   `CHECK` erkannt wird).
2. **Alte Extraktionsdateien.** `extractions/{nid}.json` →
   `extractions/{nid}.transcript.json` umbenennen und im JSON `source_kind="transcript"`,
   `source_id="transcript"` backfillen (das `Extraction`-Modell bekommt die Felder
   als Pflicht; Alt-Dateien ohne sie sonst nicht ladbar).
3. **Alte Neo4j-Kanten.** Bestehende `EXTRACTED_FROM`-Kanten tragen keine
   Properties ([write_templates.py:58](../../../services/data-ingestion/nlm_ingest/write_templates.py)).
   Die neuen MERGEs mit `{source_kind, source_id}` würden sonst **parallele** Alt-
   und Neu-Kanten erzeugen. Deterministisches Backfill (eigenes Template, kein
   LLM-Cypher): vorhandene property-lose `EXTRACTED_FROM` auf
   `source_kind="transcript", source_id="transcript"` setzen.
4. **Migrationstest.** Test gegen ein **altes** DB-/Datei-Schema (Fixture mit
   alter `phase_status`-Tabelle, alter `{nid}.json`, property-loser Kante) →
   verifiziert Rebuild, Rename+Backfill, Kanten-Backfill und Idempotenz bei
   erneutem Lauf.

## Test-Strategie (TDD-Pflicht)

| Einheit | Test |
|---|---|
| `sources.load_sources` | findet Transkript + mehrere Reports, korrekte `source_kind`/`source_id`/`text` |
| `extract_with_qwen` | nimmt `ExtractionSource`, setzt `source_kind`+`source_id` auf `Extraction` (vLLM gemockt) |
| Extract-CLI Persistenz | mehrere Quellen → kollisionsfreie `extractions/{nid}.{source_id}.json` |
| Extract-Phase | `completed` nur wenn alle Quellen ok; Teilfehler → `failed` (retrybar) |
| Extract-Target | report-only Notebook (Audio `skipped`, kein Transkript) ist gültiges Target |
| `export` audio_status | `absent` → `transcribe=skipped`; `failed` bleibt `failed`/`pending` |
| `state` `skipped` | terminal + nicht-blockierend in `validate_retry` |
| `EXTRACTED_FROM` | Rel-Props `source_kind`+`source_id` im MERGE-Pattern; zwei Quellen → zwei Kanten |
| Qdrant-Point | `point_id` = UUIDv5 (quell-spezifisch), Payload inkl. `entities`/`content_hash`/`ingested_at`, `region="N/A"`, `claim_hash`, abgelehnte Claims raus |
| Qdrant-Preflight | `validate_collection_schema` wird vor dem Write aufgerufen (Mismatch → Abbruch) |
| Ingest-Phase | globbt mehrere Extraktionsdateien; `completed` nur bei Vollerfolg |
| **DAG** `validate_retry` | `retry extract` erlaubt bei `transcribe=failed`/`skipped` (export `completed`); `retry ingest` blockiert nur bei nicht-terminalem `extract` |
| **Reconciliation** | neuer Report nach Vollerfolg → `extract/ingest`→`pending`; Audio nach `transcribe=skipped` → `transcribe`→`pending`; kein Reset bei unverändertem Inventar |
| **Slide-only** | Notebook ohne Audio-Artefakt und ohne Report → `transcribe/extract/ingest` = `skipped` |
| **Migration** | Fixture mit altem Schema → Rebuild + `{nid}.json`-Rename+Backfill + Kanten-Backfill, idempotent bei Re-Run |

Tests verifizieren echtes Verhalten; externe Dienste (vLLM, TEI, Neo4j, Qdrant,
NotebookLM-Client) werden gemockt, nicht die zu testende Logik.

## Erfolgskriterien

1. Ein Notebook mit Audio **und** Report erzeugt zwei `Extraction`-Objekte; beide
   landen in Neo4j (mit getrennten `EXTRACTED_FROM`-Kanten) und in `odin_intel`
   (als getrennte Points).
2. Ein report-only Notebook (kein Audio-Artefakt) durchläuft
   `export(skipped) → extract → ingest` ohne in `transcribe` hängenzubleiben.
3. Ein Audio-**Download-Fehler** bleibt `failed`/`pending` — wird **nicht** zu
   `skipped`.
4. Report-Claims sind über `qdrant_search` im Read-Pfad auffindbar.
5. Retries sind idempotent (deterministische UUIDv5-Point-IDs; MERGE-Semantik im
   Graph); Teilfehler einer Quelle blockieren die erfolgreichen Quellen nicht.
6. Write-Path bleibt rein deterministisch (Templates, Parameter-Binding); kein
   Write im Read-Path.
7. **Retry-DAG** korrekt: ein Audio-Fehler blockiert weder `retry extract` noch
   `retry ingest` valider Report-Quellen.
8. **Reconciliation**: neue/nachträgliche Quellen (Report oder Audio) werden auch
   nach einem Vollerfolg erkannt und verarbeitet; keine versickerten Quellen.
9. **Quellenlose Notebooks** (Slide-only) hängen in keiner Phase — alle Phasen
   terminal `skipped`, reaktivierbar durch spätere Vision-Quelle.
10. **Migration** überführt Alt-Daten (SQLite-Schema, `{nid}.json`,
    property-lose `EXTRACTED_FROM`) deterministisch und idempotent.

## Betroffene Dateien

- `nlm_ingest/schemas.py` (ExtractionSource, Extraction-Felder)
- `nlm_ingest/sources.py` (neu)
- `nlm_ingest/extract.py` (Signatur-Refactor)
- `nlm_ingest/export.py` (audio_status: absent/failed/downloaded via `list_audio`)
- `nlm_ingest/state.py` (Status `skipped`, DAG-`validate_retry`, `reconcile_phases`)
- `nlm_ingest/write_templates.py` (`LINK_CLAIM_DOCUMENT` Rel-Props, Document-Type, Kanten-Backfill-Template)
- `nlm_ingest/ingest_neo4j.py` (Provenance durchreichen)
- `nlm_ingest/ingest_qdrant.py` (neu — Embed→odin_intel, Preflight)
- `nlm_ingest/migrate.py` (neu — SQLite-Rebuild, Datei-Rename+Backfill, Neo4j-Kanten-Backfill)
- `nlm_ingest/cli.py` (`export`-Reconciliation, `extract`/`ingest`-Phasenlogik, Migrationsaufruf)
- `tests/` (neue/erweiterte Tests je Einheit inkl. Migrationstest)
