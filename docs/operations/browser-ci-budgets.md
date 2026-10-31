# Built-browser functional CI budgets

The browser job uses CPU-only SwiftShader. Its latency is not a native-GPU
performance measurement. Keep the real 1440 × 1000 viewport, real canvas picks,
source-identity checks, error assertions, single worker, zero retries and traces.

A two-core reproduction of the original GitHub failure showed a canvas screenshot
taking 21.7 seconds inside a 15-second `expect(...).toPass()` callback. The retry
deadline expired before the first attempt could click the painted contact. The
asynchronous attempt then continued while fixture teardown had already started.
Remote traces also show context creation taking 28–32 seconds and individual
screenshots taking 13–27 seconds. The old 60-second case budget included these
operations as well as navigation, assertions and source recovery.

The corrected budget hierarchy is:

| Scope | Budget | Purpose |
|---|---:|---|
| Ordinary DOM assertion | 15 s | Unchanged visible-state assertions |
| Viewer initialization after navigation | 45 s | Software WebGL context creation and remount |
| Contact or satellite pick attempt loop | 90 s | Screenshot/readback, real input and identity assertion |
| Complete test, including context setup | 180 s | Browser setup and the entire interaction sequence |
| Complete suite | 30 min | All tests must execute and pass |
| GitHub browser job | 35 min | Installation, build, suite and evidence upload |

These are functional-test deadlines, not product latency or FPS acceptance
thresholds. Native G07 frame-rate, regression and human-review requirements remain
separate and unchanged. A local browser pass does not replace the GitHub run.

Reproduce the software-renderer constraint from `services/frontend` after the
locked install and build, using two CPU cores allowed on the host:

```bash
taskset -c 0,1 npm run test:browser
```

Record the build revision and preserve the JSON report, screenshots and traces.
Do not reuse a result for a different frontend tree or silently skip slow cases.

Earlier slices also used fixed-offset clicks during the camera flight. Backport
the final slice's painted-pixel and exact source-identity picking assertions so
the test waits for its real target instead of cancelling the moving camera.

The first corrected remote run measured a 32.1 s canvas screenshot followed by
a 31.3 s locator click. Locator actionability waits for additional stable frames;
a measured fixed canvas and painted pixel can instead receive real mouse input
directly. The loop still verifies the exact source identity. Its 90 s allowance
permits a second slow screenshot when the first precedes the camera landing.
Remote scope navigation also reached 120 s, hence the 180 s complete-case budget.
