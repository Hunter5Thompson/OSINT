# ADR-0001: API prefix consolidation to `/api`

**Date:** 2026-04-21
**Status:** Accepted
**Supersedes:** N/A

## Context

S1 shipped new endpoints (`/api/signals`, `/api/landing`) without the `/v1` suffix used by legacy routers (`/api/v1/flights`, `/api/v1/satellites`, …). Spec §5.1 explicitly mandates `/api/*` for all frontend calls. The current split is inconsistent and documented as F1 in the S1 review.

## Decision

1. Remount every router in `services/backend/app/main.py` at `prefix="/api"`.
2. Migrate the in-line `@app.get("/api/v1/health")` and `@app.get("/api/v1/config")` endpoints (defined directly on `app`, not on a router) to the canonical `/api/health` and `/api/config` paths via `add_api_route`.
3. Keep `/api/v1/*` aliases (for both routers and in-line endpoints) live for 30 days — transparent to external callers (Telegram links, test dashboards).
4. Frontend `services/api.ts`: change `BASE` from `/api/v1` to `/api`.
5. Frontend hardcoded callsites (grep: `SearchPanel.tsx`) flip to `/api/*` directly.
6. Schedule removal of `/api/v1` aliases for 2026-05-21.

## Consequences

- Frontend callsites using the `fetchJSON` helper (most `services/api.ts` exports) need zero change — the helper prepends `BASE`.
- Any frontend call that hardcodes `/api/v1/…` must be rewritten. Current hardcoded paths: `SignalFeedItem`-adjacent callers use `/api/signals/*` already at bare `/api`; SearchPanel needs the update.
- External API consumers have 30 days to migrate.
- WebSocket routers remain unchanged (no prefix on either side).
- Alias `add_api_route` uses `include_in_schema=False` to keep the OpenAPI surface clean.

## Rollback

Revert the `BASE` constant and the `/api/v1` aliases become authoritative again.
