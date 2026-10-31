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
| Contact or satellite pick attempt loop | 45 s | Screenshot/readback, real input and identity assertion |
| Complete test, including context setup | 120 s | Browser setup and the entire interaction sequence |
| Complete suite | 20 min | All tests must execute and pass |
| GitHub browser job | 25 min | Installation, build, suite and evidence upload |

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
