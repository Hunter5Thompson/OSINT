# Frozen source-reading qualification, 2026-11-06

These synthetic controls were frozen before evaluation. The evaluator passes only
opaque IDs, originals and translations/readings to the model; expected labels and
dimensions are withheld. Development and heldout results remain separate.

Acceptance for source interpretation: no altered meaning accepted; at least 90%
of faithful translations accepted. Qwen/Qwen3.8-27B at temperature 0 accepted
19/20 faithful controls and rejected all 20 altered controls on **each** split.
One faithful reading per split remained an explicit abstention. This is a bounded
model-assisted regression qualification, not independent human or factual review.

Relations require every control to match the expected relation or abstention,
with original quotations preserved exactly. The original development run passed
7/8: distinct docks were treated as unrelated and the comparison was withheld.
Adding an explicit `same_subject` dimension and distinguishing a shared operational
issue from identical assets passed 8/8 development, then 8/8 untouched heldout.
Agreement, contradiction and differing evaluations cannot bypass subject identity.
No comparison generates new factual prose; the renderer uses fixed relation labels.

Evidence (raw responses, hashes, timings, failed baseline retained):
`/data/odin-reliability-20261106/p4/`. Actual application query/save/reload checks
are a separate runtime gate and are recorded there after deployment.
