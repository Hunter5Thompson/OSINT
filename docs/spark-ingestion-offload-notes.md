# DGX Spark Ingestion Offload — Planungsnotizen

**Datum:** 2026-04-13
**Status:** Geplant — Spec + Plan in nächster Session

## Ziel

Ingestion-Stack permanent auf DGX Spark (192.168.178.39), Interactive-Stack permanent auf RTX 5090 (deadpool-ultra). Kein `odin.sh swap` mehr nötig.

## Architektur

```
deadpool-ultra (RTX 5090)              DGX Spark (GB10, 128 GB)
┌─────────────────────────┐            ┌──────────────────────────┐
│ vLLM 9B (Interactive)   │            │ vLLM 27B (Extraction)    │
│ TEI Embed (Interactive) │            │ TEI Embed (Ingestion)    │
│ Frontend (5173)         │            │                          │
│ Backend (8080)          │            │ API: 192.168.178.39:8000 │
│ Intelligence (8003)     │            │ TEI: 192.168.178.39:8001 │
│ Qdrant (6333)           │◄───LAN────►│                          │
│ Neo4j (7474/7687)       │            │                          │
│ Redis (6379)            │            │                          │
│ Scheduler + Collectors  │            │                          │
└─────────────────────────┘            └──────────────────────────┘
```

## Änderungen

### config.py
- Neue Settings: `ingestion_vllm_url` (default: `http://192.168.178.39:8000`)
- Neue Settings: `ingestion_tei_url` (default: `http://192.168.178.39:8001`)
- BaseCollector und Pipeline nutzen diese statt localhost-URLs

### docker-compose.yml
- Ingestion-Service braucht kein GPU-Profil mehr
- Env-Vars `INGESTION_VLLM_URL` + `INGESTION_TEI_URL` zeigen auf Spark
- vLLM-27B und llama.cpp Container entfallen komplett

### odin.sh
- `up interactive` startet alles inkl. Ingestion (ein Modus statt zwei)
- `swap` Subcommand wird deprecated
- Neuer Subcommand: `odin.sh spark status` — Healthcheck auf Spark

### Netzwerk
- Spark und deadpool-ultra im gleichen LAN (FritzBox 6660)
- Spark IP: 192.168.178.39 (fest gepinnt)
- Qdrant/Neo4j/Redis auf deadpool-ultra müssen von Spark erreichbar sein
- Docker-Netzwerk: `extra_hosts` oder `network_mode: host` für Spark-Zugriff

## Offene Fragen

### TEI auf ARM (aarch64)
- Spark ist ARM (MediaTek Cortex-X925), nicht x86
- TEI Docker Image `ghcr.io/huggingface/text-embeddings-inference:120-1.9` ist für sm_120 (Blackwell) aber x86
- Option A: TEI nativ auf Spark kompilieren
- Option B: TEI weiterhin auf deadpool-ultra, nur vLLM auf Spark
- Option C: Sentence-Transformers Python-basiert auf Spark (langsamer, aber einfach)

### Extraction-Modell
- Gemma-4 26B-A4B-it läuft bereits auf Spark (BF16, ~48.5 GB)
- Qwen 27B wäre konsistenter mit dem bestehenden Ingestion-Prompt-Engineering
- Empfehlung: Gemma testen, Prompts anpassen wenn nötig

### Scheduler-Standort
- Option A: Scheduler auf deadpool-ultra, Collectors machen HTTP-Calls an Spark-vLLM
  - Pro: Alles zentral, ein Docker-Compose
  - Con: Netzwerk-Latenz bei jedem LLM-Call
- Option B: Scheduler + Collectors auf Spark
  - Pro: LLM-Calls lokal, kein Netzwerk-Overhead
  - Con: Braucht Docker auf Spark, Qdrant/Neo4j/Redis remote
- Empfehlung: Option A (einfacher, Latenz im LAN vernachlässigbar)

### Healthcheck / Monitoring
- `odin.sh spark status` prüft vLLM + TEI Healthchecks auf Spark
- Collectors brauchen Fallback-Logik wenn Spark offline (graceful skip, retry)
- Optional: Wake-on-LAN für Spark (aktuell nicht konfiguriert)

## Sprint-Scope

1. Config-Änderungen (ingestion URLs)
2. BaseCollector + Pipeline URL-Switch
3. docker-compose Vereinfachung
4. odin.sh Refactor (ein Modus)
5. Spark-Setup (vLLM Container, TEI, Netzwerk)
6. Smoke-Test: voller Ingestion-Cycle über Spark
7. Monitoring-Integration
