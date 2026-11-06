# Source-grounded analysis optimization

Baseline: `999b4338063adc05750635e652ff4c2c76f9d74c`.
Evidence and operational handoff: `/data/odin-analysis-optimization/20261106/README.md`.
Status: deployed after explicit operator approval on 2026-11-06. Intelligence
source revision: `33349466fc59fc9c305cc8cab624065379f04b59`.
Automatic forecasts and external factual verification remain unqualified.

## Changes

The current report now audits attribution, action/terminology, polarity,
conditions, modality, time and inference separately. Conditional source/report
spans must match the supplied text. The comparison tolerates extraction-only
zero-width spaces and whitespace, while rendered originals remain unchanged.
A positive model verdict cannot authorize fabricated quotation spans or an
obviously unfinished sentence. The audit still cannot prove that the model
identified every relevant condition or attribution.

The blind second draft is replaced by one issue-directed repair of rejected
summaries. Accepted summaries and passage bindings cannot be changed by that
repair. Repairs undergo another source audit; unavailable or invalid repairs
leave the original quotation visible and the rejected summary withheld.

Source comparisons select actual finding pairs and one of four relation types.
There is no free prose field for additional causal or scenario premises. A
separate model call examines the original pair without seeing the proposed
relation. Server rules require compatible subject/time/condition judgments for
contradiction and agreement, and the same factual question for differing
assessments. A uniquely supported alternative can correct a proposed relation,
with partial coverage retained. With exactly two readings, an empty selection
can be checked once for a supported relation; unrelated material remains empty.
The renderer links the accepted summaries and their original evidence IDs and
identifies shared provenance. A method label is not independent verification.

All optional analysis shares a 100-second budget after initial source selection.
Cancellation propagates. Timeout retains the already accepted findings and
records unavailable comparison coverage. The existing overall query deadline
is unchanged. Source/model failures never authorize a summary or relation.

## Validation and limits

- 993 intelligence tests pass after `uv sync --locked --all-extras`; Ruff passes
  for `agents/`, `graph/`, and `tests/`. No dependency or API schema change.
- The original four-statement Iran audit failure was reproduced with the running
  Spark model. Baseline approved the dropped condition; the candidate rejected
  exactly that statement and accepted the other three.
- 18 additional source-audit controls: 9/9 faulty summaries rejected, 8/9 correct
  summaries accepted. The remaining false rejection is an invented abbreviated
  audit quote, not a wrong source statement. All failed experiments are retained.
- Seven relation controls: six expected outcomes; one conservative omission of a
  compatible pair. Its shared subject is underspecified. Do not turn this small
  set into a general accuracy or recall claim.
- Four frozen-source real-model report replays: two Iran packages, Ukraine, and
  irrelevant Taiwan material. Final deterministic relation rules were replayed
  against saved model responses, not misrepresented as a fresh provider run.
  Twelve original quotations match exactly; ten summaries and five comparisons
  remain visible; two summaries are withheld and Taiwan correctly abstains.
- The dropped Iran retaliation condition is repaired in the full report. Residual
  author/actor attribution ambiguity and false rejections remain. Relative event
  time and completeness still require review; no 48-hour forecast qualification.

Model-call durations for the four source-only v3 replays were 67.76, 73.35,
65.47 and 4.33 seconds. These exclude retrieval, ReAct, persistence and UI work.
The final postprocessing replay adds no new inference timing evidence.

## Session handoff

Changed: `agents/current_report.py`, `agents/source_check.py`, the new
`agents/source_comparison.py`, coverage propagation in `graph/workflow.py`, and
focused regression tests. Backend, frontend, lockfiles, models, Tavily credentials and
notebook archive are unchanged. Only the Intelligence container was replaced.

The main checkout under `/home` was not edited. Intelligence runs `3334946`;
backend and frontend retain `999b433`. The rollout changed only the Intelligence
image in the existing Compose context. No database work was performed.

Next quality work: atomic claim attribution with article context, measured
recovery of valid summaries, and independent factual/forecast evaluation. More
positive model self-checks alone do not close these acceptance boundaries.

## Approved rollout

The source commit existed before rollout. Fresh preflight verified clean source,
the pinned image, the existing container identity and a single rendered Compose
delta. The bounded command used `--no-deps --no-build --pull never intelligence`.
Docker reports healthy; Intelligence reports `3334946` and ready. Backend and
frontend return HTTP 200. All 76 other containers, including four retained backup
containers, match the preflight snapshot. The notebook archive hash is unchanged.

A controlled replay inside the deployed container matches the expected report
exactly: four findings, two comparisons, and the preserved retaliation condition.
This used captured model responses; it was not a fresh provider query or a
production dossier persistence test. Evidence and rollback are under
`/data/odin-analysis-optimization/20261106/release/33349466fc59/`.
