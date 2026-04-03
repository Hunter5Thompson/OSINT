# Container Status & Known Issues

> Last verified: 2026-04-03 (E2E Smoke Test)

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

### TEI Rerank (tei-rerank) — UNTESTED (Exited)

Last seen: `Exited (1)` — likely same sm_80/sm_120 issue as TEI Embed.

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
