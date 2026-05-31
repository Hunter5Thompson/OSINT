# Slice 1 - Minimal Viable Evidence (Design Spec)

**Datum:** 2026-05-31
**Branch:** `feature/TASK-014c-evidence-contract`
**Ziel:** TASK-014 Teil C (Data Lineage) nach Implementierung erfüllen.
**Nordstern:** `docs/superpowers/specs/2026-05-03-fusion-core-design.md` §5.1
(volles `SourceRef`-Modell). Dieser Slice baut den kleinsten vollständigen
Provenienz- und Quellenkritik-Contract als vorwärtskompatible Teilmenge.

## 1. Motivation

ODIN-Lageberichte sind oberflächlich, weil dem Synthese-Schritt Quellenkritik fehlt:

- `sources_used` ist nur die de-duplizierte Tool-Namensliste
  (`graph/state.py:31`, `graph/workflow.py:160`) - keine echten Quellen.
- Die Qdrant-Collection `odin_intel` wird von heterogenen Write-Pfaden befüllt,
  jeweils mit eigenem Payload-Shape und ohne einheitlichen `source_type`-Diskriminator.
- Der Retriever reicht Payloads roh durch
  (`rag/retriever.py:117`, `{"score": ..., **payload}`).
- `graph/models.py:36` hat ein `credibility_score`-Feld mit Default `0.5`, das
  nie gesetzt wird.
- Pro Qdrant-Treffer erreichen nur 300 Zeichen Exzerpt die Synthese
  (`agents/tools/qdrant_search.py:10`).

Leitprinzip (Dijkstra): *Simplicity is a prerequisite for reliability.*
Einfachheit heißt hier: minimale Zahl impliziter Annahmen, nicht minimale Zahl
geänderter Dateien.

## 2. Scope

**In Scope:**

- Kanonischer Provenienz-Write-Contract mit ausschließlich Fakten für aktive
  Qdrant-Writer.
- Read-seitiger Normalisierungs-Adapter und zentrale Credibility-Registry im
  Intelligence-Service.
- `SourceRef`- und `EvidenceItem`-Pydantic-Modelle.
- Deterministische, budgetierte Evidence Packs mit einer maschinenlesbaren
  JSON-Metadatenzeile pro vollständigem Trefferblock.
- Verwendung desselben Evidence-Serializers durch `qdrant_search`, `gdelt_query`
  und `rss_fetch`.
- `sources_used: list[str] -> list[SourceRef]` durch Intelligence-Service,
  Backend-API und Frontend-Typen.
- Kompatibilitätsprojektion von `SourceRef` auf bestehende
  `ReportMessage.refs: list[str]`.
- Maximale Exzerptlänge 300 -> 700 Zeichen.
- Tests nach TDD.

**Explizit Out of Scope:**

- Bestandsmigration oder Backfill alter Qdrant-Punkte.
- Automatische Korroboration und Widerspruchserkennung (Slice 2).
- Spark-Synthese als separates Schreibmodell (Slice 3).
- Neue Frontend-Lineage-Ansicht. Slice 1 ändert Typen und hält die bestehende
  kompakte Quellenanzeige funktionsfähig.
- Volles fusion-core-14-Feld-Modell (`feed_id`, `license`, `payload_hash`,
  `classification`).
- Lange Provider-Override-Liste.
- Automatische Recency-Bewertung bei fehlendem `published_at`.

## 3. Write-Contract - nur Fakten

### 3.1 Sprachneutrale Contract-Datei

`contracts/qdrant-provenance-v1.json` ist die einzige sprachneutrale Referenz:

```json
{
  "contract_version": 1,
  "required": ["source_type", "provider", "ingested_at"],
  "optional": ["published_at"],
  "source_types": ["rss", "telegram", "gdelt", "notebooklm", "dataset"]
}
```

- Beide Service-Test-Suites validieren gegen diese Datei.
- Produktionscode importiert die JSON-Datei nicht. Die Docker-Build-Kontexte
  bleiben unabhängig.
- Kein Shared-Package für vier Payload-Felder.
- Kein `credibility_score` im Payload: Das ist read-seitige Policy (§5.2).
- `unknown` ist kein erlaubter Write-Wert. Er existiert nur als ehrlicher
  Read-Fallback für Altbestand.

### 3.2 Felder

