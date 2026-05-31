# Slice 1 — Minimal Viable Evidence (Design Spec)

**Datum:** 2026-05-31
**Branch:** `feature/TASK-014c-evidence-contract`
**Erfüllt:** TASK-014 Teil C (Data Lineage)
**Nordstern:** `docs/superpowers/specs/2026-05-03-fusion-core-design.md` §5.1 (volles SourceRef-Modell). Dieser Slice baut den kleinsten *vollständigen* Provenienz- und Quellenkritik-Contract als Teilmenge davon — vorwärtskompatibel um optionale Felder erweiterbar.

## 1. Motivation

ODIN-Lageberichte sind oberflächlich, weil dem Synthese-Schritt jede *Quellenkritik* fehlt:

- `sources_used` ist nur die de-duplizierte **Tool-Namensliste** (`graph/state.py:31`, `graph/workflow.py:160`) — keine echten Quellen.
- Die Qdrant-Collection `odin_intel` wird von ≥6 heterogenen Write-Pfaden befüllt, jeder mit eigenem Payload-Shape und **ohne einheitlichen `source_type`-Diskriminator**.
- Der Retriever reicht Payloads roh durch (`rag/retriever.py:117`, `{"score": ..., **payload}`).
- `graph/models.py:36` hat ein `credibility_score`-Feld (default `0.5`), das **nie gesetzt** wird.
- Pro Treffer erreichen nur ~300 Zeichen Exzerpt die Synthese (`agents/tools/qdrant_search.py:11`).

Leitprinzip (Dijkstra): *Simplicity is a prerequisite for reliability.* Einfachheit heißt hier **minimale Zahl impliziter Annahmen**, nicht minimale Zahl geänderter Dateien.

## 2. Scope

**In Scope:**
- Kanonischer Provenienz-**Write-Contract** (nur Fakten) für aktive Qdrant-Writer.
- Read-seitiger **Normalisierungs-Adapter** + zentrale **Credibility-Registry** (Policy) im Intelligence-Service.
- `SourceRef` / `EvidenceItem` Pydantic-Modelle.
- Deterministisches **Evidence Pack** mit maschinenlesbarer Referenz pro Treffer.
- `sources_used: list[str] → list[SourceRef]`.
- Exzerpt 300 → 700 Zeichen.
- Tests (TDD).

**Explizit Out of Scope (spätere Slices / vorwärtskompatibel ergänzbar):**
- Bestandsmigration / Backfill alter Qdrant-Punkte.
- Automatische **Korroboration** & Widerspruchserkennung → Slice 2.
- **Spark-Synthese** (separates Schreibmodell) → Slice 3.
- Frontend-Lineage-Ansicht.
- Volles fusion-core-14-Feld-Modell (`external_id`, `feed_id`, `license`, `payload_hash`, `classification`).
- Lange Provider-Override-Liste.
- Auto-Recency-Bewertung bei fehlendem `published_at`.

## 3. Write-Contract — nur Fakten

### 3.1 Sprachneutrale Contract-Datei (Single Source of Truth)

`contracts/qdrant-provenance-v1.json`:

```json
{
  "required": ["source_type", "provider", "ingested_at"],
  "optional": ["published_at"]
}
```

- **Beide** Service-Test-Suites validieren gegen diese Datei. **Produktionscode importiert sie nicht** → Docker-Builds bleiben unabhängig, Drift zwischen Producer (data-ingestion) und Consumer (intelligence) fällt im CI auf.
- *Kein* Shared-Package — für vier Felder verfrüht.
- *Kein* `credibility_score` im Payload (das ist read-seitige Policy, siehe §5.2).

### 3.2 Felder

| Feld | Pflicht | Semantik |
|---|---|---|
| `source_type` | ja | eines von `rss \| telegram \| gdelt \| notebooklm \| dataset` |
| `provider` | ja | **kanonische ID** (kein Anzeigename) — z.B. `reuters.com`, `usgs.gov`, `firms.modaps.eosdis.nasa.gov`, `telegram:rybar`, `notebooklm:rand` |
| `ingested_at` | ja | Ingestions-Zeitpunkt (existiert bereits) |
| `published_at` | optional | Veröffentlichungszeit der Primärquelle; `None` wenn unbekannt. **Nie** mit `ingested_at` vermischen. |

