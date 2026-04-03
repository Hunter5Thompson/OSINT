# Telegram Channel Collector + Vision Enrichment

**Date:** 2026-04-04
**Status:** Approved
**Author:** Claude / deadpool-ultra

## Overview

Konfigurierbarer Telegram-Channel-Collector für die ODIN Data-Ingestion Pipeline. Nutzt Telethon (MTProto) für vollen Channel-Zugriff, adaptives Polling, Media-Download und einen separaten Vision-Enrichment Service mit eigenem vLLM-Profil (Qwen2.5-VL-7B).

## Goals

1. Telegram-Channels als neue OSINT-Quelle in die bestehende Pipeline integrieren
2. Channel-Liste als YAML-Config — neue Channels ohne Code-Änderung
3. Bias-Labeling pro Channel (fließt in Knowledge Graph + Vector DB)
4. Media-Download mit asynchroner Vision-Analyse (On-Prem, kein externer API-Call)
5. Adaptives Polling basierend auf Channel-Aktivität

## Non-Goals

- Telegram Bot API (zu eingeschränkt für Channel-History)
- Echtzeit-Streaming via Telegram UserBot Events (zu fragil, Rate-Limit-Risiko)
- Vision-Analyse im Hot-Path der Ingestion (GPU-Profil-Konflikte)

---

## 1. Channel-Konfiguration

**Datei:** `services/data-ingestion/feeds/telegram_channels.yaml`

```yaml
channels:
  - handle: OSINTdefender
    name: "OSINT Defender"
    category: osint
    source_bias: neutral
    language: en
    priority: high
    media: true

  - handle: AuroraIntel
    name: "Aurora Intel"
    category: osint
    source_bias: neutral
    language: en
    priority: high
    media: true

  - handle: DeepStateEN
    name: "DeepState Map (EN)"
    category: conflict_ukraine
    source_bias: pro_ukrainian
    language: en
    priority: high
    media: true

  - handle: wartranslated
    name: "War Translated"
    category: conflict_ukraine
    source_bias: neutral
    language: en
    priority: medium
    media: false

  - handle: liveuamap
    name: "Liveuamap"
    category: conflict_global
    source_bias: neutral
    language: en
    priority: medium
    media: true

  - handle: CalibreObscura
    name: "Calibre Obscura"
    category: arms_tracking
    source_bias: neutral
    language: en
    priority: medium
    media: true

  - handle: rybar
    name: "Rybar"
    category: conflict_ukraine
    source_bias: pro_russian
    language: en
    priority: medium
    media: true
```

### Schema

| Feld | Typ | Required | Beschreibung |
|------|-----|----------|-------------|
| `handle` | string | ja | Telegram Channel-Handle (ohne @) |
| `name` | string | ja | Display-Name |
| `category` | string | ja | Thematische Kategorie (osint, conflict_ukraine, conflict_global, arms_tracking, etc.) |
| `source_bias` | string | ja | Bias-Label: `neutral`, `pro_russian`, `pro_ukrainian`, `pro_western`, `pro_chinese` |
| `language` | string | ja | ISO 639-1 Sprachcode |
| `priority` | string | ja | `high` (immer Basis-Intervall), `medium`/`low` (adaptiv) |
| `media` | bool | ja | Ob Medien heruntergeladen werden sollen |

---

## 2. Telegram Collector

**Datei:** `services/data-ingestion/feeds/telegram_collector.py`

### Telethon Session

- Session-File: `~/ODIN/odin-data/telegram/session.session` (Docker Volume)
- `api_id`, `api_hash` als Environment-Variablen (`TELEGRAM_API_ID`, `TELEGRAM_API_HASH`)
- Einmalige Authentifizierung beim ersten Start (interaktiv, Phone + Code)
- Session wird im Volume persistiert, überlebt Container-Restarts

### Adaptives Polling