| Feld | Pflicht | Semantik |
|---|---|---|
| `source_type` | ja | eines von `rss \| telegram \| gdelt \| notebooklm \| dataset` |
| `provider` | ja | kanonische ID statt Anzeigename, z.B. `reuters.com`, `usgs.gov`, `firms.modaps.eosdis.nasa.gov`, `telegram:rybar`, `notebooklm:nb-123` |
| `ingested_at` | ja | Ingestions-Zeitpunkt |
| `published_at` | optional | Veröffentlichungszeit der Primärquelle; `None` oder fehlend, wenn unbekannt. Nie mit `ingested_at` vermischen. |

Der Write-Contract speichert Fakten. Er erzwingt weder eine Bewertung noch eine
Umdeutung von Event-Zeitpunkten zu Publikationszeitpunkten. Beispielsweise bleiben
USGS-`event_time` und EONET-`event_date` fachliche Event-Felder; sie werden nicht
als `published_at` ausgegeben.

### 3.3 Aktive Qdrant-Writer

Die Implementierung pflegt das Contract-Inventar explizit. Es gibt keinen
universellen Injektionspunkt für alle Writer.

**A. Writer über `feeds/base.py::BaseCollector._build_point`:**

- `feeds/firms_collector.py`
- `feeds/ucdp_collector.py`
- `feeds/usgs_collector.py`
- `feeds/ofac_collector.py`
- `feeds/hapi_collector.py`
- `feeds/noaa_nhc_collector.py`
- `feeds/portwatch_collector.py`

`_build_point()` validiert und normalisiert die vom Collector gelieferten
Provenienz-Fakten. Der Helper rät nicht.

**B. Aktive manuelle Qdrant-Writer:**

- `feeds/rss_collector.py::_process_feed`
- `feeds/telegram_collector.py::_embed_and_upsert`
- `feeds/eonet_collector.py::collect`
- `feeds/gdacs_collector.py::collect`
- `gdelt_raw/writers/qdrant_writer.py::build_payload`
- `nlm_ingest/ingest_qdrant.py::build_claim_points`

Diese Writer verwenden denselben kleinen data-ingestion-lokalen
Provenienz-Helper wie `_build_point()`, schreiben aber weiterhin ihre
fachspezifischen Payloads.

**C. Ausdrücklich nicht Teil dieses Write-Inventars:**

- `feeds/gdelt_collector.py` ist der alte DOC-API-Collector. Er ist nicht im
  Scheduler registriert und bleibt unberührt.
- `feeds/military_aircraft_collector.py` schreibt nach Neo4j, nicht nach Qdrant.
- TLE- und Hotspot-Updater sind keine Qdrant-Evidence-Writer.

### 3.4 Provider-Regeln

- RSS: Jede kuratierte Feed-Definition erhält eine feste kanonische
  `provider`-ID. Bei Google-News-Proxys ist das die kuratierte Ursprungsdomain,
  nicht `news.google.com`. `published_at` kommt aus dem geparsten Feed-Eintrag;
  fehlt es, bleibt der Wert `None` statt auf Ingestionszeit zurückzufallen.
- Telegram: `provider="telegram:<normalisierter_channel_handle>"`.
- GDELT raw: `source_type="gdelt"`; `provider` ist die Ursprungsdomain, falls
  vorhanden, sonst `gdelt`.
- NotebookLM: `source_type="notebooklm"`;
  `provider="notebooklm:<normalisierte_notebook_id>"`. NLM ist
  Transformationspfad, keine Primärquelle. `source_name` kann als Anzeigename
  erhalten bleiben.
- Strukturierte Feeds: kanonische Provider-ID der Datenquelle, z.B. `usgs.gov`,
  `gdacs.org`, `eonet.gsfc.nasa.gov` oder `firms.modaps.eosdis.nasa.gov`.

## 4. Read-Side - Adapter

`services/intelligence/rag/evidence.py` normalisiert einen Retriever-Treffer zu
einem `EvidenceItem`.

### 4.1 Strikte Reihenfolge

1. Kanonische Felder lesen, wenn vorhanden.
2. Nur bei Fehlen kleine explizite Legacy-Heuristiken für bekannte Payload-Shapes
   anwenden, z.B. `notebook_id -> notebooklm`,
   `telegram_channel -> telegram`, `source == "rss" -> rss`.
   Dann `provenance_inferred=True` setzen.
3. Wenn keine Shape matcht: `source_type="unknown"` und
   `provenance_inferred=True`. Nicht raten.

### 4.2 Exzerpt-Priorität

Der Adapter erzeugt ein Exzerpt deterministisch:

