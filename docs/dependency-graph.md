<!-- manifest: project=WorldView | doc_version=1.0 | updated=2026-03-05 -->

# WorldView — Dependency Graph & Parallelisierung

## Execution Phases

```
Phase 0 — Foundation (1 Agent, Sequential)
═══════════════════════════════════════════
  TASK-001: Repo Setup + Docker Compose
      │
      ▼
Phase 1 — Backend + RAG (2-3 Agents, Parallel)
═══════════════════════════════════════════
  ┌── TASK-002: FastAPI Skeleton ──────────────────┐
  │       │                                        │
  │       ├── TASK-003: Flight Proxy               │
  │       ├── TASK-004: Earthquake Proxy           │
  │       └── TASK-005: Satellite TLE Proxy        │
  │                                                │
  └── TASK-006: RAG System (Qdrant + Embeddings) ──┘
          │
          ▼
Phase 2 — Intelligence + Frontend (2 Agents, Parallel)
═══════════════════════════════════════════
  ┌── TASK-007: LangGraph Multi-Agent Pipeline ────┐
  │       │                                        │
  │       └── TASK-008: Intel API (SSE)            │
  │                                                │
  └── TASK-009: CesiumJS Globe + Layers ───────────┘
          │
          ▼
Phase 3 — Polish (2 Agents, Parallel)
═══════════════════════════════════════════
  ┌── TASK-010: GLSL Shaders (CRT/NV/FLIR) ───────┐
  │                                                │
  ├── TASK-011: Tactical C2 UI                     │
  │                                                │
  └── TASK-012: Data Ingestion Service ────────────┘
          │
          ▼
Phase 4 — Integration (1 Agent)
═══════════════════════════════════════════
  TASK-013: Full Integration Test
```

## Parallelisierungs-Matrix

| Phase | Agents Parallel | Tasks | Estimated Effort |
|-------|----------------|-------|-----------------|
| 0 | 1 | TASK-001 | 2h |
| 1 | 3 | TASK-002→005 ∥ TASK-006 | 8h |
| 2 | 2 | TASK-007→008 ∥ TASK-009 | 12h |
| 3 | 3 | TASK-010 ∥ TASK-011 ∥ TASK-012 | 8h |
| 4 | 1 | TASK-013 | 2h |
| **Total** | | **13 Tasks** | **~32h** |

## Mocking-Strategie für Parallelität

### Phase 1: Backend ↔ RAG parallel
- Backend (TASK-002-005): Entwickelt gegen Mock-Fixtures für externe APIs
- RAG (TASK-006): Entwickelt gegen lokales Qdrant + Ollama, unabhängig vom Backend

### Phase 2: Intelligence ↔ Frontend parallel
- Intelligence (TASK-007-008): Nutzt echtes RAG System, Mock-LLM für Tests
- Frontend (TASK-009): Nutzt Backend API, Mock-Daten wenn Backend nicht läuft

### Phase 3: Alle unabhängig
- GLSL Shaders: Braucht nur den Globe (TASK-009)
- Tactical UI: Braucht Globe + Intel API
- Data Ingestion: Braucht nur Qdrant + Ollama

## Critical Path

```
TASK-001 → TASK-002 → TASK-003 → TASK-009 → TASK-011 → TASK-013
                  └→ TASK-006 → TASK-007 → TASK-008 ──┘
```

Längster Pfad: 7 Tasks, ~24h effektive Arbeitszeit.
Mit 3 parallelen Claude Code Agents reduzierbar auf ~12h Wall-Clock-Time.