- Basis-Intervall: 5 Minuten (konfigurierbar)
- APScheduler Job läuft alle 5min, Collector entscheidet pro Channel:
  - `priority: high` — wird immer gepollt
  - `priority: medium/low` — adaptiv:
    - Letzter Zyklus hatte neue Messages → Basis-Intervall (5min)
    - Kein neuer Content → Intervall verdoppeln (max 30min)
    - Neuer Content gefunden → zurück auf Basis-Intervall
- Activity-Timestamps pro Channel in Redis: `telegram:last_activity:{handle}`

### Message-Processing

- Jede Message → `process_item()` (bestehende Pipeline: vLLM Extract → Neo4j → Qdrant → Redis Stream)
- Deduplication: `SHA256(channel_handle + message_id)` — analog zu RSS content hash
- State-Tracking: `last_message_id` pro Channel in Redis (`telegram:last_msg:{handle}`)
- Grouped Messages (Telegram "Albums"): werden zu einem Item zusammengefasst (Text konkateniert, alle Media-Pfade gesammelt)
- Forwarded Messages: Original-Source wird als `forwarded_from` im Payload erfasst

### Payload (Qdrant + Neo4j)

```python
payload = {
    # Standard-Felder (wie RSS/GDELT)
    "source": "telegram",
    "title": first_line_or_channel_name,
    "url": f"https://t.me/{channel_handle}/{message_id}",
    "published": message.date.isoformat(),
    "codebook_type": str,           # vLLM-classified
    "entities": list,               # vLLM-extracted
    "ingested_at": datetime.utcnow().isoformat(),

    # Telegram-spezifisch
    "telegram_channel": channel_handle,
    "telegram_message_id": message_id,
    "source_bias": channel_config.source_bias,
    "source_category": channel_config.category,
    "forwarded_from": str | None,
    "has_media": bool,
    "media_paths": list[str],       # lokale Pfade
    "media_types": list[str],       # "photo", "video", "document"
    "vision_status": "pending" | "completed" | "skipped",
}
```

### Media-Download

- Speicherpfad: `~/ODIN/odin-data/telegram/media/{channel}/{message_id}/`
- Nur wenn `media: true` in Channel-Config
- Max Dateigröße: 20MB (konfigurierbar via `telegram_media_max_size`)
- Unterstützte Typen: Fotos, Videos, Dokumente (PDFs, etc.)
- Nach Download: Publish auf Redis Stream `vision:pending` (wenn Bild/Video)

---

## 3. Vision-Enrichment Service

**Verzeichnis:** `services/vision-enrichment/`

### vLLM-Profil `vision`

| Parameter | Wert |
|-----------|------|
| Modell | Qwen3-VL-8B-Instruct (FP16/BF16, kein AWQ nötig) |
| Container | `vllm-vision` |
| Port | 8011 |
| served-model-name | `qwen-vl` |
| VRAM | ~8 GB Modell + 1.7 GB TEI Embed = ~9.7 GB |
| Speed | ~187 tok/s auf RTX 5090 |
| Concurrency | Nicht concurrent mit Ingestion-27B, concurrent mit Interactive-9B möglich |

**Modellwahl-Begründung:** Qwen3-VL-8B (qwen3_vl Architektur, 8.8B params) ist neuer und schneller als Qwen2.5-VL-7B. Bei ~8 GB VRAM passt es ohne Quantisierung auf die 5090 mit genügend Headroom.

**Alternativen bei höherem Qualitätsbedarf:**
- InternVL3-14B (~10 GB Q4) — stärker bei OCR/Document Understanding
- InternVL3-38B (~22 GB Q4) — State-of-the-Art, aber braucht fast die ganze GPU

### Architektur

