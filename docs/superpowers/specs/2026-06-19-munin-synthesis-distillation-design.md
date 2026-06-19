# Munin Synthesis Distillation — Design Spec

**Date:** 2026-06-19
**Status:** Draft (pending user + Codex review)
**Author:** RT + Claude (Opus 4.8)

## 1. Context & Motivation

ODIN's interactive synthesis engine is the **Munin** agent (`services/intelligence/agents/synthesis_agent.py`):
a German-language intelligence-report synthesizer running on the local Qwen3.5-9B (AWQ, vLLM :8000).
It produces structured Lageberichte (Executive Summary / Key Findings / Threat Assessment label /
Confidence label / Recommended Actions) with a hard source-citation discipline (`(unverifiziert)`
markers, Quellenpflicht).

A controlled eval (2026-06-19, see `[[project_9b_synthesis_prompt_eval]]` + the `scripts_essay_9b*.py`
/ `scripts_judge_panel*.py` harness in `services/data-ingestion/`) established that the 9B's synthesis
quality gap to Opus 4.8 is **NOT promptable**:

- v1 "be bold" prompt → insight rose but **faithfulness collapsed** (blind 3-judge panel: 73% < 79% baseline).
- v2 "insight + faithfulness guardrails" → faithfulness recovered but only **≈ baseline** (78% ≈ 79%; Opus 90%).
- Dimensional truth: the 9B **cannot hold insight and faithfulness simultaneously** (zero-sum on a 9B);
  Opus holds both (faithfulness 9.3 + insight 8.9).

Conclusion: the ~11-point gap is a **capacity limit**, not an instruction-following gap. The one thing
prompting cannot buy — Opus-style "insight WITH discipline" — is exactly what **task-specific
distillation** teaches by example. This spec designs that distillation as a low-commitment pilot.

## 2. Goal & Success Criteria

**Goal:** distil Opus's Munin-Lagebericht behaviour into a LoRA adapter on Qwen3.5-9B, served only for
the synthesis path, so the local model gets meaningfully closer to Opus **without** sacrificing
faithfulness or harming the base model's ReAct/tool-calling job.

**Success bar (GO/NO-GO for deploy):**
- Distilled 9B closes **~half the gap** to Opus on the **Munin** rubric (roughly the midpoint between the
  measured Munin baseline-9B and Munin-Opus panel scores — concretely ~85% if the anchors land near the
  essay-proxy run).
- **HARD sub-gate:** faithfulness ≥ baseline-9B. Any faithfulness regression (worse `(unverifiziert)`
  discipline / source obligation) = automatic NO-GO regardless of other gains.

**Note:** all prior numbers were the English essay *proxy*. The Munin anchors (baseline-9B, Opus) must be
**measured first** on the Munin rubric — that is eval step 0, and it sets the concrete "halfway" target.

## 3. Non-Goals (YAGNI)

- Not distilling the English essay proxy (it was only a measurement instrument).
- Not a general/broad synthesis capability — Munin Lageberichte only.
- Not a full fine-tune — LoRA only, and **bf16 16-bit LoRA, not QLoRA/4-bit** (see §7 rationale).
- Not touching the ReAct/tool-calling path — the adapter is synthesis-only.
- Not training on the DGX Spark for the pilot (5090 chosen; Spark kept as fallback only).

## 4. Chosen Approach & Rejected Alternatives

**Chosen — A: Synthesis LoRA + Multi-LoRA serve.** One LoRA learning only Munin's synthesis behaviour;
served via vLLM `--enable-lora` so the base 9B keeps ReAct untouched and the synthesis_agent requests the
adapter by model name.