```text
content -> summary -> description -> title -> ""
```

Das Exzerpt wird auf maximal 700 Zeichen begrenzt.

### 4.3 Zeitnormalisierung

- Neues Payload: ausschließlich kanonisches `published_at` lesen.
- Legacy RSS und Telegram: bestehendes `published` darf als `published_at`
  normalisiert werden, weil es dort Publikationszeit bedeutet.
- Event-Zeitpunkte (`event_time`, `event_date`, `date_start`, `acq_date` usw.)
  bleiben Event-Zeitpunkte und werden nicht als `published_at` ausgegeben.
- `ingested_at` ist niemals Ersatz für `published_at`.

### 4.4 `source_ref_id`

Der neue Name `source_ref_id` vermeidet eine Kollision mit producer-lokalen
Feldern wie NLM-`source_id`.

Die ID wird read-seitig deterministisch gebildet:

```text
identity = erste nicht-leere Identität aus:
  1. bekanntem stabilen externen Schlüssel
     (z.B. gdelt doc_id, telegram_channel + telegram_message_id,
      notebook_id + source_kind + source_id, ucdp_id)
  2. kanonischer URL
  3. content_hash
  4. normalisiertem title + excerpt als Legacy-Letztausweg

source_ref_id =
  sha256("source-ref-v1\0" + source_type + "\0" + normalized_provider
         + "\0" + identity_kind + "\0" + identity_value)[:20]
```

Die External-ID-Auswahl ist eine kleine explizite Tabelle im Adapter. Der
Legacy-Letztausweg setzt immer `provenance_inferred=True`.

## 5. Read-Side - Modelle und Policy

### 5.1 Modelle

```python
class SourceRef(BaseModel):
    source_ref_id: str
    source_type: Literal["rss", "telegram", "gdelt", "notebooklm", "dataset", "unknown"]
    provider: str
    display_name: str | None = None
    url: str | None = None
    published_at: datetime | None = None
    credibility_score: float = 0.5
    provenance_inferred: bool = False

class EvidenceItem(BaseModel):
    source: SourceRef
    title: str
    excerpt: str
    relevance_score: float
    content_hash: str | None = None
```

- `ingested_at` gehört in den Write-Contract, aber nicht in `SourceRef`, solange
  es weder angezeigt noch bewertet wird.
- `content_hash` ist kein Teil der öffentlichen Quelle. Er dient nur der
  deterministischen Evidence-Deduplizierung.
- `dataset` ist als Typ grob; `provider` differenziert strukturierte Quellen.

### 5.2 Credibility-Registry

`services/intelligence/rag/credibility.py` enthält ausschließlich read-seitige
Policy:

```python
TYPE_BASELINES = {
    "rss": 0.60,
    "telegram": 0.40,
    "gdelt": 0.50,        # Aggregator, kein Publisher
    "dataset": 0.80,
    "notebooklm": 0.60,   # Transformationspfad, konservativ
    "unknown": 0.30,
}

PROVIDER_OVERRIDES = {   # kurz halten; jeder Eintrag mit Begründung und Test
    "reuters.com": 0.85,
    "bbc.com": 0.80,
}

def credibility_score(source_type: str, provider: str) -> float:
    return PROVIDER_OVERRIDES.get(
        normalize_provider(provider),
        TYPE_BASELINES[source_type],
    )
```

- Unbekannter Provider: Baseline seines `source_type`.
- Kurze, eindeutig begründbare Override-Liste.
- NotebookLM und GDELT werden nicht als Primärquellen aufgewertet.

## 6. Evidence Pack und Synthese-Verdrahtung

### 6.1 Verlustfreies Format

Jeder vollständige Evidence-Block beginnt mit genau einer kompakten
JSON-Metadatenzeile:

```text
[EVIDENCE] {"credibility_score":0.85,"display_name":"Reuters","provenance_inferred":false,"provider":"reuters.com","published_at":"2026-05-31T08:00:00+00:00","relevance_score":0.82,"source_ref_id":"4e1...","source_type":"rss","url":"https://..."}
Title: ...
Excerpt: ...
```

- JSON wird deterministisch mit sortierten Keys und kompakten Separatoren
  serialisiert.
- `relevance_score` und `credibility_score` sind getrennte Werte.
- Die Metadaten reichen aus, um `SourceRef` verlustfrei zu rekonstruieren.
- Titel und Exzerpt bleiben menschenlesbar für den ReAct-Agenten und die Synthese.

