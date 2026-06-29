# Container Status & Known Issues

> Last verified: 2026-04-03 (E2E Smoke Test)

## Release Notes

### 2026-06-29 — Spark ingestion vLLM cut over to NVFP4

- The **Spark (DGX GB10) ingestion vLLM** (`data-ingestion-spark`, model
  `Qwen/Qwen3.6-35B-A3B`) now runs **NVFP4 (W4A16, modelopt)** on `vllm/vllm-openai:nightly`
  instead of BF16 on vLLM v0.19.0. **No ODIN change** — the new container serves under the
  same `--served-model-name Qwen/Qwen3.6-35B-A3B`, so `data-ingestion/config.py:ingestion_vllm_model`
  is unchanged.
- **Why:** blind pairwise A/B over 30 held-out Munin contexts showed **quality + faithfulness
  parity** (NVFP4 vs BF16, p≈0.5–1.0). NVFP4 frees ~44 GB UMA (KV cache 82 vs 38 GiB) and
  ~2.3× throughput on nightly.
- **Verified contract:** `response_format: json_schema` (strict guided decoding — the RSS/NLM
  extraction path) returns HTTP 200 + schema-valid on nightly+NVFP4; `/v1/models` reports the
  expected id (scheduler `check_ingestion_llm` passes). Re-run anytime:
  `python3 scripts/spark/verify_ingestion_contract.py`.
- **Requires vLLM nightly** — v0.19.0 cannot load the modelopt NVFP4 MoE
  (`KeyError: experts.w2_input_scale`). On GB10/sm_121 vLLM has no native FP4 compute yet →
  Marlin weight-only (W4A16) fallback; the memory win is real, the full speed win awaits
  sm_121 FP4 kernels.
- **Runbook + rollback:** `scripts/spark/odin-spark-vllm.sh {up|rollback|status|down|logs}`
  (installed on the Spark as `/home/albert/odin-spark-vllm.sh`). The old BF16 container
  `vllm-qwen36` is kept stopped (`restart=no`) as an instant rollback target.
- See the **Spark (DGX GB10) Ingestion vLLM** section below for the exact config.

### 2026-06-02 — Country Briefing (Munin) landed

- New backend status-SSE endpoints (require the **interactive vLLM 9B stack**, not
  the ingestion stack): `POST /api/almanac/countries/{id}/briefing` (streams a Munin
  situation briefing from the country's Almanac profile + matched live signals +
  ReAct/RAG/graph) and `POST /api/almanac/countries/{id}/briefing/save` (hydrates a
  lookup-or-create per-country dossier keyed by unique `scope_key`, appends a Munin
  chat message). Only `/briefing/save` is gated on `app.state.report_schema_ready`
  (returns 503 until the constraints are bootstrapped); `/briefing` (generate) is not
  gated and streams regardless.
- Startup now bootstraps two Neo4j constraints in the lifespan
  (`report_id_unique`, `report_scope_key_unique`); saves return 503 until ready.
- Grounding reaches the intelligence service via new `QueryRequest.grounding_context`
  + `grounding_evidence` (bounded/allowlisted) → ReAct seed + synthesis evidence.
  **The intelligence image must be rebuilt** (`docker compose build intelligence`)
  to activate grounding; the backend picks up the new routes via its mounted source
  on restart. Until the intelligence rebuild, briefings still stream (grounding is
  accepted but unused — graceful).
- Frontend: "§ Munin-Briefing erzeugen" block in `CountryAlmanacPanel` (generate →
  collapsed report → save to Briefing Room → dossier link).
- Spec: `docs/superpowers/specs/2026-06-01-country-briefing-design.md`.
- Plan: `docs/superpowers/plans/2026-06-01-country-briefing.md`.

### 2026-05-20 — Auto-Promoter v1 landed

- New backend lifespan task observes `/api/signals/stream` and promotes
  qualifying signals to incidents.
- Detectors enabled by default: FIRMS Geo-Cluster, Telegram Topic Cluster.
- Detectors default-off in v1: Severity Burst (waits on frontend `map:no_pin`),
  GDELT Tone Spike (waits on payload schema verification — see
  `services/backend/app/services/incident_promoter/detectors/gdelt.py`).
- Admin inspector: `GET /api/incidents/_admin/promoter` (behind `X-Admin-Token`).
- E2E test (mocked Redis XREAD → SSE assertion) deferred to a follow-up plan;
  integration coverage in `services/backend/tests/integration/test_promoter_pipeline.py`
  is the highest-level test in v1.
- Spec: `docs/superpowers/specs/2026-05-19-incident-auto-promoter-design.md`.
- Plan: `docs/superpowers/plans/2026-05-19-incident-auto-promoter.md`.

## LLM Inference Containers

### llama.cpp + Qwen3.5-27B-GGUF (Q6_K) — RECOMMENDED