`source_id`: deterministische Regel — stabiler Hash aus `(source_type, provider, url)` bzw. stabiler externer ID. (Exakte Form in Plan-Phase.)

### 3.3 Injektionspunkte (vier — RSS ist eigenständig)

1. **`feeds/base.py::BaseCollector._build_point` (Z. 109)** — deckt alle `BaseCollector`-Subklassen ab (FIRMS, OFAC, PortWatch, USGS, EONET, GDACS, HAPI, NOAA, UCDP, Telegram, …). Der Helper **validiert + normalisiert** die vom Collector gelieferten Fakten — er **rät nicht**. Jeder Collector liefert `source_type` + `provider` (+ `published_at` falls vorhanden) selbst.
2. **`feeds/rss_collector.py::_process_feed`** — `RSSCollector` (Z. 89) ist **kein** `BaseCollector`-Subclass; eigenständiger Qdrant-Upsert. Jede kuratierte Feed-Definition (`rss_collector.py:26+`) bekommt eine feste kanonische `provider`-ID; `published_at` aus `entry.published`. `source_type="rss"`.
3. **`nlm_ingest/ingest_qdrant.py::build_claim_points`** — `source_type="notebooklm"`, `provider="notebooklm:<notebook>"`. NLM ist **Transformationspfad, keine Primärquelle** → konservativ bewertet (§5.2).
4. **`gdelt_raw/writers/qdrant_writer.py`** — `source_type="gdelt"` bleibt Herkunft des Datensatzes; `provider` = Ursprungsdomain falls verfügbar, sonst `gdelt`. GDELT ist **Discovery/Aggregation, kein Publisher**.

> **Plan-Phase-Aufgabe:** Doppelpfade prüfen — nur tatsächlich aktive Writer anfassen. `RSSCollector` nutzt `process_item` aus `pipeline.py` nur für Extraktion; der Qdrant-Upsert liegt in `rss_collector.py`.

## 4. Read-Side — Adapter (intelligence)

`rag/evidence.py`: `dict (Retriever-Treffer) → EvidenceItem`. Strikte Reihenfolge:

1. **Kanonische Felder lesen**, wenn vorhanden.
2. **Nur bei Fehlen** (Altbestand) kleine, *explizite* Legacy-Heuristik: bekannte Payload-Shapes matchen (`notebook_id` → `notebooklm`, `url`+`codebook_type` → `rss`, …). Setzt `provenance_inferred=True`.
3. **Wenn keine Shape matcht: `source_type="unknown"`** — nicht raten, wenn Evidenz fehlt.

Heuristiken bewusst klein halten.

## 5. Read-Side — Modelle & Policy (intelligence)

### 5.1 Modelle

```python
class SourceRef(BaseModel):
    source_id: str
    source_type: Literal["rss", "telegram", "gdelt", "notebooklm", "dataset", "unknown"]
    provider: str                       # kanonische ID
    display_name: str | None = None     # optional, NICHT scoring-relevant
    url: str | None = None
    published_at: datetime | None = None
    credibility_score: float = 0.5      # read-seitig aus Registry gefüllt
    provenance_inferred: bool = False

class EvidenceItem(BaseModel):
    source: SourceRef
    title: str
    excerpt: str
    relevance_score: float
```

- `ingested_at` gehört in den Write-Contract, aber **nicht** in `SourceRef` (solange nicht angezeigt/bewertet).
- `dataset` ist als Typ grob; für Slice 1 akzeptabel — `provider` differenziert `usgs.gov` / `firms…` / OFAC.

### 5.2 Credibility-Registry

`rag/credibility.py` — ausschließlich im Intelligence-Service (Policy von Datenpfad getrennt):

