# Host full-text enrichment timer (operational bridge)

Keeps the RAG corpus full-text **going forward**: every hour, fetch the full text of any
new think-tank RSS teasers (crawl4ai/docling), chunk+embed, write `rss_fulltext`, supersede
the teaser. The one-time backfill (2026-06-05, 1053 articles) handled the existing corpus;
this keeps new articles from regressing to teaser-only.

## Why host-side (not the container scheduler)

`FulltextCollector` is gated behind `FULLTEXT_ENABLED` in the `data-ingestion-spark`
container, but that container is on `osint_default` and **cannot reach crawl4ai (:11235) /
docling (:5001)** — they run in separate compose projects, published only on the host.
From the host, `localhost:{11235,5001,6333,8001}` all work (the backfill path). So this
runs on the host until the proper fix lands.

**Target architecture (see TASKS.md):** attach `data-ingestion` to `crawl4ai_default` /
`docling_default`, set `CRAWL4AI_URL`/`DOCLING_URL` to the container names, flip
`FULLTEXT_ENABLED=true`, and retire this timer. Do it as a tested branch/PR, not ad-hoc.

## What's here

- `fulltext_enrich.sh` — runner: flock (no overlap) → dependency health gate (skips if
  qdrant/crawl4ai/docling/TEI down) → one bounded batch (`FULLTEXT_BATCH_SIZE`, default 10)
  under a hard 600s timeout. Never fails the unit; the next hourly fire retries.
- `odin-fulltext-enrich.service` — oneshot, `RuntimeMaxSec=900`.
- `odin-fulltext-enrich.timer` — `OnCalendar=hourly`, `Persistent=true`.

## Install (user units; linger already enabled, so no login needed)

```bash
mkdir -p ~/.config/systemd/user
cp ops/fulltext-enrich/odin-fulltext-enrich.{service,timer} ~/.config/systemd/user/
systemctl --user daemon-reload

# manual test run FIRST (verifies health gate + one batch):
bash ops/fulltext-enrich/fulltext_enrich.sh

# then enable + start the timer:
systemctl --user enable --now odin-fulltext-enrich.timer
systemctl --user list-timers odin-fulltext-enrich.timer
```

## Operate

```bash
systemctl --user status odin-fulltext-enrich.timer
journalctl --user -u odin-fulltext-enrich.service -n 50      # last run output
systemctl --user start odin-fulltext-enrich.service          # run now
systemctl --user disable --now odin-fulltext-enrich.timer    # stop the bridge
```
