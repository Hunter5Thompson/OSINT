# Browser CI — built-SPA behavior gate

G03 now has a reproducible browser job for the built frontend. The isolated
goal worktree adds Playwright **1.64.0** as an exact development dependency;
only its three package nodes are new in the lockfile. Existing dependency
nodes and application source remain unchanged.

The job uses Node 22, `npm ci`, the matching Chromium, strict browser-test
TypeScript, an explicit spatial build argument and checkout revision. It builds
before testing and preserves JSON, screenshots and traces on failure. The
preview listener is private, strict-port and owned by the runner. The fixture
blocks external network providers and unexpected API requests/writes; it
records uncaught errors and the renderer actually observed from Cesium WebGL.
See [the operations contract](../operations/browser-smokes.md).

## Qualification and honest failures

- The initial CI-contract test was RED because the required browser job was
  absent. After adding the job, the contract and **97 whole ops tests** pass.
- Existing frontend qualification: **699 tests in 121 files** pass, along
  with ESLint, application/browser TypeScript and three build-metadata tests.
  The E2E directory is excluded from Vitest so the two runners do not collect
  one another's tests. The locked reinstall and clean-commit build/browser
  run have their own external logs and provenance checkpoint.
- Six behaviors were exercised in focused real-browser probes: Recon inactive,
  HTTP-503 recovery, malformed-response recovery, scope/time/layer/navigation,
  unknown aircraft and unknown vessel details. They use actual Cesium canvas
  rendering and mouse picks, without exposing the Viewer or rewriting source.
- Probe failures while authoring fixtures are not application regression REDs:
  missing ETags, a raw internal `feature_count: null` descriptor, an incorrect
  precision label, expecting a paused single step to enter replay, and clicking
  the transparent center of a direction-less ring. Screenshot review also
  caught a breadcrumb assertion matching a hidden country option. It now
  checks the actual `aria-current` breadcrumb: selecting Ukraine enters that
  scope; the top-level `/worldview` navigation remounts the global scope.
  Fixtures/expectations were
  aligned with the existing public contracts; application behavior was not
  weakened to fit the test. Strict TypeScript also caught tuple/nullability
  mistakes before browser execution.

Raw logs and artifacts are under
`/data/odin-goals/2026-10-09-repo-hardening/evidence/G03/`. Only the subsequent
external clean-commit checkpoint can identify the final source revision and
delivered build for the complete six-scenario run. Earlier builds bearing the
parent revision were compilation/probe inputs, not a new release identity.

## Remaining gates

This is a local software-rendering gate with synthetic providers. It does not
close remote CI, registry publication, live deployment, native GPU performance,
PLY/splat rendering, dense Globe usability, real analysis or human acceptance.
The newly recorded NPM audit findings are pre-existing transitive dependency
issues; no broad `audit fix` or production change was made. Their raw advisory
details are retained under G08 for separate compatibility-tested work.
