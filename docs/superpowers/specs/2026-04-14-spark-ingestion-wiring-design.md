# Spark Ingestion Wiring (Minimal) — Design

**Datum:** 2026-04-14
**Scope:** Minimal-Wiring (Option A aus Brainstorming)
**Status:** Approved (User)

## Ziel

Extraction-LLM-Calls aus `services/data-ingestion` permanent gegen den Spark vLLM-Server (`http://192.168.178.39:8000/v1/`, Gemma-4 26B-A4B-it) routen. Dadurch entfällt der GPU-Swap zwischen Modus C (Interactive 9B) und Modus D (Ingestion 27B GGUF) auf der RTX 5090 — Ingestion und Interactive können parallel laufen.

## Nicht-Ziele

- TEI-Embedding bleibt lokal auf deadpool-ultra (`http://localhost:8001`). ARM-Kompatibilität wird in einem späteren Sprint geklärt.
- `docker-compose.yml` und `odin.sh` werden nicht angefasst. Der Ingestion-Modus existiert weiterhin als Fallback.
- Kein Fallback auf lokales Modell wenn Spark offline ist. Feeds sind gepuffert; Scheduler retried beim nächsten Tick.
- Scheduler bleibt auf deadpool-ultra (kein Remote-Scheduling auf Spark).

## Architektur

```
RTX 5090 (deadpool-ultra)            DGX Spark (192.168.178.39)
─────────────────────────            ──────────────────────────
 vLLM 9B Interactive (8000)           vLLM Gemma-4 26B (8000)
 TEI Embed (8001)         ◄──────┐
 Backend / Frontend / Intel       │
 Scheduler + Pipeline ───HTTP─────┴──► /v1/chat/completions
 Qdrant / Neo4j / Redis
```

Pipeline und NLM-Extract öffnen HTTPS/HTTP-Verbindungen ins LAN. Latenz ist im einstelligen ms-Bereich (Gigabit Ethernet, gleicher Switch).

## Änderungen

### 1. `services/data-ingestion/config.py`

Neue Settings-Felder (alphabetisch nach Block):

```python
# Ingestion LLM (Spark — Gemma-4 26B)
ingestion_vllm_url: str = "http://192.168.178.39:8000/v1"
ingestion_vllm_model: str = "google/gemma-4-26B-A4B-it"
ingestion_vllm_timeout: float = 120.0
```

`vllm_url` und `vllm_model` bleiben unverändert für Rückwärtskompatibilität, werden aber von Pipeline und NLM-Extract nicht mehr gelesen.

### 2. `services/data-ingestion/pipeline.py`

Alle Stellen, die `settings.vllm_url` / `settings.vllm_model` für Extraction nutzen, lesen stattdessen `settings.ingestion_vllm_url` / `settings.ingestion_vllm_model`. HTTP-Timeout setzt `settings.ingestion_vllm_timeout`.

### 3. `services/data-ingestion/nlm_ingest/extract.py`

Gleiche Umstellung: `ingestion_vllm_url` / `ingestion_vllm_model` / `ingestion_vllm_timeout` für die Extraction-Phase der NotebookLM-Pipeline.

### 4. `.env.example`

Drei neue Variablen mit Spark-Defaults und einem Kommentar, der erklärt warum Ingestion auf Spark läuft.

### 5. Lightweight Healthcheck

Beim Start des Pipeline-Prozesses ein einmaliger `GET {ingestion_vllm_url}/models`-Call mit kurzem Timeout (5 s). Bei Erfolg: `INFO`-Log mit Modellnamen. Bei Fehler: `WARNING`-Log, Pipeline startet trotzdem (Scheduler retried). Kein Hard-Fail.

Implementierung als Helper in `pipeline.py` — keine eigene Datei, da trivial.

## Datenfluss (unverändert)

```
Feed → Collector → Redis Stream → Pipeline.extract() ─HTTP→ Spark vLLM
                                       │
                                       ▼
                                 Pydantic Validate → Cypher Templates → Neo4j
                                                  → TEI Embed (lokal) → Qdrant
```

Nur die `extract()`-HTTP-Calls wechseln den Endpoint. Alles andere bleibt identisch.

## Fehlerfälle

| Szenario | Verhalten |
|---|---|
| Spark offline beim Start | Warning-Log, Pipeline läuft, erste Extraction schlägt fehl, Scheduler retried |
| Spark offline während Run | HTTP-Exception, Item bleibt in Stream (kein ACK), retry beim nächsten Tick |
| Spark antwortet langsam | Timeout 120 s, Item retry |
| Modellname falsch | vLLM 404, Pipeline-Log zeigt Fehler, Item retry |

## Tests

**Unit (`tests/test_config.py` — neu oder erweitert):**
- Spark-Defaults werden korrekt geladen
- Env-Override für `INGESTION_VLLM_URL` funktioniert

**Unit (`tests/test_pipeline.py`):**
- Pipeline ruft `settings.ingestion_vllm_url` mit korrektem Model auf (mit `respx` gemockt)
- Timeout wird aus `ingestion_vllm_timeout` übernommen

**Unit (`tests/test_nlm_extract.py`):**
- Extract-Phase nutzt Spark-URL und -Model

**Healthcheck-Test:**
- Erfolgsfall: Log enthält Modellnamen
- Fehlerfall (URL unreachable): Warning-Log, kein Exception-Throw

**Integration (Skip wenn Spark unreachable):**
- Smoke-Test: Echter Call gegen Spark, validiert Response-Schema

## Rollout

1. Feature-Branch `feature/spark-ingestion-wiring`
2. TDD: Tests rot → Implementation → Tests grün
3. Lokal `up interactive` + Pipeline manuell triggern → bestätigen dass Extraction über Spark läuft (`docker logs vllm-gemma4` auf Spark zeigt Requests)
4. Merge → Memory-Update (`project_spark_ingestion_offload.md` → done)

## Offene Punkte (für Folge-Sprints)

- TEI auf Spark (ARM-Image klären)
- Healthcheck-Endpoint im Backend exposen, sodass Frontend Spark-Status anzeigen kann
- Prompt-Migration Qwen → Gemma (falls Extraction-Qualität abweicht)
