# munin-distill

Tooling for the Munin synthesis distillation pilot. See the spec/plan:
- `docs/superpowers/specs/2026-06-19-munin-synthesis-distillation-design.md`
- `docs/superpowers/plans/2026-06-19-munin-synthesis-distillation.md`

## Pipeline order

1. `query_gen` — build a diverse Munin query set from ODIN's taxonomy.
2. `harvest` — fire queries at the live intelligence service (`http://localhost:8003/query`,
   started with `DISTILL_CAPTURE_DIR` set) and collect the exact `(system, human)` synthesis inputs.
3. `teacher` — Opus generates the gold German Lagebericht from each captured pair.
4. `panel` — Munin blind judge (rubric + single-report scoring + content-based aggregation).
5. `filter` — layered quality filter (free heuristic gate + single-judge pass + dedup).
6. `dataset` — chat-JSONL builder, train/val split, context-only held-out, label-mask contract.
7. `eval_gate` — anchors + GO/NO-GO (hard faithfulness + injection-resistance sub-gates).
8. `train/train_munin_lora.py` — Unsloth **bf16** LoRA (run with the `~/unsloth_studio` venv, NOT repo uv).

Repo tooling is tested with `uv run pytest`. Heavy training deps live in the `~/unsloth_studio` venv;
the dataset JSONL is the handoff artefact. The trained adapter lands at `/models/lora/munin/`.
