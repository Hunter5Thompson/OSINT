# TASK-014: Intelligence Pipeline Hardening (Foundry Patterns)

## Service/Modul
services/intelligence/ + services/data-ingestion/

## Hintergrund
Drei architektonische Muster aus Palantir Foundry wurden als direkt transferierbar identifiziert
und adressieren konkrete Schwachstellen in der aktuellen Pipeline:

1. **Agent Control Plane** — Agents haben keine granularen Tool-Permissions → nicht deterministisch, schlecht testbar
2. **Write/Read Separation** — `indexer.py` liegt im Intelligence-Service, obwohl er ein Write-Path-Concern ist
3. **Data Lineage** — `sources_used: list[str]` enthält nur Source-Namen, keine Document-IDs → Analysen nicht reproduzierbar

---

## Akzeptanzkriterien

### Teil A — Agent Tool Sandboxing
- [ ] Jeder Agent bekommt eine explizite, abgeschlossene Tool-List:
  - `osint_agent`: `web_search`, `rss_fetch`, `gdelt_query` — kein Qdrant-Write, kein Direct-DB-Access
  - `analyst_agent`: `qdrant_search` — kein Web-Zugriff, kein Write
  - `synthesis_agent`: read-only — gibt `IntelAnalysis` als Proposal zurück, schreibt nichts
- [ ] LangGraph Interrupt vor jeder nicht-lesbaren Action (zukünftige Hotspot-Updates)
- [ ] Unit-Tests beweisen: `osint_agent` kann nicht `qdrant_search` aufrufen, `analyst_agent` kann nicht `web_search`

### Teil B — Write/Read Separation
- [ ] `intelligence/rag/indexer.py` wird nach `data-ingestion/` verschoben
- [ ] Intelligence-Service hat **keinen direkten Qdrant-Write-Zugriff** mehr
- [ ] Der Data-Ingestion-Service ist alleiniger Owner des Qdrant Write-Path
- [ ] Intelligence-Service ruft Indexierung nur über einen definierten internen Endpoint auf
  (oder: data-ingestion exposed `POST /internal/ingest` → intelligence POSTet dort hin)
- [ ] Alle bestehenden Tests nach der Verschiebung grün

### Teil C — Data Lineage in IntelAnalysis
- [ ] Neues Pydantic-Model `SourceRef`:
  ```python
  class SourceRef(BaseModel):
      doc_id: str          # Qdrant Point-ID des Quelldokuments
      source: str          # "rss", "gdelt", "manual"
      title: str
      relevance_score: float  # Qdrant Score aus der Retrieval-Query
  ```
- [ ] `IntelAnalysis.sources_used` wird von `list[str]` auf `list[SourceRef]` umgestellt
- [ ] `retriever.py` liefert `SourceRef`-Objekte statt String-Listen
- [ ] `synthesis_agent.py` propagiert die `SourceRef`-Liste in die finale `IntelAnalysis`
- [ ] `GET /api/v1/intel/history` gibt `sources_used` als `list[SourceRef]` zurück
- [ ] Frontend `IntelPanel.tsx` zeigt Sources als klickbare Liste mit Titel und Score

---

## Tests (VOR Implementierung schreiben)

```
intelligence/tests/
├── unit/
│   ├── test_agent_tool_permissions.py   # Teil A — Tool-Sandboxing
│   ├── test_source_ref_model.py         # Teil C — Pydantic-Validation
│   └── test_retriever_returns_refs.py   # Teil C — Retriever-Output
├── integration/
│   └── test_pipeline_lineage.py         # Ende-zu-Ende: Query → IntelAnalysis mit doc_ids
```

Teil B ist primär strukturell — der bestehende `test_indexer.py` muss am neuen Pfad grünen.

---

## Dependencies
- Blocked by: TASK-006 (RAG System), TASK-005 (Intelligence Pipeline)
- Blocks: TASK-012 (Data Ingestion — wegen Indexer-Verschiebung), TASK-013 (Integration Test)

## Implementierungsreihenfolge
1. Teil C zuerst (isoliert, keine Abhängigkeiten zu A/B)
2. Teil B (Refactor, rein strukturell)
3. Teil A zuletzt (baut auf sauberem B auf)

## Documentation
- LangGraph Tool-Use: `/websites/langchain_oss_python_langgraph` → "tool_node", "bind_tools"
- LangGraph Interrupt: `/websites/langchain_oss_python_langgraph` → "human-in-the-loop"
- Qdrant Scored Points: `/websites/qdrant_tech` → "ScoredPoint", "search with payload"

## Session-Notes

**Status 2026-03-29: PARTIAL**
- `services/intelligence/extraction/entity_extractor.py` wurde außerhalb dieses Tasks implementiert.
  NER via vLLM (Qwen3.5-27B-AWQ) + Neo4j-Write via HTTP Transactional API existiert.
  Entspricht grob Teil A (LLM statt spaCy), aber nicht im Rahmen dieses Tasks spezifiziert.
- Teil A (Agent Tool Sandboxing): ❌ offen
- Teil B (Write/Read Separation: indexer.py bleibt noch in intelligence/rag/): ❌ offen
- Teil C (Data Lineage / SourceRef): ❌ offen
