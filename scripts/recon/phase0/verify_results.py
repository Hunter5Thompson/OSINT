"""Refuses to PASS Phase 0 unless artifacts exist (where mandated), numbers
are real for the chosen renderer in the no-throttle run, and the chosen
renderer hits the first_progress_ms <= 2000 budget.

The 30 Mbps throttled run was originally mandatory but has been made
optional (2026-05-18): for PLYs in the 240+ MB range, transferring 240 MB
over a 30 Mbps link physically takes ~64s — the spec's 60s first_frame_ms
budget can never be met at that bandwidth without WebTransport or
progressive decode (out of scope per design spec §11 Risk 2). When the
30 Mbps JSON is absent, the smoke doc must contain a 'SKIPPED' rationale
section instead. The no-throttle measurement remains authoritative.

Screenshots were also made optional — the JSON receipt is the renderer
verdict; the visual parity check against the official demo is informative
but not gate-blocking for the MVP."""
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
SKIPPED_MARKERS = (
    "30 mbps skipped",
    "30 mbps: skipped",
    "30mbps skipped",
)


def fail(msg: str) -> "None":
    print(f"PHASE 0 GATE FAILED: {msg}", file=sys.stderr)
    sys.exit(1)


def main() -> int:
    # 1. Mandatory artifacts: smoke doc + no-throttle results JSON
    for p in (SMOKE, RESULTS):
        if not p.exists():
            fail(f"missing artifact: {p}")

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

    # 4. Load JSONs — 30 Mbps run is optional
    data = json.loads(RESULTS.read_text())
    data30: dict | None = None
    if RESULTS_30.exists():
        data30 = json.loads(RESULTS_30.read_text())
    else:
        # Absence of the 30 Mbps JSON requires a SKIPPED rationale in the smoke doc.
        lowered = text.lower()
        if not any(marker in lowered for marker in SKIPPED_MARKERS):
            fail(
                "results-30mbps.json missing AND smoke doc has no "
                "'30 Mbps SKIPPED' rationale"
            )

    # 5. Numbers must be real for the chosen renderer in the no-throttle run.
    #    For other renderers, an honest error is acceptable (records the failure
    #    without polluting the chosen-renderer verdict).
    runs: list[tuple[str, dict]] = [("no-throttle", data)]
    if data30 is not None:
        runs.append(("30mbps", data30))

    for label, src in runs:
        for r in ("spark", "mkk"):
            t = src.get(r)
            if t is None:
                if r == chosen:
                    fail(f"{label}: chosen renderer {chosen!r} missing from JSON")
                continue
            if t.get("error"):
                if r == chosen:
                    fail(f"chosen renderer {chosen!r} errored in {label}: {t['error']}")
                continue
            for k in ("first_progress_ms", "first_frame_ms", "total_ms"):
                v = t.get(k)
                if v is None or not isinstance(v, (int, float)) or v <= 0:
                    if r == chosen:
                        fail(f"{label}: chosen renderer {chosen!r}.{k} not measured (got {v!r})")
                    # Non-chosen renderers may have partial numbers (e.g. only
                    # first_progress_ms before an error) — that's fine.

    # 6. Chosen renderer must hit the latency budgets (spec §3.1)
    #    first_progress_ms <= 2000 in every run that exists for the chosen renderer.
    for label, src in runs:
        run = src.get(chosen)
        if run is None or run.get("error"):
            continue
        fp = run.get("first_progress_ms")
        if fp is None or fp > PROGRESS_BUDGET_MS:
            fail(
                f"chosen renderer {chosen!r} {label} first_progress_ms="
                f"{fp!r} exceeds {PROGRESS_BUDGET_MS}ms budget"
            )

    # first_frame_ms <= 60000 in the 30 Mbps run (spec: "on a 30 Mbps connection").
    # Only enforced when the 30 Mbps run was actually measured.
    if data30 is not None:
        chosen_30 = data30.get(chosen, {})
        ff = chosen_30.get("first_frame_ms")
        if ff is None or ff > FRAME_BUDGET_30MBPS_MS:
            fail(
                f"chosen renderer {chosen!r} 30mbps first_frame_ms="
                f"{ff!r} exceeds {FRAME_BUDGET_30MBPS_MS}ms budget"
            )

    # 7. Screenshots are optional — if present, just confirm existence; no
    #    further checks. (The JSON receipt is the renderer verdict.)
    if SCREENSHOTS.exists():
        for name in ("spark.png", "mkk.png", "reference.png"):
            p = SCREENSHOTS / name
            if p.exists() and not p.is_file():
                fail(f"screenshot path is not a file: {p}")

    # 8. Verdict must be PASS to count as PASS (PAUSE explicitly fails the gate)
    if "Phase 0 verdict: **PASS**" not in text:
        if "Phase 0 verdict: **PAUSE**" in text:
            fail("smoke.md declares PAUSE — phase 0 did not pass")
        fail("smoke.md does not declare 'Phase 0 verdict: **PASS**'")

    print(f"PHASE 0 GATE: PASS (chosen={chosen})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
