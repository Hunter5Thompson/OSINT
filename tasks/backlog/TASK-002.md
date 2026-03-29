# TASK-002: FastAPI Backend Skeleton + Proxy Service

## Service/Modul
services/backend/

## Akzeptanzkriterien
- [x] FastAPI App mit Health-Endpoint `/api/v1/health`
- [x] Pydantic Settings aus .env geladen
- [x] Redis-Connection mit async redis client
- [x] Generic ProxyService Klasse: fetch → cache → return
- [x] CORS Middleware für localhost:5173
- [x] structlog konfiguriert (JSON-Format)
- [x] OpenAPI Docs unter /docs erreichbar

## Tests (VOR Implementierung schreiben)
- [x] tests/unit/test_config.py (Settings laden)
- [x] tests/unit/test_proxy_service.py (Cache Hit/Miss/Expiry)
- [x] tests/integration/test_health.py (FastAPI TestClient)

## Dependencies
- Blocked by: TASK-001
- Blocks: TASK-003, TASK-004, TASK-005

## Documentation
- Context7: `/websites/fastapi_tiangolo` → "WebSocket, middleware, settings"
- Redis async: https://redis.readthedocs.io/en/stable/examples/asyncio_examples.html

## Session-Notes
(noch keine Sessions)
