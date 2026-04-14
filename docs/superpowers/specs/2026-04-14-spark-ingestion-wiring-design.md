# Spark Ingestion Wiring (Minimal) — Design

**Datum:** 2026-04-14
**Scope:** Minimal-Wiring (Option A aus Brainstorming) + Compose-Profil + Retry-Fix
**Status:** Revision 2 (nach Code-Review)

## Ziel

Extraction-LLM-Calls aus `services/data-ingestion` permanent gegen den Spark vLLM-Server (`http://192.168.178.39:8000`, Gemma-4 26B-A4B-it) routen. Dadurch entfällt der GPU-Swap zwischen Modus C (Interactive 9B) und Modus D (Ingestion 27B GGUF). Ingestion und Interactive laufen über `./odin.sh up interactive-spark` parallel.

## Nicht-Ziele

- TEI-Embedding bleibt lokal auf deadpool-ultra (`http://localhost:8001`). ARM-Image-Klärung: Folge-Sprint.
- Bestehende Modi (`up ingestion`, `up interactive`) bleiben funktional als Fallback. Wir fügen einen neuen Modus hinzu, statt die alten zu ersetzen.
- Scheduler bleibt auf deadpool-ultra (kein Remote-Scheduling).
- Kein lokaler LLM-Fallback wenn Spark offline. Bei transienten Fehlern wird der Qdrant-Upsert für das betroffene Item übersprungen; das Item wird **nicht** persistent als "pending" markiert. Der nächste Run findet es erneut über die Quelle (RSS-Re-Fetch, GDELT-Re-Query, etc.) und versucht erneut zu extrahieren — Hash-Dedup greift nicht, weil noch kein Qdrant-Eintrag existiert. Konsequenz: die Quelle muss das Item beim nächsten Tick noch ausliefern. Telegram-Items, die bereits aus dem Channel rotiert sind, gehen verloren — acceptable für diesen Sprint.

## Architektur

```
RTX 5090 (deadpool-ultra)            DGX Spark (192.168.178.39)
─────────────────────────            ──────────────────────────
 vLLM 9B Interactive (8000)           vLLM Gemma-4 26B (8000)
 TEI Embed (8001)
 Backend / Frontend / Intel
 data-ingestion ─────────HTTP─────────► /v1/chat/completions
 Qdrant / Neo4j / Redis
```

Latenz im LAN ist ms-Bereich (Gigabit Ethernet, gleicher Switch).

## Änderungen

### 1. `services/data-ingestion/config.py`

```python
# Ingestion LLM (Spark — Gemma-4 26B)
# URL OHNE /v1 — Aufrufer hängen `/v1/chat/completions` an (Konvention wie vllm_url)
ingestion_vllm_url: str = "http://192.168.178.39:8000"
ingestion_vllm_model: str = "google/gemma-4-26B-A4B-it"
ingestion_vllm_timeout: float = 120.0
```

`vllm_url` / `vllm_model` bleiben unverändert (für Backwards-Compat mit Modus D).

### 2. URL-Normalisierungs-Regel (verbindlich)

**Konvention:** `ingestion_vllm_url` ist ein **Base-URL ohne `/v1`**. Alle Aufrufer hängen den vollen Pfad `/v1/chat/completions` an. Begründung: matched die bestehende `settings.vllm_url`-Konvention in `pipeline.py:199` und vermeidet `/v1/v1`-Bugs.

**Betroffene Call-Sites — alle drei werden auf gleiches Schema umgestellt:**

| Datei:Zeile | Vorher | Nachher |
|---|---|---|
| `pipeline.py:199` | `f"{settings.vllm_url}/v1/chat/completions"` | `f"{settings.ingestion_vllm_url}/v1/chat/completions"` |
| `nlm_ingest/extract.py:66` | `f"{vllm_url}/chat/completions"` (Aufrufer übergibt URL mit `/v1`) | Funktion erwartet **Base-URL ohne `/v1`**, nutzt `f"{vllm_url}/v1/chat/completions"` |
| `nlm_ingest/cli.py:221-222` | `vllm_url=settings.vllm_url + "/v1"`, `vllm_model=settings.vllm_model` | `vllm_url=settings.ingestion_vllm_url`, `vllm_model=settings.ingestion_vllm_model` |

**Tests müssen `/v1/v1` explizit ausschließen** (Regex-Assertion auf den finalen Request-URL).

