# Signals Stream Contract

**Source of truth:** Redis Stream `events:new` (key defined by `settings.redis_stream_events` in `services/data-ingestion/config.py`).

**Producers (XADD):**
- `services/data-ingestion/pipeline.py` (all RSS/GDELT/UCDP/FIRMS/EONET/GDACS collectors funnel here)

**Consumers:**
- `services/backend/app/services/signal_stream.py` → SSE via `/api/signals/stream`
- `services/backend/app/routers/landing.py` reads the same source for last-24h counts

## XADD payload fields

| Field | Type | Example | Notes |
|---|---|---|---|
| `title` | str | `"Sinjar cluster expansion"` | Human-readable event title |
| `codebook_type` | str | `"signal.firms"` \| `"military.air_activity"` \| `"other.unclassified"` | Codebook type — **any taxonomy value**, see `services/intelligence/codebook/` |
| `severity` | str | `"low"` \| `"medium"` \| `"high"` \| `"critical"` | Used by frontend to map to dot color |
| `source` | str | `"firms"` \| `"ucdp"` \| `"gdelt"` \| `"eonet"` \| `"gdacs"` \| `"rss"` \| `"telegram"` | Origin collector |
| `url` | str | `"https://…"` | Source URL, empty string if not applicable |

Any additional producer-specific fields are passed through into `SignalEnvelope.payload` unchanged.

## SSE envelope (client-facing)

The backend wraps the Redis record into this envelope before streaming. The SSE `type` is the raw `codebook_type` — there is **no `signal.*` normalisation**; `military.air_activity`, `armed_conflict.skirmish`, etc. all come through unchanged.

```json
{
  "event_id": "<ms>-<seq>",
  "ts": "ISO-8601 UTC",
  "type": "<codebook_type>",
  "payload": { "title": "...", "severity": "...", "source": "...", "url": "...", ... }
}
```

- `event_id` encodes the Redis record ID for Last-Event-ID reconnect replay.
- `type` is routed as a named SSE event (e.g. `event: military.air_activity`); clients register per-type via `addEventListener(type, …)` or fall back to `onmessage` as an unfiltered wildcard.

## Replay contract

- Ring buffer: last 15 minutes
- Reconnect header: `Last-Event-ID`
- Query fallback: `?last_event_id=…`
- Beyond 15 min → server emits `event: reset`, clients re-hydrate from `/api/signals/latest`

## Adding a new signal type

1. Add a new codebook entry under `services/intelligence/codebook/`.
2. Ensure `pipeline.py` XADDs with that `codebook_type`.
3. No frontend change required — the wildcard listener in `useSignalFeed` accepts any codebook type. To opt into a named SSE event channel (rather than the generic `onmessage` stream), dispatch `new CustomEvent('signal-feed:register', { detail: { type: '<your_type>' } })` from application code.
4. Add a row to the table above.

## Testing

- Integration test (backend): `services/backend/tests/streams/test_signals_stream.py` — see §6.1 acceptance criteria in `docs/superpowers/specs/2026-04-14-odin-4layer-hlidskjalf-design.md`.
- Frontend test: `services/frontend/src/test/hooks/signalFeedWildcard.test.tsx`.