Rejected:
- **B — Merge + re-quantize a separate `qwen3.5-munin` AWQ model.** Same training pipeline; avoids the
  AWQ+LoRA serving-compat risk. **Kept as the explicit fallback** if the AWQ+LoRA compat spike fails —
  but B is **not** naive co-serving: two 9B-AWQ models alongside TEI + reranker almost certainly do not
  fit one 32 GB 5090. B must therefore run as one of: **(b1) swap-mode** (synthesis served only when the
  ReAct base is down — unacceptable for interactive use, pilot-only), **(b2) a dedicated synthesis-only
  server on the DGX Spark**, or **(b3) base+munin co-serve only if a VRAM-feasibility spike proves it fits**.
  The serve spike (§9) measures actual VRAM before B is committed.
- **C — No training: dynamic few-shot exemplar bank.** Cheapest, but circumvents (does not solve) the
  proven capacity limit and costs context tokens on every prod call. Rejected as primary.

## 5. Architecture & Data Flow

```
Query-Set → [Harvest] → Evidence contexts → [Opus teacher + real Munin prompt]
   → Gold Lageberichte → [Blind panel filter] → Dataset JSONL
   → [Unsloth bf16 LoRA on 5090] → munin adapter → [Eval gate GO/NO-GO] → [Multi-LoRA serve]
```

The blind judge panel pattern is used **twice**: as the training-data quality filter (step 4) and as the
eval gate (step 8), same rubric. **The harness must be built/parametrized for Munin first** — the existing
`scripts_judge_panel_stage.py` / `scripts_essay_9b*.py` are hard-wired to the English essay files,
NotebookLM paths, and essay staging. Only the *pattern* (blind staging → N independent judges →
content-based aggregation) is reusable; the Munin harness (Munin contexts, Munin rubric, Munin scoring)
is new code and an explicit pipeline step.

## 6. Data Pipeline

Cost falls in two places — teacher generation (step 3) AND the LLM judge in steps 4/8 (see cost model
below). Steps 1–2 are local/free.

1. **Query generation** *(local, free)* — ~400–600 diverse intelligence queries from ODIN's own taxonomy:
   `{entity} × {analytical template}` over countries, SUV.report defence companies (the SUV Track-2 graph
   entities), codebook event types (65+), recent incidents. Provides topic breadth without manual curation.
2. **Context harvest** *(local, free)* — run each query through the **existing** intelligence pipeline and
   capture the **exact `messages` passed to `llm.ainvoke()` at `graph/workflow.py:229`** — i.e. the
   `synthesis_sys()` system message AND the full assembled `HumanMessage`. That HumanMessage is NOT just
   evidence: it is `"Erstelle einen finalen Intelligence-Lagebericht…\nAnfrage: {query}\n\nRecherche-
   Ergebnisse:\n{research_text}"` + the inline 5-section instruction block, where `research_text` =
   grounding-pack + tool-results, joined and **clipped to `SYNTHESIS_RESEARCH_MAX_CHARS`**. Capturing at
   the `ainvoke` point guarantees training-input distribution = prod distribution (incl. the clip).
3. **Teacher generation** *(Opus — cost)* — Opus produces the German Munin Lagebericht per captured
   `(system, human)` pair, using the **exact prod messages from step 2**, so format, German,
   Threat/Confidence labels, and `(unverifiziert)` discipline match prod 1:1. Over-generate ~1.3× the target.
4. **Quality filter** *(layered, to bound cost)* —
   (a) **heuristic pre-filter** *(free)*: drop malformed gold (length out of range, missing any of the 5
   sections, missing a valid Threat/Confidence label, no citations) — cheap structural gate first;
   (b) **single-judge quality pass** *(LLM, bounded)*: one judge scores survivors on the Munin rubric;
   keep top ~300–400; drop near-duplicates. Only Opus's *best* outputs become training targets.
5. **Dataset** — chat-format JSONL `{system: synthesis_sys(), user: full assembled HumanMessage,
   assistant: gold report}` (i.e. the exact prod message pair, not just evidence), 90/10 train/val split.
   Plus **~30 held-out contexts** never in training → the eval gate.