### 3. `services/data-ingestion/pipeline.py` — Modell + Timeout + Retry-Fix

- `_call_vllm` liest `settings.ingestion_vllm_url`, `settings.ingestion_vllm_model`, `settings.ingestion_vllm_timeout`.
- **Drei exklusive Fehlerklassen** (`process_item` raised oder returned je nach Klasse):

| Klasse | Auslöser | Signatur | Caller-Verhalten |
|---|---|---|---|
| `ExtractionTransientError` | HTTP-Timeout, ConnectError, HTTP 5xx | raised | Skip Qdrant, Warning-Log, Retry über Quellen-Re-Fetch |
| `ExtractionConfigError` | HTTP 404, 401, 403 | raised | Skip Qdrant, **Error**-Log, kein Retry sinnvoll bis Config gefixt |
| `ValidEmpty` (kein Sentinel — Funktion returned `None` oder dict) | LLM lieferte leeres/parsbares Ergebnis (auch JSON-Parse-Fehler nach erfolgreicher HTTP-Response) | return `None` oder dict | Upsert wie bisher mit `codebook_type="other.unclassified"` falls leer |

Andere unerwartete Exceptions werden NICHT abgefangen — sie propagieren und stoppen den Collector-Run (sichtbar im Log, kein silent failure).

- Healthcheck (siehe §6) prüft Modell-Verfügbarkeit beim Scheduler-Start zusätzlich präventiv.

### 4. `services/data-ingestion/feeds/rss_collector.py` — Retry-Verhalten

In der Schleife (`rss_collector.py:176-183`):

```python
try:
    enrichment = await process_item(...)
except ExtractionTransientError as exc:
    log.warning("extraction_skipped_transient", url=link, error=str(exc))
    continue  # KEIN Qdrant-Upsert → Hash-Dedup greift nicht → Retry über Quellen-Re-Fetch
except ExtractionConfigError as exc:
    log.error("extraction_skipped_config", url=link, error=str(exc))
    continue  # KEIN Qdrant-Upsert → Recovery erst nach Config-Fix
```

Andere Collectors (`gdelt_collector.py`, `telegram_collector.py`, etc.), die `process_item` aufrufen, bekommen denselben Try/Except-Block für `ExtractionTransientError` und `ExtractionConfigError`.

**Audit per Verhaltenstest, nicht per grep:** Pro Collector, der `process_item` aufruft, gibt es einen dedizierten Test mit zwei Szenarien:
1. `process_item` raised `ExtractionTransientError` → kein Qdrant-Upsert (assertet via Mock auf `qdrant.upsert`)
2. `process_item` raised `ExtractionConfigError` → kein Qdrant-Upsert + Error-Log

Liste der zu testenden Collectors in der Implementation:
- `rss_collector.py`
- `gdelt_collector.py`
- `telegram_collector.py`
- alle weiteren via `Grep` ermittelten Aufrufer von `process_item` (Implementation-Schritt 1: Grep-Liste fixieren, jeden Treffer testen).

### 5. `services/data-ingestion/nlm_ingest/extract.py` + `cli.py`

- `extract.py`: Funktion `extract_with_qwen` erwartet jetzt **Base-URL ohne `/v1`** (Breaking, aber interner Aufrufer ist nur `cli.py`). Hängt `/v1/chat/completions` selbst an.
- `cli.py`: Übergibt `settings.ingestion_vllm_url` (ohne `+ "/v1"`) und `settings.ingestion_vllm_model`.
- Funktionsname bleibt `extract_with_qwen` (Refactor zu `extract_with_llm` ist out-of-scope).

### 6. Healthcheck — Platzierung verbindlich

**Ort:** `services/data-ingestion/scheduler.py`, in der `main()`-Coroutine **nach `scheduler.start()` und vor `initial_collection_starting`** (also nach `scheduler.py:425`, vor `:428`).

**Verhalten — drei exklusive Outcomes (matched die Fehlerklassen aus §3):**

1. **Reachable + Modell verfügbar:** `GET {ingestion_vllm_url}/v1/models` liefert 200 UND `settings.ingestion_vllm_model` ist in `data[].id` enthalten.
   - Log: `log.info("ingestion_llm_ready", url=..., model=...)`

