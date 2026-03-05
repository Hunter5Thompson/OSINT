# TASK-006: RAG System (Qdrant + Embedding Pipeline)

## Service/Modul
services/intelligence/rag/

## Akzeptanzkriterien
- [ ] Qdrant Collection "worldview_intel" mit 768-dim Vektoren erstellt
- [ ] Embedder-Klasse: Text → nomic-embed-text → Vektor (via Ollama API)
- [ ] Chunker: Semantic Chunking mit max 512 Token Chunks
- [ ] Indexer: Document → Chunks → Embed → Qdrant Upsert
- [ ] Retriever: Query → Embed → Qdrant Search → Top-K Documents
- [ ] Payload-Filtering nach region, source, published_at
- [ ] Batch-Embedding für >100 Dokumente
- [ ] Query-Latenz <2s für Retrieval (ohne LLM)

## Tests (VOR Implementierung schreiben)
- [ ] tests/unit/test_chunker.py (Chunk-Sizes, Overlap)
- [ ] tests/unit/test_embedder.py (Mock Ollama Response)
- [ ] tests/integration/test_qdrant_ops.py (Create, Upsert, Search, Filter)
- [ ] tests/integration/test_rag_pipeline.py (End-to-End: Ingest → Query)

## Fixtures
- tests/fixtures/sample_documents.json (5 Geopolitik-Artikel)
- tests/fixtures/sample_embeddings.json (pre-computed für Unit-Tests)

## Dependencies
- Blocked by: TASK-001 (Qdrant Container)
- Blocks: TASK-007 (LangGraph Pipeline)

## Documentation
- Context7: `/websites/qdrant_tech` → "Collection creation, filtering, hybrid search"
- Context7: `/qdrant/qdrant-client` → "Python async client"
- Ollama Embeddings API: https://github.com/ollama/ollama/blob/main/docs/api.md#generate-embeddings

## Session-Notes
(noch keine Sessions)
