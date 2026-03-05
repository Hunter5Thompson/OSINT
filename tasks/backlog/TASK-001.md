# TASK-001: Repo Setup + Docker Compose Foundation

## Service/Modul
Root + infra/docker/

## Akzeptanzkriterien
- [ ] Monorepo mit uv workspaces konfiguriert (backend, intelligence, data-ingestion)
- [ ] docker-compose.yml startet Redis + Qdrant + Ollama erfolgreich
- [ ] Ollama Container mit nvidia GPU-Passthrough verifiziert
- [ ] .env.example vorhanden, .env in .gitignore
- [ ] Makefile mit `make up`, `make down`, `make test`, `make logs`
- [ ] Pre-commit config: ruff, mypy

## Tests (VOR Implementierung schreiben)
- [ ] scripts/test_docker_health.sh (curl healthchecks für Redis, Qdrant, Ollama)

## Dependencies
- Blocked by: -
- Blocks: TASK-002, TASK-003, TASK-004, TASK-005, TASK-006, TASK-007

## Documentation
- Docker Compose GPU: https://docs.docker.com/compose/gpu-support/
- uv workspaces: https://docs.astral.sh/uv/concepts/workspaces/
- Context7: `/qdrant/qdrant` → "Docker deployment health check"

## Session-Notes
(noch keine Sessions)