2. **Reachable, aber Modell fehlt:** 200, aber `ingestion_vllm_model` nicht in `data[].id`.
   - Log: `log.error("ingestion_llm_model_mismatch", url=..., expected=..., available=[...])`
   - Scheduler läuft trotzdem; Collectors werden bei der ersten Extraction `ExtractionConfigError` raisen (404 vom vLLM).

3. **Unreachable:** Timeout, ConnectError, Non-200 von `/v1/models`.
   - Log: `log.warning("ingestion_llm_unreachable", url=..., error=...)`
   - Scheduler läuft trotzdem; Items werden via `ExtractionTransientError`-Pfad retried.

Implementiert als Helper `check_ingestion_llm()` in `scheduler.py` (~25 Zeilen). Hard-Fail (Scheduler-Abort) wird **nicht** gemacht — selbst bei `model_mismatch` startet der Scheduler, damit andere Wartungs-Jobs (TLE-Update, Hotspot-Update) ohne LLM-Bedarf weiterlaufen können.

### 7. `.env.example`

Drei neue Variablen mit Spark-Defaults und einem Kommentar:

```bash
# Ingestion LLM (Spark — eliminates GPU swap on RTX 5090)
INGESTION_VLLM_URL=http://192.168.178.39:8000
INGESTION_VLLM_MODEL=google/gemma-4-26B-A4B-it
INGESTION_VLLM_TIMEOUT=120.0
```

### 8. `docker-compose.yml` — neues Profil `interactive-spark`

Neuer Service `data-ingestion-spark` (oder eleganter: `data-ingestion` bekommt zusätzlich Profil `interactive-spark`, Dependency auf `vllm-27b` wird via Override entfernt).

**Konkret — saubere Variante:** Zweiter Service-Eintrag `data-ingestion-spark`, identisch zu `data-ingestion` aber:
- `profiles: ["interactive-spark"]`
- Environment: `INGESTION_VLLM_URL=http://192.168.178.39:8000` (überschreibt `.env`-Default falls anders)
- `depends_on`: nur `redis`, `qdrant`, `neo4j`, `tei-embed` — **kein** `vllm-27b`
- Container-Name: `odin-data-ingestion-spark`

Duplikation ist akzeptabel (~30 Zeilen YAML), vermeidet Override-File-Komplexität.

### 9. `odin.sh` — neuer Modus `interactive-spark` + Stop-Updates

**Neuer Case:**
```bash
interactive-spark)
  "${COMPOSE[@]}" --profile ingestion --profile interactive --profile interactive-spark stop \
    vllm-27b data-ingestion 2>/dev/null || true
  echo "Starting INTERACTIVE+SPARK mode: 9B local + Ingestion via Spark"
  "${COMPOSE[@]}" --profile interactive-spark --profile interactive up -d --remove-orphans \
    "${CORE_SERVICES[@]}" "${INTERACTIVE_SERVICES[@]}" data-ingestion-spark
  ;;
```

**Bestehende Cases müssen ebenfalls angepasst werden**, damit ein Rückwechsel `data-ingestion-spark` sicher stoppt (sonst laufen zwei Scheduler parallel → doppelte Ingestion):

- `ingestion)`-Branch: `stop`-Liste erweitern um `data-ingestion-spark` und Profil `interactive-spark` mit `--profile`-Flags inkludieren.
- `interactive)`-Branch: `stop`-Liste erweitern um `data-ingestion-spark`.
- `down)`-Branch (falls vorhanden): inkludiert `--profile interactive-spark` damit auch `data-ingestion-spark` mit runterfährt.

Test (Bash-Integration, manuell oder in CI als Dry-Run): `up interactive-spark` → `up ingestion` → `docker ps | grep data-ingestion` zeigt nur **einen** Container.

Pre-flight-Check für `interactive-spark`: `curl -sf http://192.168.178.39:8000/v1/models > /dev/null || echo "WARN: Spark unreachable"` (nicht-blockierend).

`doctor` und `smoke` werden um den Spark-Reachability-Check erweitert.

## Datenfluss (geändert)

```
Feed → Collector → process_item ─HTTP→ Spark vLLM (Spark down → ExtractionTransientError → skip Qdrant)
                       │
                       ▼ (Erfolg)
                 Pydantic → Cypher Templates → Neo4j
                          → TEI Embed (lokal) → Qdrant
```

## Fehlerfälle

