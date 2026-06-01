# AGENTS.md — WorldView Tactical Intelligence Platform

## Quick reference (commands must run from service directories)

```bash
# Backend (FastAPI, port 8080 host / 8000 container)
cd services/backend && uv sync && uv run pytest && uv run ruff check app/ && uv run mypy app/

# Frontend (React/CesiumJS, port 5173)
cd services/frontend && npm install && npm run lint && npm run type-check && npm test

# Intelligence (LangGraph, port 8003)
cd services/intelligence && uv sync && uv run pytest

# Data Ingestion (scheduler + feeds)
cd services/data-ingestion && uv sync && uv run pytest
```

**Lockfiles are gitignored** — `uv sync` regenerates `uv.lock`, `npm install` regenerates `package-lock.json`.

## Docker Compose: profiles, not monolithic

Services are opt-in via profiles: `ingestion`, `interactive`, `interactive-spark`, `notebooklm`, `vision`. Core services (redis, qdrant, neo4j, tei-embed) have no profile — always start. Use `odin.sh`:

```bash
./odin.sh up interactive          # 9B + reranker + intelligence + backend + frontend
./odin.sh up ingestion            # 27B + data-ingestion (GDELT, RSS, TLE)
./odin.sh swap ingestion          # stop active vLLM, start other mode
./odin.sh smoke                   # health checks for running services
```

## GPU constraint (single RTX 5090, 32 GB)

**Only one LLM at a time.** Swap modes with `odin.sh swap`. No two vLLM/llama.cpp containers can run concurrently.

**CRITICAL: vLLM 27B is BROKEN** in docker-compose (infinite encoder profiling loop with v0.18+). Use **llama.cpp** for Qwen3.5-27B-GGUF Q6_K. See `docs/CONTAINER-STATUS.md` for the working `docker run` command.

**TEI image tag must be `:120-1.9`** (Blackwell sm_120). `latest` is sm_80 and crashes on RTX 5090:
```
ghcr.io/huggingface/text-embeddings-inference:120-1.9.3
```

## Port mapping quirks

| Service | Host | Container | Why |
|---------|------|-----------|-----|
| vLLM | 8000 | 8000 | — |
| Backend | **8080** | 8000 | 8000 host taken by vLLM |
| TEI Embed | 8001 | 80 | TEI default |
| TEI Rerank | 8002 | 80 | TEI default |
| Voxtral | 8010 | 8000 | — |

## Critical architecture rules

- **Neo4j write path**: deterministic Cypher templates ONLY. **No LLM-generated Cypher on writes.**
- **Neo4j read path**: LLM can generate Cypher for queries. Read-only.
- **Neo4j queries always use parameter binding** — no string interpolation.
- **Backend: all async/await** — no synchronous HTTP calls (`httpx.AsyncClient`).
- **Frontend: no `any` types** — TypeScript strict.
- **CesiumJS bulk rendering**: use `BillboardCollection` (not Entity API). Use `CallbackProperty` for smooth tracking without React re-renders.
- **No API keys in code** — all via `.env` / `config.py` (Pydantic Settings). No hardcoded URLs.
- **GDELT ingestion**: raw files pipeline only. Old DOC API collector is dead and not registered in the scheduler.

## Testing & quality

- **TDD required**: tests first (red), minimal impl (green), refactor.
- **`pytest.mark.skip` only with TODO comment + ticket reference** — no silent skipping.
- Backend: `asyncio_mode = "auto"`, `mypy` strict mode, `ruff` with `E,F,W,I,N,UP`.
- Frontend: `vitest run`, ESLint, `tsc --noEmit`.
- Each service has its own test directory and runs independently.

## Commit style

```
feat(backend): add flight proxy endpoint
fix(frontend): fix satellite orbit rendering
test(intelligence): add OSINT agent unit tests
```

## Key reference files

| File | Purpose |
|------|---------|
| `CLAUDE.md` | Full project context, hardware modes, verbote, agent context |
| `TASKS.md` | Task registry (single source of truth), canonical tech stack |
| `decisions.md` | Architecture decision log |
| `architecture.md` | System architecture (diagrams, data flow) |
| `docs/CONTAINER-STATUS.md` | Working container configs and known issues |
| `odin.sh` | Orchestration entry point (always run from repo root) |