**Status: WORKS. Cold start ~4s. Stable.**

```bash
docker run -d \
  --name qwen-llama \
  --gpus all \
  -p 8000:8080 \
  -v "$(cat <<'BLOB'
/home/deadpool-ultra/.cache/huggingface/hub/models--unsloth--Qwen3.5-27B-GGUF/blobs/69e0f8527e0d937097cbcd486b51e2effaed963f49ef7962c9ef3eab45164ff8
BLOB
):/models/model.gguf:ro" \
  ghcr.io/ggml-org/llama.cpp:server-cuda \
  -m /models/model.gguf \
  --host 0.0.0.0 --port 8080 \
  -ngl 99 -c 32768 --jinja -t 8
```

- **VRAM:** ~25 GB (model + KV cache)
- **Speed:** ~57 tok/s gen, ~318 tok/s prompt
- **API:** OpenAI-compatible at `http://localhost:8000/v1/chat/completions`
- **Model name in responses:** `model.gguf` (not `qwen3.5`)
- **Flags:** `--jinja` required for tool-calling, blob path required (HF symlinks don't work in Docker)

### vLLM + Qwen3.5-9B-AWQ (docker-compose vllm-9b) — WORKS (ReAct/Interactive)

**Status: WORKS. Cold start ~95s. Tool-calling verified.**

```bash
docker compose --profile interactive up -d vllm-9b
```

- **VRAM:** ~19 GB at 0.50 utilization
- **API:** OpenAI-compatible at `http://localhost:8000/v1/chat/completions`
- **Model name:** `qwen3.5`
- **Tool-calling:** `--enable-auto-tool-choice --tool-call-parser qwen3_coder`
- **Key flags:** `--limit-mm-per-prompt '{"image":0}'` disables vision profiling (prevents OOM)
- **max-model-len:** 8192 (sufficient for ReAct agent loops)
- **Known issue:** Qwen3.5 chat template requires a user message after ToolMessages. Fixed in `graph/workflow.py` by appending `HumanMessage("Continue...")` after tool results.
- **Fine-tuning option:** If 9B quality insufficient, fine-tune with Unsloth Studio for ODIN-specific tasks.

### vLLM + Qwen3.5-27B-AWQ (docker-compose vllm-27b) — BROKEN

**Status: BROKEN. Encoder cache profiling loop, never becomes healthy.**

The `vllm/vllm-openai:latest` image (v0.18.x) with Qwen3.5-27B-AWQ enters an infinite EngineCore restart loop during encoder cache profiling. The model loads (~18 GB), but the Vision encoder profiling step fails repeatedly with:

```
EngineCore failed to start.
Encoder cache will be initialized with a budget of 16384 tokens...
Available KV cache memory: -X.X GiB
```

This happens because vLLM v0.18 enables Vision/multimodal by default and profiles the encoder cache even for text-only models. The profiling consumes too much VRAM leaving negative KV cache budget.

**Root cause:** vLLM latest auto-enables vision pipeline for Qwen3.5 (which has vision capabilities). The encoder profiling reserves too much memory on a single 32GB GPU.

**Workaround:** Use llama.cpp with GGUF quantization (see above). Same model, faster startup, stable.

**Potential fix (untested):** Pin to an older vLLM version (e.g., v0.7.x) that doesn't have V1 engine or vision auto-detection, or use `--disable-mm-processor` flag if available.

### vLLM + Voxtral (docker-compose vllm-voxtral) — WORKS WITH TUNING

**Status: WORKS after config tuning. Cold start ~40s.**

```yaml
# docker-compose.yml (profile: notebooklm)
vllm-voxtral:
  image: vllm/vllm-omni:v0.18.0
  command: >
    vllm serve /models/voxtral        # MUST include 'vllm serve' prefix
    --served-model-name voxtral
    --tokenizer_mode mistral
    --config_format mistral
    --load_format mistral
    --gpu-memory-utilization 0.55      # 0.25 is NOT enough (model=9.3GB bf16)
    --max-model-len 16384             # 4096 too small (10min audio = ~7.5K tokens)
    --enforce-eager
    --port 8000
```

**Known gotchas:**
- `vllm serve` prefix required — the image has no entrypoint (null CMD)
- `gpu-memory-utilization 0.25` causes OOM (negative KV cache), needs at least 0.55
- `max-model-len 4096` causes "input too long" for 10-min audio chunks (~7.5K tokens), use 16384
- `verbose_json` response_format not supported — use default (plain text)
- Audio chunks must be < 100MB — export as mp3 (not WAV)
- **VRAM:** ~21 GB at 0.55 utilization — cannot run concurrent with Qwen

### TEI Embed (tei-embed) — WORKS

**Status: WORKS. Use sm_120 tag for RTX 5090.**

```
ghcr.io/huggingface/text-embeddings-inference:120-1.9
```

**CRITICAL:** `latest` tag is sm_80 and will crash on Blackwell GPUs. Always use `:120-1.9`.

### TEI Rerank (tei-rerank) — RUNTIME UNVERIFIED

The reranker is a custom CUDA 12.8 + PyTorch cu128 image from
`infra/docker/reranker`, not a TEI image. The old sm_80/sm_120 hypothesis was
incorrect; verify the active container separately with `./odin.sh smoke`.

### vLLM + Qwen3.6-35B-A3B NVFP4 on the Spark (DGX GB10) — ingestion backend

**Status: WORKS (production). Serves the `data-ingestion-spark` contract.**
**Host: Spark `192.168.178.39:8000` (NOT the local 5090). Cold start ~8 min (compile + FP4 autotune).**

Runs on the Spark, addressed by `data-ingestion-spark` via `INGESTION_VLLM_URL` /
`ingestion_vllm_model` (`http://192.168.178.39:8000`, model `Qwen/Qwen3.6-35B-A3B`). Started and
managed by `scripts/spark/odin-spark-vllm.sh` (installed on the Spark as `/home/albert/odin-spark-vllm.sh`):

```bash
docker run -d --name vllm-qwen36-nvfp4 --restart unless-stopped --gpus all -p 8000:8000 \
  -v /home/albert/.cache/huggingface:/root/.cache/huggingface \
  vllm/vllm-openai@sha256:907377dd...   `# :nightly pinned 2026-06-29` \
  --model nvidia/Qwen3.6-35B-A3B-NVFP4 \
  --served-model-name Qwen/Qwen3.6-35B-A3B \
  --quantization modelopt \
  --max-model-len 32768 \
  --gpu-memory-utilization 0.90 \
  --trust-remote-code
```

- **Why NVFP4:** parity with BF16 on quality + faithfulness (blind A/B, 30 held-out Munin
  contexts); frees ~44 GB UMA, ~2.3× throughput on nightly. (Nemotron-3-Super-120B was also
  A/B-tested and was statistically indistinguishable but 3.6× slower — not adopted.)
- **Contract (data-ingestion):** model name `Qwen/Qwen3.6-35B-A3B`; `response_format json_schema`
  strict; `chat_template_kwargs.enable_thinking:false`; temperature 0.1; max_tokens 2000 (RSS) /
  8000 (NLM). `4xx/422` → `ExtractionConfigError` (hard fail, no retry); `5xx/timeout/connect` →
  `ExtractionTransientError` (retry). **No tool-calling on this path** (JSON-schema only — tool
  calling is the local 9B's ReAct path).
- **Requires `vllm/vllm-openai:nightly`** (v0.23.1+) — v0.19.0 fails to load the modelopt NVFP4
  MoE (`KeyError: experts.w2_input_scale`). sm_121 has no native FP4 compute yet → Marlin W4A16
  fallback (memory win real; speed win partly from the newer vLLM).
- **Operate:** `odin-spark-vllm.sh up` (cutover → NVFP4), `rollback` (→ legacy BF16
  `vllm-qwen36`), `status`, `down`, `logs [container] [n]`. **One model at a time** (single GPU /
  unified memory). Prefix a mutating action with `--dry-run` to print the Docker commands
  without executing them.
- **Verify the contract anytime:** `python3 scripts/spark/verify_ingestion_contract.py`
  (replicates `pipeline.py:_call_vllm` + the scheduler `/v1/models` check).
- **Note:** independent of the local 5090 embeddings — `*_embed_failed` in ingestion logs means
  TEI / the 5090 is busy (e.g. Munin LoRA training), NOT a Spark issue.

## Infrastructure Containers

| Container | Status | Notes |
|-----------|--------|-------|
| `osint-neo4j-1` | WORKS | Neo4j 5-community, auth: neo4j/$NEO4J_PASSWORD from .env |
| `osint-qdrant-1` | WORKS | Port 6333/6334 |
| `osint-redis-1` | WORKS | Port 6379 |

## VRAM Budget (RTX 5090, 32 GB)

| Config | VRAM | Status |
|--------|------|--------|
| llama.cpp Qwen 27B Q6_K | ~25 GB | Stable |
| vLLM Voxtral (0.55 util) | ~21 GB | Stable |
| vLLM 27B-AWQ (0.55 util) | ~28 GB | BROKEN (profiling loop) |
| llama.cpp + TEI Embed | ~25 + 1.7 = ~27 GB | Should work |
| Voxtral + Qwen concurrent | ~21 + 25 = 46 GB | IMPOSSIBLE on single GPU |

**Rule:** Only one LLM at a time. Swap between them:
- `odin nlm up` / `odin nlm down` for Voxtral
- Manual `docker run/stop qwen-llama` for Qwen