| Szenario | Verhalten |
|---|---|
| Spark offline beim Start | Warning-Log, Scheduler läuft, Collectors raisen ExtractionTransientError, Items übersprungen (kein Qdrant-Upsert), Retry beim nächsten Tick |
| Spark offline während Run | HTTPException → ExtractionTransientError → Item übersprungen, retry |
| Spark antwortet langsam | Timeout 120 s, dann ExtractionTransientError, retry |
| Modellname falsch (HTTP 404) | `ExtractionConfigError` → Item übersprungen, **kein** Qdrant-Upsert, Error-Log. Healthcheck loggt beim Start `ingestion_llm_model_mismatch` (wenn `/v1/models` 200 liefert aber Modell fehlt). Recovery: Config fixen, Items kommen beim nächsten Quellen-Tick erneut. |
| Auth-Fehler (HTTP 401/403) | Wie Modellname falsch — `ExtractionConfigError` |
| LLM liefert valides leeres Ergebnis | `other.unclassified`, gespeichert, kein Retry — wie bisher |

## Tests

**Unit (`tests/test_config.py`):**
- Spark-Defaults werden geladen
- Env-Override `INGESTION_VLLM_URL=http://x:9000` greift

**Unit (`tests/test_pipeline.py`):**
- `_call_vllm` ruft genau `http://192.168.178.39:8000/v1/chat/completions` (Regex-Assert: kein `/v1/v1`)
- Model im Payload ist `google/gemma-4-26B-A4B-it`
- Bei `httpx.ConnectError` → `ExtractionTransientError` raised
- Bei `httpx.HTTPStatusError 404/401/403` → `ExtractionConfigError` (kein Transient)
- Bei `httpx.HTTPStatusError 5xx` → `ExtractionTransientError`
- Bei Timeout → `ExtractionTransientError`

**Unit (`tests/test_rss_collector.py`):**
- Wenn `process_item` `ExtractionTransientError` raised → Item NICHT in Qdrant-Upsert-Liste
- Wenn `process_item` `None` returned → Item WIRD upserted mit `other.unclassified`
- Equivalent-Tests für gdelt/telegram/etc., die `process_item` aufrufen

**Unit (`tests/test_nlm_extract.py`):**
- `extract_with_qwen` ruft `{base_url}/v1/chat/completions` (Regex-Assert)
- Nutzt `ingestion_vllm_model`

**Unit (`tests/test_nlm_cli.py` falls vorhanden, sonst neu):**
- CLI ruft `extract_with_qwen` mit `settings.ingestion_vllm_url` (ohne `/v1`-Suffix)

**Healthcheck-Test (`tests/test_scheduler.py`) — drei Outcomes:**
- 200 + Modell in `data[].id` → Log `ingestion_llm_ready`
- 200 + Modell NICHT in `data[].id` → Log `ingestion_llm_model_mismatch` mit `expected` und `available` Feldern
- ConnectError/Timeout/Non-200 → Log `ingestion_llm_unreachable`
- Alle drei: kein Exception-Throw, Scheduler startet weiter

**Integration (Skip wenn Spark unreachable):**
- Smoke-Test: Echter `_call_vllm` gegen Spark, Response valides JSON-Schema

**Compose-Test:**
- `docker compose --profile interactive-spark config --quiet` läuft sauber
- `data-ingestion-spark` hat keine Dependency auf `vllm-27b`

## Rollout

1. Feature-Branch `feature/spark-ingestion-wiring`
2. TDD: Tests rot → Implementation → Tests grün
3. `./odin.sh up interactive-spark` — Pipeline manuell triggern
4. Auf Spark `docker logs vllm-gemma4 | tail` — bestätigen dass Requests reinkommen
5. Spark gezielt stoppen → bestätigen dass Items als pending übersprungen werden, nicht in Qdrant landen
6. Spark wieder hoch → bestätigen dass Items beim nächsten Tick extrahiert werden
7. Merge → Memory-Update (`project_spark_ingestion_offload.md` → done; `feedback`-Note über Retry-Pattern)

## Offene Punkte (Folge-Sprints)

- TEI auf Spark (ARM-Image)
- `/health/ingestion-llm`-Endpoint im Backend für Frontend-Status-Anzeige
- Prompt-Migration Qwen → Gemma falls Extraction-Qualität abweicht
- Optional: alten `up ingestion`-Modus deprecaten sobald Spark-Wiring stabil ist
