# TASK-007: LangGraph Multi-Agent Intelligence Pipeline

## Service/Modul
services/intelligence/agents/ + services/intelligence/graph/

## Akzeptanzkriterien
- [x] AgentState TypedDict mit messages, sources, analysis, threat_level
- [x] OSINT Agent: Web-Recherche Tool + RSS Feed Tool + Qdrant Search Tool
- [x] Analyst Agent: Threat Assessment, Escalation Risk Scoring
- [x] Synthesis Agent: Report-Generierung aus Agent-Outputs
- [x] StateGraph: START → OSINT → Analyst → Synthesis → END
- [x] Conditional Edge: Skip OSINT wenn Qdrant ausreichend Kontext hat
- [x] SSE Streaming: Jeder Agent-Step wird als Event gestreamt
- [x] Ollama/vLLM als LLM Backend (konfigurierbar via Settings)
- [x] Query-to-Response <10s für Standard-Queries auf RTX 5090

## Tests (VOR Implementierung schreiben)
- [x] tests/unit/test_state.py (AgentState Serialization)
- [x] tests/unit/test_osint_agent.py (Tool-Use mit Mock-Responses)
- [x] tests/unit/test_analyst_agent.py (Threat Assessment Logic)
- [x] tests/unit/test_synthesis_agent.py (Report Format)
- [x] tests/integration/test_workflow.py (Full Graph Execution mit Mock-LLM)

## Fixtures
- tests/fixtures/mock_llm_responses.json
- tests/fixtures/mock_qdrant_results.json
- tests/fixtures/sample_osint_data.json

## Dependencies
- Blocked by: TASK-006 (RAG System)
- Blocks: TASK-008 (Intel API Endpoint)

## Documentation
- Context7: `/websites/langchain_oss_python_langgraph` → "Agentic RAG, StateGraph, streaming, tool use"
- Context7: `/langchain-ai/langgraph` → "Source patterns, conditional edges"
- LangGraph Streaming: https://docs.langchain.com/oss/python/langgraph/streaming

## Session-Notes
(noch keine Sessions)
