# YouTube → NotebookLM → ODIN Knowledge Pipeline

## Use Case

Video-only defense/intelligence sources publish valuable analysis on YouTube that has no
written equivalent. NotebookLM acts as a knowledge distillation layer — processing public
YouTube videos into structured audio summaries that our NLM pipeline can ingest.

> **Note:** SUV Sicherheit & Verteidigung's *written* fachbeiträge are now ingested
> directly as full text (`suv.report/category/fachbeitraege/feed/` → `rss_fulltext`, see
> `THINKTANK_FEEDS`). This pipeline now covers only its video-only/podcast material.

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
7. odin-ingest-nlm ingest --id <notebook-id>        (Neo4j + Qdrant)
         |
8. Entities, Claims, Relations in Knowledge Graph
   with full provenance (Source → Document → Claim)
```

## Multi-Source Extraction (transcript + reports)

`extract`/`ingest` process **every** source of a notebook, not just the podcast
audio: the transcript **and** each NotebookLM-generated written report. Each source
is extracted independently and carries `source_kind` (`transcript` | `report`) and
`source_id` provenance — distinct `EXTRACTED_FROM` edges in Neo4j and one Qdrant
point per claim in `odin_intel`. The extraction prompt is source-agnostic
(`extraction_v3.txt`, the default): it injects a dynamic hint so the model knows
whether it is reading a podcast transcript or a written report. `v1`/`v2` remain
available for rollback.

## Parallel Signal: RSS Full Text

SUV's written analysis is ingested directly from its own full-text feed
(`https://suv.report/category/fachbeitraege/feed/`) through the standard RSS pipeline and
enriched to `rss_fulltext` (see `THINKTANK_FEEDS`), grounding briefings on the full article
body. The NotebookLM path below complements this with video-only/podcast content.

## Current Sources Using This Pattern

| Source | RSS | YouTube | NotebookLM |
|--------|-----|---------|------------|
| SUV Sicherheit & Verteidigung | `suv.report/…/fachbeitraege/feed` (full text → `rss_fulltext`) | Manual | Manual trigger |

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
