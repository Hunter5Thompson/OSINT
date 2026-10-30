# GP browser clock diagnosis — 2026-10-30

The original GP100651 built-browser test reproduced the same Cesium RangeError
and render abort in one of five fresh repetitions; four passed. Raw evidence:
`/data/odin-plan-20261030/evidence/browser-red-repeat-2/`.

Cesium's actual camera controller reads new Date() for inertia decay. A frozen
Date probe retained identical wheel motion (-117.8097245) while camera height
increased to119,148,042m. Advancing wall time decayed the same controller's motion
to about0.000035 and stabilized height at1,706,610m. These are test camera
observations, not satellite positions or a general mathematics qualification.

Playwright's full clock also replaces native RAF, performance and timers.
Changing system time alone left hover/pick/readback timeouts. A small contract
first failed in88ms because requestAnimationFrame was a ClockController wrapper.
The deterministic failure identifies render timing coupling without relying on
a flaky RangeError. The installed Playwright source confirms the replacement.

The harness now controls Date only and preserves native RAF/timers/performance.
It starts at the source epoch, pauses simulation through the public control,
then resumes advancing Date for camera input. Constructor arguments preserve
native behavior. The displayed simulation cursor must remain fixed while Date
advances. Existing real canvas picking, exact six-digit ID, source coverage,
orbit screenshot and route-remount assertions remain. No Viewer hook, shader,
library or application edit, skipped assertion, increased timeout or retry.

GREEN: timer/date contract and actual GP case passed; GP then passed five fresh
consecutive runs with zero retries/skips. Evidence: browser-date-only* and
native-timer-contract-red. Final complete suite/native-platform gates follow.

Rejected attempts remain: Playwright clock progression, hover/wheel staging,
experimental screenshot picking, CDP frustum probes and explicit ellipse height.
The ellipse change did not resolve the failure and was reverted. Diagnostic
instrumentation was removed from repository code. Failed attempts remain raw
artifacts and are not counted as passing application gates.

This fixes the known harness failure. It does not prove every possible Cesium
RangeError impossible or provide deployment/live-source/native-performance/
human acceptance. An initial final-run wrapper used incorrect relative Git/doc
paths from the service directory; it was stopped and is retained as an invocation
failure. Only the clean committed-head rerun may qualify the final suite.
