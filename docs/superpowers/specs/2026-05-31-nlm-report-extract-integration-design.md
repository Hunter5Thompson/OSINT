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

## Änderung 6: `nlm_ingest/state.py` — Status `skipped`

- Status-Enum erweitern: `CHECK(status IN ('pending','running','completed','failed','skipped'))`
  (Mini-Migration: `ALTER`/Recreate je nach SQLite-Setup; idempotent).
- `skipped` ist **terminal** und in `validate_retry` **nicht-blockierend**: eine
  `skipped` Vorphase zählt wie erledigt, blockiert spätere Phasen also nicht.
- `get_all_status`/Target-Filter behandeln `skipped` nicht als ausstehend.

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

## Änderung 8: Qdrant-Write für NLM (neu) — `nlm_ingest/ingest_neo4j.py` bzw. neuer Writer

Der NLM-Ingest schreibt heute **nur** Neo4j. Diese Änderung ergänzt einen
Embed→`odin_intel`-Schritt für **beide** Quellen (Transkript + Report), damit
NLM-Inhalte im RAG-Read-Pfad sichtbar werden.

**Einheit: pro Claim.** Je Claim ein Point:

- **Point-ID:** `uuid5(NAMESPACE, f"{notebook_id}|{source_kind}|{source_id}|{claim_hash}")`
  — deterministisch (Retries idempotent), **quell-spezifisch** (identischer Claim
  aus Report und Transkript bleibt als zwei Evidenz-Points sichtbar, keine
  Provenance-Überschreibung). `NAMESPACE` = projektfeste UUID-Konstante.
- **Vektor:** bestehendes TEI-`/embed` (1024-dim) auf `claim.statement`.
- **Payload** (schema-kompatibel zum bestehenden `odin_intel`, das der Read-Pfad
  `qdrant_search` mit `title/source/region/content` liest):

```python
{
  "title":       <notebook-title>,
  "source":      <source_name>,
  "region":      None,                 # NLM hat keine Region; Read-Pfad defaultet "N/A"
  "content":     claim.statement,
  "notebook_id": extraction.notebook_id,
  "source_kind": extraction.source_kind,
  "source_id":   extraction.source_id,
  "claim_type":  claim.type,
  "claim_hash":  <claim_hash>,         # zusätzlich im Payload
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
| Qdrant-Point | `point_id` = UUIDv5 (quell-spezifisch), Payload-Felder, `claim_hash` im Payload, abgelehnte Claims raus |
| Ingest-Phase | globbt mehrere Extraktionsdateien; `completed` nur bei Vollerfolg |

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

## Betroffene Dateien

- `nlm_ingest/schemas.py` (ExtractionSource, Extraction-Felder)
- `nlm_ingest/sources.py` (neu)
- `nlm_ingest/extract.py` (Signatur-Refactor)
- `nlm_ingest/export.py` (audio_status: absent/failed/downloaded)
- `nlm_ingest/state.py` (Status `skipped` + Migration)
- `nlm_ingest/write_templates.py` (`LINK_CLAIM_DOCUMENT` Rel-Props, Document-Type)
- `nlm_ingest/ingest_neo4j.py` (Provenance durchreichen, Qdrant-Write)
- `nlm_ingest/cli.py` (`export`/`extract`/`ingest`-Phasenlogik)
- `tests/` (neue/erweiterte Tests je Einheit)
