# TASK-001: Repo Setup + Docker Compose Foundation

## Service/Modul
Root + infra/docker/

## Akzeptanzkriterien
- [x] Monorepo mit uv workspaces konfiguriert (backend, intelligence, data-ingestion)
- [x] docker-compose.yml startet Redis + Qdrant + Ollama erfolgreich
- [x] Ollama Container mit nvidia GPU-Passthrough verifiziert
- [x] .env.example vorhanden, .env in .gitignore
- [x] Makefile mit `make up`, `make down`, `make test`, `make logs`
- [x] Pre-commit config: ruff, mypy

## Tests (VOR Implementierung schreiben)
- [x] scripts/test_docker_health.sh (curl healthchecks für Redis, Qdrant, Ollama)

## Dependencies
- Blocked by: -
- Blocks: TASK-002, TASK-003, TASK-004, TASK-005, TASK-006, TASK-007

## Documentation
- Docker Compose GPU: https://docs.docker.com/compose/gpu-support/
- uv workspaces: https://docs.astral.sh/uv/concepts/workspaces/
- Context7: `/qdrant/qdrant` → "Docker deployment health check"

## Session-Notes
(noch keine Sessions)