**Cost model (explicit — judges are not free):**
- Teacher: ~450 Opus completions.
- Filter judge (step 4b): **1 judge pass** over survivors (~≤450 calls), not the 3-judge panel — bulk
  filtering does not need triple redundancy. Pick the judge model explicitly: **default = single Opus
  judge** (bounded API cost), **cheaper alternative = local 27B ingestion model** (no API cost, but needs
  a GPU swap to load). The 9B is too weak/biased to judge.
- Eval gate (step 8): the **full 3-judge blind panel** but only on the **~30 held-out** set (~90 calls) —
  small, so the expensive triple-redundant panel is affordable exactly where rigour matters.

**Cost envelope:** target ~350 filtered → ~450 generated; judge calls bounded as above. Narrow-domain
format/style distillation is data-efficient; a few hundred filtered examples is expected to suffice.

## 7. Training (Unsloth bf16 LoRA, RTX 5090)

- **bf16 LoRA, NOT QLoRA/4-bit.** The official Unsloth Qwen3.5 fine-tuning docs recommend **against**
  4-bit/QLoRA training for Qwen3.5 (larger quantization differences degrade quality) and support **bf16
  16-bit LoRA**. Since our bar is "the LoRA must be *good*", we use bf16 LoRA. Per Unsloth, a 9B bf16 LoRA
  needs **~22 GB VRAM** — fits the 32 GB 5090 with the interactive stack down. Sources:
  <https://unsloth.ai/docs/models/qwen3.5/fine-tune>,
  <https://unsloth.ai/docs/get-started/fine-tuning-llms-guide/lora-hyperparameters-guide>.
- **Env:** dedicated venv in `~/unsloth_studio` (Unsloth is deliberately isolated from system Python).
  Requires **transformers v5** (per the Unsloth Qwen3.5 docs — confirm exact version at setup). Training is
  **offline** while the interactive stack is down (one GPU swap; ~22 GB fits the 32 GB 5090).
- **Base:** Qwen3.5-9B **bf16** HF base weights — **not** 4-bit and **not** the AWQ artifact (AWQ is an
  inference quant only). Must be the same weights the AWQ was derived from, so the adapter applies to the
  serve base. **Record a base artifact manifest** (not just "same weights"): HF repo id, **revision/commit
  hash**, tokenizer files, and chat template — and verify the training tokenizer + chat template are
  byte-identical to what the served AWQ uses. A chat-template/tokenizer mismatch silently corrupts a
  LoRA-on-AWQ deployment.
- **LoRA config (starting point):** rank 16 (conservative vs overfit on ~350 examples), alpha = rank,
  target = all linear layers (q,k,v,o,gate,up,down), dropout 0, 2–3 epochs, lr 2e-4 cosine + warmup,
  `max_seq_len` ~8k (evidence bundles are long), bf16 + gradient checkpointing.
- **Assistant-only loss.** The dataset carries the exact prod messages, but loss is computed **only on the
  assistant output** — system/user tokens are masked. Use Unsloth `train_on_responses_only` (or TRL's
  conversational/prompt-completion format with chat-template application). Ship a **label-mask unit test**:
  system/user token labels == -100, assistant token labels != -100.
- **Pure synthesis adapter:** no tool-calling examples in the mix — the adapter is loaded only for
  synthesis; the base keeps ReAct. No forgetting risk by design.