### 6.2 Budgetierung ohne kaputte Blöcke

`agents/tools/qdrant_search.py` hängt Evidence-Blöcke nach absteigendem
`relevance_score` an, solange der nächste Block vollständig in das
Tool-Output-Budget passt.

- Maximale Exzerptlänge pro Treffer: 700 Zeichen.
- Kein abschließendes `_clip_text()` über den zusammengesetzten Evidence-Pack.
- Kein halbierter JSON-Header und kein abgeschnittener Evidence-Block.
- Deduplizierung: `content_hash`, falls vorhanden; sonst `source_ref_id`.
- Graph-Kontext bleibt optional und wird erst nach vollständigen
  Evidence-Blöcken innerhalb seines eigenen Budgets ergänzt.
- `TOOL_OUTPUT_MAX_CHARS` steigt von 3.500 auf 6.500 Zeichen. Das Gesamtbudget
  schließt Evidence-Blöcke und Graph-Kontext ein.
- `GRAPH_CONTEXT_MAX_CHARS` bleibt 1.200 Zeichen. Graph-Kontext wird nur bis zum
  verbleibenden Gesamtbudget ergänzt; Evidence-Blöcke haben Vorrang.

### 6.3 Einheitlicher Serializer für Live-Tools

`qdrant_search`, `gdelt_query` und `rss_fetch` verwenden denselben
Evidence-Serializer.

- `qdrant_search`: normalisierte Qdrant-Treffer.
- `gdelt_query`: URL und Domain aus dem Live-Ergebnis. `seendate` bleibt
  GDELT-Beobachtungsmetadatum und wird nicht als `published_at` ausgegeben.
- `rss_fetch`: Feed-URL, Artikellink und `pubDate`; Provider aus der
  Artikeldomain, mit Feed-Domain als konservativem Fallback.
- Graph-Kontext bleibt abgeleiteter Kontext ohne `SourceRef`.

Damit erfassen `sources_used` auch Live-Evidenz, nicht nur Qdrant-Treffer.

### 6.4 `sources_used`

Der Workflow parst ausschließlich vollständige `[EVIDENCE] <json>`-Zeilen aus
Tool-Ergebnissen, rekonstruiert `SourceRef` und de-dupliziert nach
`source_ref_id`.

- Kein `contextvar`, kein run-scoped Collector.
- Kein stiller Rückfall auf Tool-Namen.
- Die Legacy-Pipeline liefert `sources_used=[]`, solange sie keine echte
  Evidence-Lineage besitzt; `"llm_knowledge"` wird nicht als Quelle ausgegeben.

Propagation:

```text
intelligence AgentState
-> intelligence /query JSON
-> backend IntelAnalysis
-> frontend IntelAnalysis
```

Die bestehende Berichtschat-Persistenz bleibt kompatibel:

```text
ReportMessage.refs: list[str] =
  de-duplizierte provider-IDs aus sources_used in Ergebnisreihenfolge
```

Die bestehende Frontend-Anzeige rendert weiterhin kompakte String-Referenzen.
Eine interaktive Lineage-Ansicht bleibt out of scope.

### 6.5 Synthese-Prompt

Der Synthese-Prompt erklärt:

- `credibility_score` ist Quellenverlässlichkeit, nicht Aussagewahrheit.
- `provenance_inferred=true` wird als `(Herkunft aus Legacy-Payload abgeleitet)`
  behandelt.
- `published_at=null` oder fehlend bedeutet: Aktualität nicht aus der Quelle
  ableitbar.
- `ingested_at` ist kein Publikationszeitpunkt.

## 7. Tests - TDD, zuerst rot

### 7.1 Data Ingestion

- Contract-Datei enthält Version, Pflichtfelder, optionale Felder und erlaubte
  Write-`source_type`-Werte.
- Lokaler Provenienz-Helper validiert Pflichtfelder und akzeptiert
  `published_at=None`.
- Repräsentative `_build_point()`-Nutzer schreiben kanonische Provenienz:
  FIRMS und USGS.
- Jeder aktive manuelle Qdrant-Writer schreibt kanonische Provenienz:
  RSS, Telegram, EONET, GDACS, GDELT raw und NLM.
- RSS-Feeddefinitionen besitzen kanonische Provider-IDs; Google-News-Proxys
  speichern die kuratierte Ursprungsdomain.
- Der alte `feeds/gdelt_collector.py` bleibt vom Scheduler ausgeschlossen.

