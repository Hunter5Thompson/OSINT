# YouTube → NotebookLM → ODIN Knowledge Pipeline

## Use Case

Paywalled or video-only defense/intelligence sources (e.g., SUV Sicherheit & Verteidigung)
publish valuable analysis on YouTube but lock written content behind subscriptions.
NotebookLM acts as a knowledge distillation layer — processing public YouTube videos into
structured audio summaries that our NLM pipeline can ingest.

## Workflow

```
1. Source publishes YouTube video (public)
         |
2. User adds video URL as source in NotebookLM
         |
3. NotebookLM generates Audio Overview (podcast)
         |
4. odin-ingest-nlm export --id <notebook-id>
         |
5. odin-ingest-nlm transcribe --id <notebook-id>    (Voxtral)
         |
6. odin-ingest-nlm extract --id <notebook-id>       (Qwen + Claude)
         |
7. odin-ingest-nlm ingest --id <notebook-id>        (Neo4j)
         |
8. Entities, Claims, Relations in Knowledge Graph
   with full provenance (Source → Document → Claim)
```

## Parallel Signal: RSS Teaser

The RSS feed (`https://steady.page/de/suv/rss`) provides weekly teaser keywords
(weapon systems, budget figures, organization names) that are processed through the
standard RSS ingestion pipeline. These lightweight signals complement the deep
knowledge extracted via NotebookLM.

## Current Sources Using This Pattern

| Source | RSS (Teaser) | YouTube | NotebookLM |
|--------|-------------|---------|------------|
| SUV Sicherheit & Verteidigung | `steady.page/de/suv/rss` | Manual | Manual trigger |

## Steps for Adding a New Source

1. Find the YouTube channel
2. Create a NotebookLM notebook named after the source (e.g., "SUV KW14")
3. Add the YouTube video as a source in NotebookLM
4. Generate an Audio Overview
5. Run: `odin-ingest-nlm run --id <notebook-id>`
6. Verify: Check Neo4j for new Entities/Claims

## Future: Automation Options

- YouTube RSS feeds exist at `https://www.youtube.com/feeds/videos.xml?channel_id=CHANNEL_ID`
- Could auto-detect new videos and prompt user to add to NotebookLM
- NotebookLM API (if it ever supports programmatic source addition) would close the loop
