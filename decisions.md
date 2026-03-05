<!-- manifest: project=WorldView | doc_version=1.0 | updated=2026-03-05 -->

# Entscheidungslog

## DEC-001: 2026-03-05 — Single-User statt Multi-User-System
**Kontext**: Soll WorldView ein Multi-User-System mit Auth werden?
**Optionen**:
  A) Multi-User mit Keycloak — Pro: Teamfähig / Contra: Massive Komplexität, Auth-Overhead
  B) Single-User ohne Auth — Pro: Einfach, schnell / Contra: Nicht teilbar
**Entscheidung**: B) Single-User
**Begründung**: Lokaler Entwickler-Stack, kein Team-Zugriff nötig. Auth kann in v2 nachgerüstet werden.
**Auswirkung auf**: REQ-006 (keine Auth-Middleware), architecture.md (kein Keycloak Container)
**Review-Termin**: Wenn Team-Zugriff gewünscht

---

## DEC-002: 2026-03-05 — Python Monorepo statt Microservices
**Kontext**: Backend, Intelligence und Data-Ingestion als separate Services oder Monolith?
**Optionen**:
  A) Separate Docker-Container pro Service — Pro: Isolation / Contra: IPC-Overhead, mehr Dockerfiles
  B) Monorepo mit shared libs — Pro: Einfacher Import, weniger Overhead / Contra: Weniger Isolation
**Entscheidung**: A) Separate Services, aber shared Python libs via workspace
**Begründung**: Intelligence-Pipeline braucht GPU-Zugriff und andere Dependencies als Backend. Docker Compose handhabt die Orchestrierung.
**Auswirkung auf**: architecture.md (Dateistruktur), FEAT-010 (Docker Compose)

---

## DEC-003: 2026-03-05 — Ollama als Dev-Default, vLLM als Prod-Option
**Kontext**: Welcher Inference-Server als Default?
**Optionen**:
  A) Nur Ollama — Pro: Einfach / Contra: Weniger Throughput
  B) Nur vLLM — Pro: Performance / Contra: Setup-Aufwand, nicht für alle Modelle
  C) Beide, konfigurierbar — Pro: Flexibel / Contra: Zwei Code-Pfade
**Entscheidung**: C) Beide via OpenAI-kompatible API
**Begründung**: Beide bieten OpenAI-kompatible `/v1/chat/completions`. Ein einziger Client mit konfigurierbarer `base_url` reicht. Ollama für Quick-Start, vLLM für Production-Load.
**Auswirkung auf**: architecture.md (Tech-Stack), CLAUDE.md (LLM-Konfiguration)

---

## DEC-004: 2026-03-05 — uv statt pip/poetry für Python
**Kontext**: Python Package Manager
**Optionen**:
  A) pip + requirements.txt — Pro: Universal / Contra: Kein Lockfile, langsam
  B) Poetry — Pro: Lockfile / Contra: Langsam, Docker-Layer-Caching problematisch
  C) uv — Pro: 10-100x schneller, Lockfile, workspace support / Contra: Relativ neu
**Entscheidung**: C) uv
**Begründung**: Albert kennt uv bereits. Drastisch schnellere Installs, native workspace support für shared libs.
**Auswirkung auf**: Alle Python-Services (pyproject.toml statt requirements.txt)