### 7.2 Intelligence

- Read-Modell akzeptiert die Contract-`source_type`-Werte plus read-only
  `unknown`.
- Adapter normalisiert RSS, Telegram, NLM, GDELT raw und einen strukturierten
  Feed.
- Legacy-Fallback setzt `provenance_inferred=True`; unbekannte Shape ergibt
  `source_type="unknown"`.
- Exzerpt-Priorität ist `content -> summary -> description -> title -> ""`.
- Event- und Aggregator-Beobachtungszeitpunkte werden nicht als `published_at`
  ausgegeben.
- Registry: Overrides greifen, unbekannter Provider fällt auf Baseline zurück,
  jeder Override hat einen Test.
- `source_ref_id` ist deterministisch; producer-lokales NLM-`source_id` bleibt
  unverändert.
- Evidence-Pack-Format ist deterministisch und parsebar.
- Tool-Budgetierung gibt ausschließlich vollständige Evidence-Blöcke aus.
- Qdrant-, GDELT-Live- und RSS-Live-Tools erzeugen parsebare Evidence-Blöcke.
- Workflow sammelt echte `SourceRef` und keine Tool-Namen.

### 7.3 Backend und Frontend

- Backend-`IntelAnalysis.sources_used` akzeptiert `list[SourceRef]`.
- Berichtschat persistiert de-duplizierte Provider-IDs als bestehende
  `ReportMessage.refs: list[str]`.
- Frontend-`IntelAnalysis.sources_used` ist als `SourceRef[]` typisiert.
- Frontend projiziert `SourceRef[]` für die bestehende Berichtschat-Anzeige auf
  de-duplizierte Provider-IDs.

## 8. Erfolgskriterium

Nach Slice 1:

- Neue Qdrant-Punkte tragen explizite Provenienz-Fakten.
- Altbestand bleibt ohne Backfill lesbar und wird ehrlich als abgeleitet markiert.
- Synthese und API erhalten echte Quellen statt Tool-Namen.
- Quellenverlässlichkeit kommt aus einer zentralen read-seitigen Policy.
- Berichtschat bleibt ohne neue UI kompatibel.
- Ein Blindvergleich mit 10-20 festen OSINT-Fragen prüft die Berichtsqualität,
  bevor Slice 2 (Korroboration) oder Slice 3 (Spark-Synthese) beginnt.

## 9. Betroffene Dateien

**Repository-Contract:**

- `contracts/qdrant-provenance-v1.json` (neu)

**Data Ingestion - Write:**

- `services/data-ingestion/feeds/provenance.py` (neu)
- `services/data-ingestion/feeds/base.py`
- `services/data-ingestion/feeds/rss_collector.py`
- `services/data-ingestion/feeds/telegram_collector.py`
- `services/data-ingestion/feeds/eonet_collector.py`
- `services/data-ingestion/feeds/gdacs_collector.py`
- `services/data-ingestion/feeds/firms_collector.py`
- `services/data-ingestion/feeds/ucdp_collector.py`
- `services/data-ingestion/feeds/usgs_collector.py`
- `services/data-ingestion/feeds/ofac_collector.py`
- `services/data-ingestion/feeds/hapi_collector.py`
- `services/data-ingestion/feeds/noaa_nhc_collector.py`
- `services/data-ingestion/feeds/portwatch_collector.py`
- `services/data-ingestion/gdelt_raw/writers/qdrant_writer.py`
- `services/data-ingestion/nlm_ingest/ingest_qdrant.py`

**Intelligence - Read and synthesis:**

- `services/intelligence/rag/evidence.py` (neu)
- `services/intelligence/rag/credibility.py` (neu)
- `services/intelligence/agents/tools/qdrant_search.py`
- `services/intelligence/agents/tools/gdelt_query.py`
- `services/intelligence/agents/tools/rss_fetch.py`
- `services/intelligence/graph/state.py`
- `services/intelligence/graph/workflow.py`
- `services/intelligence/graph/nodes.py`
- `services/intelligence/agents/synthesis_agent.py`

**Backend and frontend - typed propagation without new UI:**

- `services/backend/app/models/intel.py`
- `services/backend/app/routers/intel.py`
- `services/backend/tests/unit/test_intel_router_reports.py`
- `services/frontend/src/types/index.ts`
- `services/frontend/src/pages/BriefingPage.tsx`
- `services/frontend/src/test/pages/briefingPage.test.tsx`
