# TASK-007: LangGraph Multi-Agent Intelligence Pipeline

## Service/Modul
services/intelligence/agents/ + services/intelligence/graph/

## Akzeptanzkriterien
- [ ] AgentState TypedDict mit messages, sources, analysis, threat_level
- [ ] OSINT Agent: Web-Recherche Tool + RSS Feed Tool + Qdrant Search Tool
- [ ] Analyst Agent: Threat Assessment, Escalation Risk Scoring
- [ ] Synthesis Agent: Report-Generierung aus Agent-Outputs
- [ ] StateGraph: START → OSINT → Analyst → Synthesis → END
- [ ] Conditional Edge: Skip OSINT wenn Qdrant ausreichend Kontext hat
- [ ] SSE Streaming: Jeder Agent-Step wird als Event gestreamt
- [ ] Ollama/vLLM als LLM Backend (konfigurierbar via Settings)
- [ ] Query-to-Response <10s für Standard-Queries auf RTX 5090

## Tests (VOR Implementierung schreiben)
- [ ] tests/unit/test_state.py (AgentState Serialization)
- [ ] tests/unit/test_osint_agent.py (Tool-Use mit Mock-Responses)
- [ ] tests/unit/test_analyst_agent.py (Threat Assessment Logic)
- [ ] tests/unit/test_synthesis_agent.py (Report Format)
- [ ] tests/integration/test_workflow.py (Full Graph Execution mit Mock-LLM)

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
