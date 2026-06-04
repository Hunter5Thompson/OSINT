# Full-Text Fetch — Pinned Service Shapes (Task 1)

Verified live on 2026-06-03 against the running containers
(`crawl4ai-crawl4ai-1` :11235, `docling-docling-serve-1` :5001).
**These are the source of truth for Task 3** (`feeds/_fulltext_fetch.py`).
Where they differ from the plan's assumptions, the live API wins (noted below).

---

## crawl4ai — HTML → fit markdown

- **Endpoint:** `POST http://localhost:11235/md`
- **Request body:** `{"url": "<abs http/https url>", "f": "fit"}`
  - `f` (FilterType) defaults to `"fit"` (Readability-based clean extraction). Other modes: `raw`, `bm25`, `llm`. We use `fit`.
- **Response (HTTP 200) top-level keys:** `url`, `filter`, `query`, `cache`, `markdown`, `success`
  - **`markdown`** *(str)* — holds the fit-filtered markdown. **FLAT, top-level.**
  - `filter` *(str)* — echoes `"fit"`.
  - `success` *(bool)* — `true` on success.
  - There is **NO `fit_markdown` key** and **no nested `markdown.fit_markdown`** on this build (crawl4ai server). The content is the flat `markdown` string.

> **Task-3 impact:** the plan's `_CRAWL4AI_FIT_KEYS = ("fit_markdown", "markdown")` still works
> (falls through to `markdown`), but `fit_markdown` will never match — content is in `markdown`.
> Keep the tuple (harmless, future-proof) OR simplify to `("markdown",)`. Either is correct.
> The fit filter does **not** strip the site's nav/subscribe header (the WotR fixture begins with
> "When the world's at stake… National security. For insider…") — `clean_body` + the quality gate
> (min_chars / min_paras) handle residual boilerplate, exactly as the plan anticipates.

- **Fixture:** `crawl4ai_md.json` (real response, War on the Rocks article, ~19 KB, `markdown` len ≈ 18.8k chars).

---

## docling-serve — PDF → markdown

- **Endpoint:** `POST http://localhost:5001/v1/convert/source`
  - ⚠️ **CORRECTION vs plan:** the plan assumed `/v1alpha/convert/source`. The running
    docling-serve **1.12.0** exposes **`/v1/convert/source`** (sync). Use `/v1/convert/source`.
- **Request body:**
  ```json
  {
    "sources": [{"kind": "http", "url": "<pdf url>"}],
    "options": {"to_formats": ["md"]}
  }
  ```
  - ⚠️ **CORRECTION vs plan:** the plan assumed `{"http_sources": [{"url": ...}]}`. The real
    schema is **`sources`** (a discriminated union); each item needs **`kind: "http"`** + `url`
    (`HttpSourceRequest`). `kind` defaults to `"http"` but include it explicitly for the discriminator.
  - `options.to_formats: ["md"]` is enough. Defaults include `do_ocr:true` (only fires on
    image PDFs; born-digital reports skip it), `image_export_mode:"embedded"`,
    `include_images:true` → these embed base64 images and bloat the response. For our text-only
    use, the production fetch can pass `include_images:false` to slim payloads (optional).
- **Response (HTTP 200) top-level keys:** `document`, `status`, `errors`, `processing_time`, `timings`
  - **`document.md_content`** *(str)* — holds the converted markdown. ✅ matches the plan's
    `_DOCLING_MD_PATH = ("document", "md_content")`.
  - `document` also has: `filename`, `json_content`, `html_content`, `text_content`,
    `doctags_content` (the non-requested formats are null/empty when `to_formats:["md"]`).
  - `status` *(str)* — `"success"` on success. `errors` *(list)* — `[]` on success.
- **Sync vs async:** `/v1/convert/source` is synchronous and blocks until done (arxiv sample ≈ 6–8 s).
  Async variants also exist (`/v1/convert/source/async` → `/v1/status/poll/{id}` → `/v1/result/{id}`)
  but are **not needed** for our single-URL fetch. The collector's per-call httpx timeout must be
  generous (large reports take longer than HTML).

> **Operational note:** a probe against a live RAND report URL returned
> `{"detail": "Task result not found. Please wait for a completion status."}` — i.e. the source
> fetch/convert did not yield a sync result (likely the origin host blocking the server-side
> fetcher, or a slow/large doc). Real think-tank PDFs **will** fail sometimes; the collector must
> treat a missing/empty `document.md_content` or non-`success` `status` as **skip (None)** and any
> HTTP/transport error as **retry** — which the plan's `fetch_fulltext` already does
> (`_docling_md` returns None when the md path is absent; `httpx.HTTPError` re-raises → caller marks retry).

- **Fixture:** `docling_convert.json` (real response, arxiv `2206.01062` with `include_images:false`,
  ~52 KB, `document.md_content` len ≈ 51.5k chars, `status:"success"`).

---

## Summary for Task 3 (`_fulltext_fetch.py`)

| concern | use this (verified) |
|---|---|
| crawl4ai endpoint | `POST {crawl4ai_url}/md` |
| crawl4ai body | `{"url": url, "f": "fit"}` |
| crawl4ai md key | top-level `markdown` (str); `fit_markdown` absent |
| crawl4ai success flag | `success` (bool) — optional to check |
| docling endpoint | `POST {docling_url}/v1/convert/source` **(not `/v1alpha/...`)** |
| docling body | `{"sources": [{"kind": "http", "url": url}], "options": {"to_formats": ["md"]}}` **(not `http_sources`)** |
| docling md path | `document.md_content` (str) |
| docling success | `status == "success"`, `errors == []` |