- **Reproducibility pins (artifact):** record `unsloth`, `unsloth_zoo`, `transformers` (v5), Torch/CUDA,
  tokenizer + chat-template, and the SFT config/YAML. If Unsloth Studio is used, **export its training
  config as a run artifact**. See HF TRL SFTTrainer formats
  (<https://huggingface.co/docs/trl/sft_trainer>) and PEFT LoRAConfig
  (<https://huggingface.co/docs/peft/package_reference/lora>).
- **Export:** adapter safetensors → `/models/lora/munin/`.

Trade-off: start rank/epochs **conservative** — prefer slightly under-trained + iterate over overfitting
the small dataset.

## 8. Eval Gate (GO/NO-GO)

Uses the **new Munin panel harness** (built per §5, modelled on the essay-proxy panel pattern), with
**3 independent Opus judges** on the small held-out set.

- **Step 0 — measure anchors:** run the Munin-rubric panel on baseline-9B and Opus over the held-out
  contexts to establish the real anchors and the concrete "halfway" target.
- **Rubric = Munin** (not the essay proxy): faithfulness *incl. correct `(unverifiziert)` markers &
  source obligation*, Threat/Confidence calibration, coverage, insight, structure, German quality, and
  **injection-resistance** (see below).
- **Injection-resistance dimension (own risk):** the Munin system prompt treats evidence as untrusted and
  forbids executing instructions embedded in it. Distillation can dilute that. The eval set includes
  held-out contexts with planted instruction-injection in the evidence; the gate checks the distilled
  model still refuses to follow them. A regression here is a faithfulness-class NO-GO.
- **Blind + anchor-calibrated:** distilled-9B vs baseline-9B vs Opus on the ~30 held-out contexts.
  3 independent judges; **aggregate by described content, not by JSON label** (label-swap lesson from
  the essay-proxy round 2 — verify with grep on signature phrases).
- **Bar:** ~half gap closed (~85%) AND faithfulness ≥ baseline (hard) AND no injection-resistance regression.
- **NO-GO path:** if the first adapter misses the bar → iterate data (more / better-filtered) and
  hyperparameters (rank/epochs) *before* any deploy. No "deploy anyway".

## 9. Serve Path (Multi-LoRA) + Rollback

- **Compat + VRAM spike FIRST** (before training — de-risks the whole approach): bring up vLLM 9B (AWQ
  base) with `--enable-lora --max-lora-rank 32` + a throwaway dummy LoRA. Verify: (1) it loads & serves on
  the **AWQ base**; (2) per-request `model` routing (`qwen3.5` vs `munin`) works; (3) **measure VRAM**
  headroom (informs whether Fallback B's co-serve b3 is even possible). Yes → Approach A confirmed.
  No → switch to **Approach B** before investing training effort. Training is identical either way; only the
  last step differs. AWQ+LoRA serving is documented by vLLM (LoRA: <https://docs.vllm.ai/en/latest/features/lora/>;
  AWQ+LoRA example: <https://docs.vllm.ai/en/v0.6.1/getting_started/examples/lora_with_quantization_inference.html>).
- **Pin the vLLM image.** `docker-compose.yml` currently runs `vllm/vllm-openai:latest` — too volatile for
  a LoRA/AWQ deployment. After the spike, **pin the exact tested image tag + digest** in compose; record it
  in this spec's decisions log. Re-validate on any future bump.
- **Serving config:** `vllm-9b` command gains `--enable-lora --lora-modules munin=/models/lora/munin`
  (and `--max-lora-rank` matching the trained rank). The process then serves two names: `qwen3.5` (base) +
  `munin` (adapter).
- **Prod wiring:** new `settings.synthesis_llm_model` (default = `settings.llm_model`).
  `create_synthesis_llm()` uses it; on deploy → `"munin"`. `react_agent` stays on `qwen3.5`.
  One vLLM process: synthesis → LoRA, ReAct → base.
- **Rollback:** set `synthesis_llm_model` back to `"qwen3.5"` and drop `--enable-lora`. Fully reversible.

## 10. Risks & Mitigations

| # | Risk | Mitigation |
|---|------|-----------|
| 1 | vLLM **AWQ + LoRA** incompatibility (biggest) | Compat spike FIRST; fallback = Approach B |
| 2 | Blackwell sm_120 / Unsloth torch-CUDA + transformers-v5 quirks | 5090 chosen; pin transformers v5 + Torch/CUDA per Unsloth Qwen3.5 docs; DGX Spark fallback kept open |
| 3 | Opus teacher cost | Hard-bounded (~450 gen → ~350 filtered) |
| 4 | Overfit on small dataset | Conservative rank/epochs, val split, early stop |
| 5 | `(unverifiziert)` discipline lost (intel-safety core) | Teacher demonstrates it; panel faithfulness checks marker correctness; gate enforces no faithfulness regression |
| 6 | ReAct regression from `--enable-lora` | Base untouched, but flag changes serving → **mandatory ReAct smoke test** (tool-call still parses) |
| 7 | **Injection-resistance diluted** by distillation | Dedicated eval dimension (§8) with planted evidence-injection; regression = faithfulness-class NO-GO |
| 8 | vLLM `:latest` image volatility | Pin tested tag+digest after spike (§9); re-validate on bump |
| 9 | Fallback B not co-serveable on one 5090 | VRAM measured in the spike (§9); B runs as swap / Spark / verified co-serve (§4) |
| 10 | Tokenizer / chat-template mismatch (LoRA-on-AWQ) | Base artifact manifest + byte-identical template check (§7) |

## 11. Testing (TDD, per CLAUDE.md)

- Unit tests for the repo data-tooling: query-gen output schema; **harvest fidelity** (captured pair
  equals the exact `(system, HumanMessage)` at `workflow.py:229`, incl. the research-text clip); dataset
  builder (JSONL schema, train/val split, **held-out leakage check**); layered-filter logic (heuristic
  gate + threshold).
- Unit tests for the **new Munin panel harness** (blind staging, rubric scoring, content-based aggregation).
- **Label-mask test** (assistant-only loss): system/user token labels == -100, assistant labels != -100.
- ReAct smoke test after `--enable-lora`; injection-resistance check in the eval set.
- Eval gate = the integration test.
- New tooling dir → wire `.vscode` / keep the Test panel green (`[[feedback_tests_always_visible]]`).

## 12. Code Layout

- **In repo:** `training/munin-distill/` — query generation, context harvest (hooks the existing
  intelligence pipeline at the synthesis `ainvoke` point), dataset builder, the **new Munin panel harness**
  (built fresh on the essay-panel *pattern*; the essay `scripts_judge_panel*` are not reused as-is), and
  the training launcher.
- **Out of repo:** heavy Unsloth deps live in the `~/unsloth_studio` venv. The dataset JSONL is the
  handoff artefact between repo-tooling and the Unsloth env. The trained adapter lands at
  `/models/lora/munin/`.

## 13. Decisions Log

- Distill target = **real Munin German Lagebericht** (prod format), not the essay proxy.
- Training input = the **exact prod `(system, HumanMessage)` pair** captured at `workflow.py:229`, not raw evidence.
- Success bar = **~half gap closed (~85%)** with **faithfulness ≥ baseline + no injection-resistance regression** as hard sub-gates.
- Training on **RTX 5090** (Spark fallback only).
- Serve via **Approach A** (multi-LoRA on AWQ base); **B** as fallback, operated as swap / Spark / verified co-serve (not naive co-serve).
- **bf16 16-bit LoRA, NOT QLoRA/4-bit** (Unsloth Qwen3.5 docs: 4-bit not recommended; bf16 9B LoRA ~22 GB fits the 5090 w/ stack down); requires transformers v5; **assistant-only loss** (label mask).
- Synthesis-only adapter (ReAct untouched); not a full fine-tune.
- Judge cost model: layered filter (free heuristic + **single** judge) for bulk data; **3-judge** panel only on the ~30 held-out eval set. Judge model = single Opus (default) or local 27B (no-API alternative).
- **vLLM image pinned** (tag+digest) after the compat spike — recorded here once known: `TBD-after-spike`.
- Munin panel harness = **new code** on the essay-panel pattern (essay scripts not reused as-is).

## 14. Open Questions (for Codex review)

- Exact LoRA hyperparameters (rank 16 vs 32, epochs) — tune empirically against the gate.
- Whether direct Qdrant retrieval suffices for harvest or the full ReAct loop is needed for distribution
  fidelity on a subset.
- vLLM version's precise AWQ+LoRA support surface (resolved by the spike).
- Final filtered dataset size if ~350 under-delivers on the bar.
