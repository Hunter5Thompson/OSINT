# TASK-008: Intel API Endpoint (SSE Streaming)

## Service/Modul
services/backend/app/routers/intel.py

## Akzeptanzkriterien
- [ ] POST /api/v1/intel/query → SSE Stream (text/event-stream)
- [ ] POST /api/v1/intel/hotspot/{id} → SSE Stream mit Hotspot-Kontext
- [ ] Backend ruft Intelligence Service auf, streamt Agent-Steps als Events
- [ ] Event-Format: `data: {"agent": "osint", "step": "searching", "content": "..."}`
- [ ] GET /api/v1/intel/history → letzte 50 Queries

## Dependencies
- Blocked by: TASK-002 (Backend), TASK-007 (LangGraph Pipeline)
- Blocks: TASK-011 (UI Intel Panel)

## Documentation
- Context7: `/websites/fastapi_tiangolo` → "StreamingResponse, SSE"