```
Telegram Collector (oder jeder andere Service)
       ↓
Redis Stream: vision:pending
  {channel, message_id, media_path, source_bias, source}
       ↓
Vision-Enrichment Service (Consumer Group)
       ↓
vLLM Qwen2.5-VL → strukturierte Bildbeschreibung (JSON)
       ↓
Neo4j: MATCH (d:Document {url: $url}) SET d.vision_description = $desc
Qdrant: Update payload mit vision_description
Redis: Publish auf events:enriched
```

### Vision-Prompt

```
Analyze this image from a geopolitical/military OSINT context.
Extract:
- scene_description: What is shown in the image
- visible_text: Any text, labels, watermarks visible
- military_equipment: Equipment types if identifiable (e.g., "T-72B3 tank", "HIMARS launcher")
- location_indicators: Any clues about location (signs, terrain, landmarks)
- map_annotations: If satellite/map image — marked areas, arrows, labels
- damage_assessment: If applicable — infrastructure damage, impact craters
Output as JSON.
```

### Queue-Mechanismus

- Redis Stream `vision:pending` mit Consumer Group `vision-workers`
- At-least-once delivery — idempotent writes (MATCH + SET, kein neuer Node)
- Pending messages überleben Service-Restart
- Backpressure: max 100 pending items, danach loggt Warning

### Wiederverwendbarkeit

Nicht nur für Telegram — jeder Service kann auf `vision:pending` publishen:
- RSS-Artikel mit Bildern (zukünftig)
- GDELT-Artikel mit Thumbnails (zukünftig)
- NotebookLM Screenshots (zukünftig)

---

## 4. Scheduler-Integration

### APScheduler Job

```python
scheduler.add_job(
    telegram_collector.collect,
    trigger="interval",
    minutes=5,
    id="telegram_collector",
    coalesce=True,
    max_instances=1
)
```

Adaptives Polling wird intern vom Collector gesteuert — der Job läuft alle 5min, der Collector entscheidet pro Channel ob tatsächlich gepollt wird.

### odin.sh Integration

```bash
odin telegram up|down       # Startet/stoppt data-ingestion mit Telegram-Support
odin vision up|down         # Startet/stoppt Vision-Enrichment Service + vLLM-Vision
odin doctor                 # Prüft auch Telegram-Session + Vision-Queue
```

---

## 5. Fehlertoleranz

| Szenario | Verhalten |
|----------|-----------|
| Channel gesperrt/offline | Warning loggen, Channel überspringen, nächsten Zyklus retry |
| Telethon Session expired | Error loggen, Healthcheck schlägt fehl, Alert |
| Telegram Rate Limit (FloodWait) | Telethon handled nativ — wartet automatisch |
| vLLM down | Graceful Degradation — Text+Embedding in Qdrant, kein Extract |
| Vision Service down | Media gespeichert, bleibt in `vision:pending` Queue |
| Redis down | Collector stoppt, Healthcheck failed |
| Channel postet kein Media | `vision_status: skipped`, kein Queue-Eintrag |

### Healthcheck

- Prüft: Telethon connected, Redis erreichbar, letzte erfolgreiche Collection < 1h
- Integriert in `odin doctor`
- Docker HEALTHCHECK im Container

---

## 6. Konfiguration

### Environment-Variablen (`.env`)

```bash
TELEGRAM_API_ID=12345678
TELEGRAM_API_HASH=abcdef1234567890abcdef1234567890
```

### config.py Erweiterungen

```python
telegram_api_id: int              # env: TELEGRAM_API_ID
telegram_api_hash: str            # env: TELEGRAM_API_HASH
telegram_session_path: str        # default: /data/telegram/session
telegram_media_path: str          # default: /data/telegram/media
telegram_media_max_size: int      # default: 20_971_520 (20MB)
telegram_channels_config: str     # default: feeds/telegram_channels.yaml
telegram_base_interval: int       # default: 300 (5min)
telegram_max_interval: int        # default: 1800 (30min)
vision_vllm_url: str              # default: http://localhost:8011
vision_vllm_model: str            # default: qwen-vl (Qwen3-VL-8B-Instruct)
vision_queue_max_pending: int     # default: 100
```