```python
TYPE_BASELINES = {
    "rss": 0.60,
    "telegram": 0.40,
    "gdelt": 0.50,        # Aggregator, kein Publisher
    "dataset": 0.80,
    "notebooklm": 0.60,   # Transformationspfad, konservativ
    "unknown": 0.30,
}
PROVIDER_OVERRIDES = {   # kurz halten; jeder Eintrag mit Begründung + Test
    "reuters.com": 0.85,
    "bbc.com": 0.80,
}

def credibility_score(source_type: str, provider: str) -> float:
    return PROVIDER_OVERRIDES.get(normalize_provider(provider), TYPE_BASELINES[source_type])
```

- Unbekannter Provider → `source_type`-Baseline.
- Kurze, eindeutig begründbare Override-Liste — sonst wird die Registry zur unprüfbaren Meinungsdatenbank.

## 6. Evidence Pack & Synthese-Verdrahtung

### 6.1 Format

Deterministisch, sortiert nach `relevance_score`, dedupliziert nach `content_hash`. Ersetzt die flache Text-Wurst in `agents/tools/qdrant_search.py`. Pro Treffer eine **maschinenlesbare Referenzzeile**:

```
[EVIDENCE source_id=... type=rss provider=reuters.com score=0.82]
Title: ...
Published: ... (oder "unbekannt")
Excerpt: ...
```

- Exzerpt: `RESULT_CONTENT_MAX_CHARS` 300 → **700**. **Nicht** konfigurierbar machen, bevor Messwerte es fordern. Top-5 ≈ 3.500 Zeichen Exzerpttext.

### 6.2 `sources_used`

`list[str] → list[SourceRef]`. Der Workflow **parst die `[EVIDENCE …]`-Zeilen** aus den Tool-Ergebnissen und rekonstruiert `SourceRef` — **kein contextvar / kein run-scoped Collector** (versteckte Seiteneffekt-Kopplung). Optional, falls die LangChain-Version es zuverlässig stützt: Tool-`artifact`; für Slice 1 ist das explizite serialisierte Format robuster.
Betroffen: `graph/state.py:31`, `graph/workflow.py:160`, `graph/nodes.py:33`.

### 6.3 Synthese-Prompt

Bekommt pro Treffer Provider + `credibility_score` + bei `provenance_inferred=True` einen `(Herkunft abgeleitet)`-Marker. **Recency-Ehrlichkeit:** `published_at=None` → der Bericht darf keine Aktualität behaupten.

## 7. Tests (TDD — zuerst rot)

- Normalisierung korrekt für **RSS, Telegram, NLM, GDELT, einen strukturierten Feed (FIRMS/USGS)**.
- Registry-Scoring: Override greift, unbekannt → Baseline, jeder Override hat einen Test.
- Legacy-Fallback setzt `provenance_inferred=True`; unbekannte Shape → `source_type="unknown"`.
- **Contract-Test je Service** gegen `contracts/qdrant-provenance-v1.json`.
- Evidence-Pack-Format deterministisch & parsebar; `sources_used` enthält echte `SourceRef`.

## 8. Erfolgskriterium

Messbar bessere Lageberichte: echte Quellen statt Tool-Namen, Provider/Datum/Score/längeres Exzerpt in der Synthese, eine zentrale Provider-Policy statt verstreuter Sonderlogik. **Erst messen** (10–20 feste OSINT-Fragen, Blindvergleich), dann Slice 2 (Korroboration) / Slice 3 (Spark-Synthese).

## 9. Betroffene Dateien (Anker)

**data-ingestion (Write):** `contracts/qdrant-provenance-v1.json` (neu), `feeds/base.py:109`, `feeds/rss_collector.py`, `nlm_ingest/ingest_qdrant.py`, `gdelt_raw/writers/qdrant_writer.py`, je Subclass-Collector (Fakten liefern).
**intelligence (Read):** `rag/evidence.py` (neu), `rag/credibility.py` (neu), `agents/tools/qdrant_search.py`, `graph/state.py:31`, `graph/workflow.py:160`, `graph/nodes.py:33`, `agents/synthesis_agent.py` (Prompt).
