"""Refuses to PASS Phase 0 unless artifacts exist, numbers are real, the
chosen renderer has no error in either timing run, and the chosen
renderer meets the Goal §3.1 latency budgets:

  - first_progress_ms (any run): <= 2000
  - first_frame_ms (30 Mbps run): <= 60000
"""
from __future__ import annotations
import json
import re
import sys
from pathlib import Path

DOCS = Path("docs/workflows")
SCREENSHOTS = DOCS / "recon-phase-0-screenshots"
SMOKE = DOCS / "recon-phase-0-smoke.md"
RESULTS = DOCS / "recon-phase-0-results.json"
RESULTS_30 = DOCS / "recon-phase-0-results-30mbps.json"

PROGRESS_BUDGET_MS = 2000
FRAME_BUDGET_30MBPS_MS = 60000

CHOSEN_RE = re.compile(r"Chosen renderer:\s*\*\*(spark|mkk)\*\*", re.IGNORECASE)


def fail(msg: str) -> "None":
    print(f"PHASE 0 GATE FAILED: {msg}", file=sys.stderr)
    sys.exit(1)


def main() -> int:
    # 1. Artifacts must exist
    for p in (SMOKE, RESULTS, RESULTS_30):
        if not p.exists():
            fail(f"missing artifact: {p}")
    for name in ("spark.png", "mkk.png", "reference.png"):
        if not (SCREENSHOTS / name).exists():
            fail(f"missing screenshot: {SCREENSHOTS / name}")

    text = SMOKE.read_text()

    # 2. Smoke doc must not contain placeholders
    placeholder_substrings = (
        "<from JSON>", "<from JSON-30>",
        "<one paragraph", "<YYYY-MM-DD>",
        "<browser + OS + GPU>",
        "Chosen renderer: **<", "Phase 0 verdict: **<",
        "<spark | mkk>", "<PASS|FAIL>", "<PASS | FAIL>",
        "<from JSON",  # catch any remaining angle-bracket JSON refs
    )
    for needle in placeholder_substrings:
        if needle in text:
            fail(f"smoke.md still contains placeholder {needle!r}; fill in real values")
    # Bare angle-bracket regex (catches anything like <foo bar>) as a final guard
    if re.search(r"<[A-Za-z][^>]{0,80}>", text):
        m = re.search(r"<[A-Za-z][^>]{0,80}>", text)
        fail(f"smoke.md still contains an angle-bracket placeholder: {m.group(0)!r}")

    # 3. Parse the chosen renderer
    m = CHOSEN_RE.search(text)
    if not m:
        fail("smoke.md does not declare 'Chosen renderer: **spark|mkk**'")
    chosen = m.group(1).lower()

    # 4. Numbers must be real for ALL renderers (so the comparison is honest)
    data = json.loads(RESULTS.read_text())
    data30 = json.loads(RESULTS_30.read_text())
    for label, src in (("no-throttle", data), ("30mbps", data30)):
        for r in ("spark", "mkk"):
            t = src[r]
            if t.get("error"):
                if r == chosen:
                    fail(f"chosen renderer {chosen!r} errored in {label}: {t['error']}")
                continue
            for k in ("first_progress_ms", "first_frame_ms", "total_ms"):
                v = t.get(k)
                if v is None or not isinstance(v, (int, float)) or v <= 0:
                    fail(f"{label}: {r}.{k} not measured (got {v!r})")

    # 5. Chosen renderer must hit the latency budgets (spec §3.1)
    #    first_progress_ms <= 2000 in *both* runs (spec: "any run")
    for label, src in (("no-throttle", data), ("30mbps", data30)):
        run = src[chosen]
        if run.get("first_progress_ms", 0) > PROGRESS_BUDGET_MS:
            fail(
                f"chosen renderer {chosen!r} {label} first_progress_ms="
                f"{run['first_progress_ms']:.0f} exceeds "
                f"{PROGRESS_BUDGET_MS}ms budget"
            )
    # first_frame_ms <= 60000 in the 30 Mbps run (spec: "on a 30 Mbps connection")
    chosen_30 = data30[chosen]
    if chosen_30["first_frame_ms"] > FRAME_BUDGET_30MBPS_MS:
        fail(
            f"chosen renderer {chosen!r} 30mbps first_frame_ms="
            f"{chosen_30['first_frame_ms']:.0f} exceeds "
            f"{FRAME_BUDGET_30MBPS_MS}ms budget"
        )

    # 6. Verdict must be PASS to count as PASS (PAUSE explicitly fails the gate)
    if "Phase 0 verdict: **PASS**" not in text:
        if "Phase 0 verdict: **PAUSE**" in text:
            fail("smoke.md declares PAUSE — phase 0 did not pass")
        fail("smoke.md does not declare 'Phase 0 verdict: **PASS**'")

    print(f"PHASE 0 GATE: PASS (chosen={chosen})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