### Docker Compose Erweiterungen

```yaml
# Neue Volumes
volumes:
  telegram-session:
    driver: local
    driver_opts:
      device: ${ODIN_DATA_DIR:-~/ODIN/odin-data}/telegram/session
  telegram-media:
    driver: local
    driver_opts:
      device: ${ODIN_DATA_DIR:-~/ODIN/odin-data}/telegram/media

# data-ingestion: zusätzliche Mounts + Env
data-ingestion:
  volumes:
    - telegram-session:/data/telegram/session
    - telegram-media:/data/telegram/media
  environment:
    - TELEGRAM_API_ID=${TELEGRAM_API_ID}
    - TELEGRAM_API_HASH=${TELEGRAM_API_HASH}

# Neuer Service: Vision Enrichment
vision-enrichment:
  build: ./services/vision-enrichment
  profiles: ["vision"]
  volumes:
    - telegram-media:/data/telegram/media:ro
  environment:
    - VISION_VLLM_URL=http://vllm-vision:8011/v1
    - REDIS_URL=redis://redis:6379/0
  depends_on:
    redis: { condition: service_healthy }
    vllm-vision: { condition: service_healthy }

# Neuer Service: vLLM Vision
vllm-vision:
  image: vllm/vllm-openai:latest
  profiles: ["vision"]
  ports:
    - "8011:8000"
  volumes:
    - ${HF_HOME:-~/.cache/huggingface}:/root/.cache/huggingface
  deploy:
    resources:
      reservations:
        devices:
          - driver: nvidia
            count: 1
            capabilities: [gpu]
  command: >
    --model Qwen/Qwen3-VL-8B-Instruct
    --served-model-name qwen-vl
    --max-model-len 4096
    --gpu-memory-utilization 0.40
```

### Dependencies (pyproject.toml)

```toml
[project]
dependencies = [
    # ... bestehende deps ...
    "telethon>=1.36",
    "cryptg>=0.4",       # schnellere Telegram-Crypto
    "pyyaml>=6.0",       # bereits vorhanden
]
```

---

## 7. Datenfluss (End-to-End)

```
telegram_channels.yaml
        ↓
TelegramCollector.collect()         [5min APScheduler Job]
        ↓
    ┌── Für jeden Channel (adaptiv) ──┐
    │                                  │
    │  Telethon: get_messages()        │
    │  since: last_message_id          │
    │        ↓                         │
    │  Dedup: SHA256(handle+msg_id)    │
    │        ↓                         │
    │  Media Download (wenn enabled)   │
    │        ↓                         │
    │  process_item()                  │
    │    ├─ vLLM Extract (Qwen 27B)   │
    │    ├─ Neo4j Write               │
    │    ├─ Qdrant Upsert             │
    │    └─ Redis Publish             │
    │        ↓                         │
    │  Redis: vision:pending           │
    │  (wenn has_media)                │
    └──────────────────────────────────┘
        ↓ (async, entkoppelt)
Vision-Enrichment Service
        ↓
    vLLM Qwen2.5-VL-7B
        ↓
    Neo4j Update + Qdrant Update
        ↓
    Redis: events:enriched
```

---

## 8. Plattformrisiko-Mitigierung

Telegram hat im Juni 2025 OSINT-Channels ohne Vorwarnung gesperrt. Mitigierungen:

1. **Channel-Status-Tracking:** Collector trackt pro Channel ob erreichbar, loggt Ausfälle
2. **Graceful Skip:** Gesperrte Channels blockieren nicht den Rest
3. **Alerting:** Wenn >50% der Channels unerreichbar → Alert
4. **Keine Session-Sharing:** Eine Session pro Deployment, kein Multi-Device
5. **Rate-Limit-Compliance:** Telethon's eingebautes FloodWait-Handling, kein aggressives Polling
