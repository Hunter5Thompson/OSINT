# WorldView Declutter P1 — Explicit Render + Label Budget Pilot

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop the WorldView globe repainting when nothing moves, and introduce one collective, altitude-aware label budget — measured against the incumbent per-layer mechanism first, proven on two pilot layers, with everything else named as follow-up rather than claimed as done.

**Architecture:** Three phases. **Phase 0** measures what the current label system actually does across the five altitude bands, because every design choice in Phase B depends on it and none of it is currently known. **Track A** moves Cesium into explicit-render mode — a scene-wide switch, so it installs LAST, after every scene-mutating site requests frames. **Track B** replaces per-layer label caps with one collective budget: `labelBudget.ts` (altitude × density → one cap), `labelQuota.ts` (split across layers), `labelArbiter.ts` (which labels, collision-resolved, hysteresis-stabilised, pure), and `useLabelArbiter.ts` (the React seam, which owns **all** world→screen projection so no layer can ever submit a stale rectangle).

**Tech Stack:** React 19, TypeScript 5.7 (strict, no `any`), Vite 6, CesiumJS 1.142.0 (pinned), Vitest 4, @testing-library/react 16.

**Spec:** `TASKS.md:1475` — TASK-114. This implements the render + label portion of P1. P0 (viewport culling, `NearFarScalar` fades, `lib/lod.ts`) shipped via `docs/superpowers/plans/2026-06-06-worldview-declutter-p0.md`.

**Base:** Branch off `origin/main` (`9ee06cc` or later) in a fresh worktree.

**Provenance:** Adapts designs from `bilawalsidhu/gods-eye-view` @ `880a672b5e16ad3e41d318801d3a5203f9201923`, MIT, Copyright (c) 2026 Bilawal Sidhu. Task 0 installs the full licence before any adapted code lands.

---

## The measurement that gates this plan

**Every label-bearing layer in ODIN caps its labels with a `DistanceDisplayCondition`.** Verified at `9ee06cc`:

| Layer | Cap (camera→object, metres) | Line |
|---|---|---|
| EONET | 5 000 000 | `EONETLayer.tsx:169` |
| Cable | 5 000 000 | `CableLayer.tsx:192` |
| Pipeline | 3 000 000 | `PipelineLayer.tsx:181` |
| Datacenter | 5 000 000 | `DatacenterLayer.tsx:157` |
| Refinery | 5 000 000 | `RefineryLayer.tsx:176` |
| Event | 2 500 000 | `EventLayer.tsx:252` |
| GDACS | 5 000 000 | `GDACSLayer.tsx:169` |
| Earthquake | 5 000 000 | `EarthquakeLayer.tsx:153` |

There is **no label layer without one.** That makes the DDC the incumbent declutter system — a coarse, per-layer, uncoordinated version of exactly what this plan's budget provides. Two consequences the plan must not assume its way past:

1. A `DistanceDisplayCondition` is **not** a camera-altitude guard. It compares camera-to-*object* distance. At an oblique angle the near edge of the viewport is inside the cap while the far edge is outside. Any plan text calling it an "altitude early-out" is wrong.
2. Above roughly 5 000 km, ODIN may draw **no labels at all, from any layer**. If so, the `global` and upper-`regional` rows of any budget matrix govern an empty set — and the TASK-114 screenshot that motivates this whole ticket is a globe view.

**Task 1 measures this before anything in Track B is built. Task 10 is the decision point it feeds.** Nothing between them may assume an answer.

---

## What this plan does NOT deliver

Stated up front so the PR cannot be mis-sold:

- **Not a globally arbitrated label scene.** Two pilot layers (Earthquakes, GDACS). Six label layers keep current behaviour.
- **Not idle rendering in the default view.** `DEFAULT_LAYERS` (`WorldviewPage.tsx:133`) ships **eight** entries `true` — `flights`, `satellites`, `earthquakes`, `countryBorders`, `cityBuildings`, `firmsHotspots`, `milAircraft`, `recon` — of which `flights`, `earthquakes`, `firmsHotspots` and `milAircraft` all own per-frame animators, so each takes a continuous-render hold while visible. The idle win is real but only materialises when the animated layers are off. The 30-second measurement in Task 4 is a laboratory case, not the default experience. Reducing holds to "only while something actually moves" (e.g. FIRMS holding with an empty pulse list) is follow-up.
- **Not correct sun/terminator animation in idle.** `GlobeViewer.tsx` sets `enableLighting = true`, and the governor sets `maximumRenderTimeChange = Infinity`. In idle the terminator and the photoreal night shader stop advancing until some other event requests a frame. Over minutes this is visible. Accepted for P1; the fix is a low-frequency time-driven request, not in scope.
- **Not label fade.** Deliberate: a fade needs a per-frame animator, which under Track A means a continuous-render hold.
- **Not a density UI control.** The module supports the five stops; the control is a design task.
- **`EventLayer` is explicitly NOT a pilot.** `EventLayer.tsx:236` sets `shouldLabel = placement.stackIndex === 0 && getTimeMsRef.current == null`, and `WorldviewPage.tsx:419` (`EventLayerBridge`) always supplies `getTimeMs`. In production that layer renders zero labels. Wiring it would be an untestable no-op. Changing that suppression is a recorded product decision, out of scope.

---

## Global Constraints

- **Third-party licence:** adapted modules carry the Task 0 pointer header verbatim. Full MIT text in `LICENSES/gods-eye-view-MIT.txt`, indexed by `THIRD_PARTY_NOTICES.md`. No adapted module lands before Task 0.
- **No Cesium Entity API for bulk rendering** — imperative collections only. (CLAUDE.md hard rule.)
- **No `any` types anywhere, tests included.** Where a test needs a partial Cesium object, define a structural interface and have production code accept it. A test reaching for `as any` means the production signature is too wide.
- **Label/LOD rebuilds run on `camera.moveEnd` (debounced), never per-frame, never on `camera.changed`.** (TASK-114 invariant.)
- **Do not replace `PerformanceGuard`** (`components/globe/PerformanceGuard.tsx`); build alongside it.
- **Hlíðskjalf Noir** is the committed design system. This plan changes how many labels are drawn, never their colours or typography.
- **TDD, strictly.** Every task writes its failing test before the code it tests — including the layer-wiring tasks, which is where the previous two revisions of this plan failed review.
- **Verify before asserting.** No step may claim behaviour of existing code without a file:line reference. If a step needs a fact that is not yet established, it measures it.
- Commands, from `services/frontend`: `npm test` · `npx vitest run <path>` · `npm run type-check` · `npm run lint` · `npm run build`.

---

## File Structure

**Create:**

| File | Responsibility |
|---|---|
| `LICENSES/gods-eye-view-MIT.txt`, `THIRD_PARTY_NOTICES.md` | Third-party licence (repo root). |
| `docs/reports/2026-08-25-task-114-label-baseline.md` | Task 1 measurement output. |
| `services/frontend/src/lib/renderGovernor.ts` (+ test) | Ref-counted holds; owns `scene.requestRenderMode`. |
| `services/frontend/src/lib/labelBudget.ts` (+ test) | Altitude → view scale, density stops, collective budget matrix. Pure. |
| `services/frontend/src/lib/labelQuota.ts` (+ test) | Work-conserving split of one capacity across layers. Pure. |
| `services/frontend/src/lib/labelArbiter.ts` (+ test) | Collision grid, per-layer priority normalisation, hysteresis, lending. Pure. |
| `services/frontend/src/hooks/useLabelArbiter.ts` (+ test) | React seam. Owns projection, coalesced solve, `submit`/`remove`. |
| `services/frontend/src/components/globe/__tests__/renderRequestCoverage.test.ts` | Static coverage gate over **all** scene-mutating sites. |

**Modify:**

| File | Change | Task |
|---|---|---|
| `components/layers/MilAircraftLayer.tsx:157` | Gate the `clock.onTick` effect on `visible`; hold `"milair-tick"`. | 3 |
| 14 further `components/layers/*.tsx` | `governorRequestRender` after each mutation; holds on the four other animators. | 3 |
| `components/globe/visual-layers/Graticule.tsx:48` | Request a frame after `primitives.add`. | 3 |
| `components/globe/spotlight/SpotlightOverlay.tsx:102,109,154` | Request frames; **scoped hold for the 320 ms / 200 ms `preUpdate` fade**. | 3 |
| `components/globe/spotlight/CapitalPulse.tsx:45` | `preUpdate` DOM projection stops firing in idle — hold while active. | 3 |
| `components/globe/GlobeViewer.tsx:81,83,131,201,207` | Request frames on tileset/border `.show` and `primitives.add`. | 3 |
| `spatial/cesium/CesiumSpatialScopeAdapter.ts:64,108,349–522`, `buildScopePrimitives.ts:189,197` | Request frames on scope primitive `.show` / `add`. | 3 |
| `components/globe/GlobeViewer.tsx:164` | Install the governor (LAST step of Track A). | 4 |
| `components/layers/EarthquakeLayer.tsx` | Pilot: arbiter-gated labels. | 9 |
| `components/layers/GDACSLayer.tsx` | Pilot: arbiter-gated labels. **No viewport culling** — the hook owns that (Task 8). Rank-cap the submitted set (300) so projection stays bounded. | 9 |
| `pages/WorldviewPage.tsx` | Create the arbiter (page level); drill through `GlobeChildren`. | 9 |
| `TASKS.md` | Status. | 11 |

**Explicitly NOT in the coverage set:** `components/globe/GoogleTiles.tsx` — dead code, imported nowhere (verified: `grep -rn GoogleTiles src` finds only its own definition). The live photoreal path is `Cesium3DTileset.fromIonAssetId` inside `GlobeViewer.tsx`.

---

## Task 0: Third-party licence

**Files:** Create `LICENSES/gods-eye-view-MIT.txt`, `THIRD_PARTY_NOTICES.md`.

**Interfaces:** Produces the pointer header every adapted module must carry, verbatim:
```
/**
 * Adapted from God's Eye View, commit 880a672b5e16ad3e41d318801d3a5203f9201923
 * Copyright (c) 2026 Bilawal Sidhu. MIT License — full text in
 * LICENSES/gods-eye-view-MIT.txt. See THIRD_PARTY_NOTICES.md.
 */
```

**Why:** a header saying "the MIT permission notice shall be included" without including the grant or disclaimer does not satisfy MIT. Pointer headers plus one canonical full text is the standard discharge and survives file moves.

- [ ] **Step 1: Write `LICENSES/gods-eye-view-MIT.txt`**

Header naming the project, the pinned commit, and the four adapted ODIN paths; then the complete MIT body (`MIT License` … `OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.`); then this note:

```
NOTE: upstream's LICENSE carves out third-party DATA and 3D models from the MIT
grant. ODIN adapts SOURCE CODE ONLY — no upstream dataset, texture, or model is
used, so that carve-out does not apply here.
```

- [ ] **Step 2: Write `THIRD_PARTY_NOTICES.md`**

One table row: project, licence `MIT`, pinned commit `880a672`, link to the full text, and the adapted paths (`services/frontend/src/lib/{renderGovernor,labelBudget,labelQuota,labelArbiter}.ts`). Plus the rule for future additions: full licence under `LICENSES/`, a row here, a pointer header in every adapted file.

- [ ] **Step 3: Verify the text is byte-identical to upstream**

```bash
curl -sL https://raw.githubusercontent.com/bilawalsidhu/gods-eye-view/880a672b5e16ad3e41d318801d3a5203f9201923/LICENSE \
  | sed -n '/^MIT License/,/^SOFTWARE\.$/p' > /tmp/upstream-mit.txt
sed -n '/^MIT License/,/^SOFTWARE\.$/p' LICENSES/gods-eye-view-MIT.txt > /tmp/ours-mit.txt
diff /tmp/upstream-mit.txt /tmp/ours-mit.txt && echo IDENTICAL
```
Expected: `IDENTICAL`. If it differs, upstream wins.

- [ ] **Step 4: Commit**

```bash
git add LICENSES/gods-eye-view-MIT.txt THIRD_PARTY_NOTICES.md
git commit -m "chore: add third-party licence notices for adapted code"
```

---

## Task 1: Measure the label baseline

**Files:** Create `docs/reports/2026-08-25-task-114-label-baseline.md`.

**Interfaces:** Produces the numbers Task 5's budget matrix and Task 10's DDC decision both consume. No code.

**Why this is a task and not an assumption:** the previous two revisions of this plan asserted label behaviour from reading source and were wrong both times. The `DistanceDisplayCondition` question — does the analyst see any labels at globe scale, and where exactly do they cut out — cannot be answered by reading; Cesium evaluates it per object per frame against camera distance, not altitude.

- [ ] **Step 1: Add a temporary counting probe**

In `WorldviewPage.tsx`, temporarily, inside a `useEffect` that has the viewer:

```ts
    const probe = setInterval(() => {
      const scene = viewer.scene;
      const counts: Record<string, number> = {};
      for (let i = 0; i < scene.primitives.length; i++) {
        const p = scene.primitives.get(i);
        if (p instanceof Cesium.LabelCollection) {
          let shown = 0;
          for (let j = 0; j < p.length; j++) if (p.get(j).show) shown++;
          counts[`labels#${i}`] = shown;
        }
      }
      console.log("[baseline]", {
        heightM: Math.round(viewer.camera.positionCartographic.height),
        counts,
      });
    }, 2000);
```
with `clearInterval(probe)` in the cleanup.

Note `label.show` is the author-set flag, not the DDC verdict — Cesium evaluates the `DistanceDisplayCondition` at render time and does not write it back. The probe therefore reports how many labels were *created*; the visual count in Step 2 is what reports how many are *drawn*. Recording both is the point: their divergence is the DDC.

- [ ] **Step 2: Measure at five altitudes with the default layer set**

`npm run dev`. For each altitude — **~15 000 km (globe), ~3 000 km, ~500 km, ~100 km, ~10 km** — record:

- the probe's created-label counts per collection
- a screenshot
- the **visually counted** labels actually on screen, per layer (Earthquakes and GDACS at minimum)
- whether the count changes when the camera tilts to oblique at the same altitude (this is the altitude-vs-distance distinction; if it changes, the DDC is confirmed as distance-based and no altitude threshold can reproduce it)

Enable GDACS explicitly — `DEFAULT_LAYERS` ships it off.

- [ ] **Step 3: Write the report**

`docs/reports/2026-08-25-task-114-label-baseline.md`: a table of altitude × layer × (created, drawn), the five screenshots, and three explicit findings:

1. The highest altitude at which any label is drawn at all.
2. Whether created ≫ drawn (i.e. the layers build labels Cesium then discards — wasted work the arbiter could avoid).
3. Whether tilting changes the count (distance-based confirmed).

- [ ] **Step 4: Remove the probe and commit the report**

```bash
git checkout -- services/frontend/src/pages/WorldviewPage.tsx
git add docs/reports/2026-08-25-task-114-label-baseline.md
git commit -m "docs(frontend): measure TASK-114 label baseline across altitude bands"
```

---

# Track A — Explicit Render

**Ordering rule.** `scene.requestRenderMode = true` is **scene-wide**. Once on, every application-side mutation — collection adds, `.show` flips, material/shader changes, `preUpdate`-driven animation — needs an explicit `requestRender()` or it will not appear until something else triggers a frame. Camera moves and tile loads request frames natively; the Primitive and Entity APIs do not.

**Task 2 builds the module. Task 3 wires every site. Task 4 installs it.** Installing earlier ships frozen toggles and a frozen spotlight fade. Do not reorder.

### Task 2: Render governor module (dormant)

**Files:** Create `services/frontend/src/lib/renderGovernor.ts` + `src/lib/__tests__/renderGovernor.test.ts`.

**Interfaces:** Produces `GovernedScene`, `GovernedViewer`, `RenderGovernorDiagnostics`, `installRenderGovernor(viewer)`, `uninstallRenderGovernor()`, `holdContinuousRender(id)`, `releaseContinuousRender(id)`, `governorRequestRender(reason?)`, `getRenderGovernorDiagnostics()`. `Cesium.Viewer` satisfies `GovernedViewer` structurally, so no call site and no test needs a cast.

- [ ] **Step 1: Write the failing test**

Create `src/lib/__tests__/renderGovernor.test.ts`:

```ts
import { describe, it, expect, beforeEach } from "vitest";
import {
  installRenderGovernor, uninstallRenderGovernor, holdContinuousRender,
  releaseContinuousRender, governorRequestRender, getRenderGovernorDiagnostics,
  type GovernedViewer,
} from "../renderGovernor";

interface FakeScene {
  requestRenderMode: boolean;
  maximumRenderTimeChange: number;
  renderCount: number;
  requestRender(): void;
}

function fakeViewer(): GovernedViewer & { scene: FakeScene } {
  const scene: FakeScene = {
    requestRenderMode: false,
    maximumRenderTimeChange: 0,
    renderCount: 0,
    requestRender() { this.renderCount++; },
  };
  return { scene };
}

describe("renderGovernor", () => {
  beforeEach(() => { uninstallRenderGovernor(); });

  it("ENTERS IDLE when installed with no holds", () => {
    // The single most important assertion here. requestRenderMode TRUE means
    // EXPLICIT rendering — Cesium stops repainting. So idle ⇒ true, which is
    // the inverse of "holds are active". Getting this backwards inverts the
    // whole feature while every other test still passes.
    const v = fakeViewer();
    installRenderGovernor(v);
    expect(v.scene.requestRenderMode).toBe(true);
    expect(getRenderGovernorDiagnostics().mode).toBe("idle");
  });

  it("STAYS CONTINUOUS when installed while a hold is already registered", () => {
    holdContinuousRender("early");
    const v = fakeViewer();
    installRenderGovernor(v);
    expect(v.scene.requestRenderMode).toBe(false);
    expect(getRenderGovernorDiagnostics().mode).toBe("continuous");
  });

  it("stops Cesium re-rendering on simulation-time deltas", () => {
    const v = fakeViewer();
    installRenderGovernor(v);
    expect(v.scene.maximumRenderTimeChange).toBe(Number.POSITIVE_INFINITY);
  });

  it("renders one settling frame entering idle, none entering continuous", () => {
    const a = fakeViewer();
    installRenderGovernor(a);
    expect(a.scene.renderCount).toBe(1);
    uninstallRenderGovernor();
    holdContinuousRender("early");
    const b = fakeViewer();
    installRenderGovernor(b);
    expect(b.scene.renderCount).toBe(0);
  });

  it("switches to continuous on hold and back to idle on release", () => {
    const v = fakeViewer();
    installRenderGovernor(v);
    holdContinuousRender("flights");
    expect(v.scene.requestRenderMode).toBe(false);
    releaseContinuousRender("flights");
    expect(v.scene.requestRenderMode).toBe(true);
  });

  it("is idempotent per owner so double-hold cannot corrupt the mode", () => {
    const v = fakeViewer();
    installRenderGovernor(v);
    holdContinuousRender("flights");
    holdContinuousRender("flights");
    releaseContinuousRender("flights");
    expect(v.scene.requestRenderMode).toBe(true);
    expect(getRenderGovernorDiagnostics().holds).toEqual([]);
  });

  it("tolerates releasing a hold never taken", () => {
    const v = fakeViewer();
    installRenderGovernor(v);
    expect(() => releaseContinuousRender("never-held")).not.toThrow();
    expect(v.scene.requestRenderMode).toBe(true);
  });

  it("stays continuous until the last of several holds is released", () => {
    const v = fakeViewer();
    installRenderGovernor(v);
    holdContinuousRender("firms-pulse");
    holdContinuousRender("spotlight-fade");
    releaseContinuousRender("firms-pulse");
    expect(v.scene.requestRenderMode).toBe(false);
    releaseContinuousRender("spotlight-fade");
    expect(v.scene.requestRenderMode).toBe(true);
  });

  it("records diagnostics for idle-mode requests only, forwards always", () => {
    const v = fakeViewer();
    installRenderGovernor(v);
    governorRequestRender("layer-visibility");
    holdContinuousRender("flights");
    const before = v.scene.renderCount;
    governorRequestRender("while-continuous");
    expect(v.scene.renderCount).toBe(before + 1);
    expect(getRenderGovernorDiagnostics().recentRequests.map((e) => e.reason))
      .toEqual(["layer-visibility"]);
  });

  it("is a safe no-op before install", () => {
    expect(() => governorRequestRender("no-viewer")).not.toThrow();
    expect(() => holdContinuousRender("x")).not.toThrow();
    expect(getRenderGovernorDiagnostics().installed).toBe(false);
  });

  it("drops all holds on uninstall so a new viewer starts clean", () => {
    const a = fakeViewer();
    installRenderGovernor(a);
    holdContinuousRender("flights");
    uninstallRenderGovernor();
    const b = fakeViewer();
    installRenderGovernor(b);
    expect(b.scene.requestRenderMode).toBe(true);
  });
});
```

- [ ] **Step 2: Run to verify it fails**

`npx vitest run src/lib/__tests__/renderGovernor.test.ts` → FAIL, unresolved import.

- [ ] **Step 3: Write the implementation**

Create `src/lib/renderGovernor.ts` with the Task 0 pointer header, then:

```ts
/**
 * Idle render governor.
 *
 * ⚠ POLARITY: `requestRenderMode === true` means EXPLICIT rendering — Cesium
 * stops repainting on its own. So idle ⇒ true, continuous ⇒ false, the inverse
 * of "holds are active". `applyMode()` is the ONLY place that writes the flag.
 *
 * Holds are identity-keyed (a Set of owner ids), NOT a counter — a module that
 * double-holds or double-releases cannot corrupt the mode. That is what makes
 * this safe under React StrictMode's double-invoked effects.
 */

export interface GovernedScene {
  requestRenderMode: boolean;
  maximumRenderTimeChange: number;
  requestRender(): void;
}
export interface GovernedViewer { readonly scene: GovernedScene }
export interface RenderGovernorRequest { readonly reason: string; readonly at: number }
export interface RenderGovernorDiagnostics {
  readonly installed: boolean;
  readonly mode: "continuous" | "idle";
  readonly holds: string[];
  readonly recentRequests: RenderGovernorRequest[];
}

const RECENT_REQUEST_CAP = 16;

let viewerRef: GovernedViewer | null = null;
let installed = false;
const holds = new Set<string>();
const recentRequests: RenderGovernorRequest[] = [];

const isIdle = (): boolean => holds.size === 0;

/** `force` skips the no-op guard so install always lands flag + settling frame. */
function applyMode(force = false): void {
  if (!installed || !viewerRef) return;
  const scene = viewerRef.scene;
  const idle = isIdle();
  if (!force && scene.requestRenderMode === idle) return;
  scene.requestRenderMode = idle;
  // Entering idle: one settling frame so the last continuous frame's mutations
  // reach the screen before the loop stops.
  if (idle) scene.requestRender();
}

export function installRenderGovernor(viewer: GovernedViewer): void {
  viewerRef = viewer;
  installed = true;
  // Never let Cesium re-render on simulation-time deltas behind our back.
  viewer.scene.maximumRenderTimeChange = Number.POSITIVE_INFINITY;
  applyMode(true);
}

export function uninstallRenderGovernor(): void {
  viewerRef = null;
  installed = false;
  holds.clear();
  recentRequests.length = 0;
}

export function holdContinuousRender(ownerId: string): void {
  if (!ownerId) return;
  holds.add(ownerId);
  applyMode();
}

export function releaseContinuousRender(ownerId: string): void {
  if (!ownerId) return;
  holds.delete(ownerId);
  applyMode();
}

/**
 * One-shot request for a discrete scene mutation. Always forwards — in
 * continuous mode that is a harmless flag set, and forwarding closes the
 * request-then-last-release race. Only idle requests are recorded.
 */
export function governorRequestRender(reason = "unspecified"): void {
  if (!installed || !viewerRef) return;
  if (isIdle()) {
    recentRequests.push({ reason, at: Date.now() });
    if (recentRequests.length > RECENT_REQUEST_CAP) recentRequests.shift();
  }
  viewerRef.scene.requestRender();
}

export function getRenderGovernorDiagnostics(): RenderGovernorDiagnostics {
  return {
    installed,
    mode: isIdle() ? "idle" : "continuous",
    holds: [...holds].sort(),
    recentRequests: [...recentRequests],
  };
}
```

- [ ] **Step 4: Run, type-check, lint, commit**

```bash
cd services/frontend && npx vitest run src/lib/__tests__/renderGovernor.test.ts && npm run type-check && npm run lint
cd ../.. && git add services/frontend/src/lib/renderGovernor.ts services/frontend/src/lib/__tests__/renderGovernor.test.ts
git commit -m "feat(frontend): add ref-counted cesium render governor"
```

If "ENTERS IDLE" fails, the polarity is inverted — fix `applyMode`, never the test.

---

### Task 3: Request a frame from every scene mutation

**Files:** Test first — `src/components/globe/__tests__/renderRequestCoverage.test.ts`. Then all files in the coverage set below.

**Interfaces:** Consumes Task 2. Hold vocabulary: `"firms-pulse"`, `"earthquake-pulse"`, `"event-pulse"`, `"flight-interpolation"`, `"milair-tick"`, `"spotlight-fade-in"`, `"spotlight-fade-out"`, `"capital-pulse"`.

**Coverage set — verified at `9ee06cc`, and NOT limited to `components/layers/`:**

*Layers (15, all under `src/components/layers/`):* `CableLayer` · `SatelliteLayer` · `PipelineLayer` · `EventLayer` · `MilAircraftLayer` · `FlightLayer` · `EarthquakeLayer` · `ShipLayer` · `RefineryLayer` · `GDACSLayer` · `EONETLayer` · `DatacenterLayer` · `FIRMSLayer` · `ReconLayer` · `CCTVLayer`

*Outside `layers/` — the gap that failed the previous review:*

| Site | Why it mutates | Line |
|---|---|---|
| `components/globe/visual-layers/Graticule.tsx` | `primitives.add`, mounted always (`WorldviewPage.tsx:219`) | `:48` |
| `components/globe/spotlight/SpotlightOverlay.tsx` | `primitives.add` ×2 **plus a `scene.preUpdate` alpha fade** (`FADE_IN_MS` 320 / `FADE_OUT_MS` 200, `:46-47`). Mounted as `LegacyCountrySpotlightOverlay` (`WorldviewPage.tsx:949`) and `CircleSpotlightOverlay` (`:988`) | `:102,109,154` |
| `components/globe/spotlight/CapitalPulse.tsx` | `scene.preUpdate` listener projecting a DOM element every frame; mounted `WorldviewPage.tsx:950` | `:45` |
| `components/globe/GlobeViewer.tsx` | `primitives.add`, tileset `.show`, border `.show`; **plus the visual-style effect** that swaps CRT/NVG/FLIR shaders | `:81,83,131,201,207,212` |
| `components/globe/visual-layers/CountryBorders.tsx` | `scene.groundPrimitives.add` / `.remove` — **`groundPrimitives`, not `primitives`**, and the GeoJSON fetch resolves asynchronously well after the governor is installed | `:80,90` |
| `components/shaders/shaderUtils.ts` | `scene.postProcessStages.add(stage)` ×3 — a bare identifier argument, so the `.add({` half of the regex never sees it | `:24,32,40` |
| `spatial/cesium/CesiumSpatialScopeAdapter.ts` | `primitives.add` + a large number of `.show` transitions during scope handoff | `:64,108,349–522` |
| `spatial/cesium/buildScopePrimitives.ts` | primitive `.show` | `:189,197` |

**Natively covered, deliberately not in this set:** imagery layers (`GlobeViewer.tsx` ~`:143` night imagery). Imagery loads request frames through Cesium's own tile pipeline. Only the Primitive / GroundPrimitive / PostProcessStage APIs need an explicit request.

**The two `preUpdate` consumers are the subtle ones.** In explicit-render mode `preUpdate` fires only when a frame runs, so both a spotlight fade and the capital-pulse DOM projection simply stop in idle. They need a **scoped hold** for exactly as long as they animate — the same mechanism this plan defers for label fade, except this fade already exists in the codebase.

- [ ] **Step 1: Write the failing coverage test**

Create `src/components/globe/__tests__/renderRequestCoverage.test.ts`:

```ts
import { describe, it, expect } from "vitest";
import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";

const SRC = join(process.cwd(), "src");
const LAYER_DIR = join(SRC, "components/layers");

/**
 * A file mutates the scene if it adds primitives (scene.primitives OR
 * scene.groundPrimitives), adds a post-process stage, flips show, empties a
 * collection, or drives preUpdate.
 *
 * `postProcessStages\.add` and `groundPrimitives` are listed explicitly: the
 * first takes a bare identifier so `\.add\(\{` never matches it, and the second
 * only matches `primitives\.add` by luck of substring — a reader tightening
 * that alternative to `scene\.primitives\.add` would silently drop
 * CountryBorders.tsx from the population. Do not tighten it.
 */
const MUTATES =
  /primitives\.add|postProcessStages\.add|\.show\s*=|\.add\(\{|removeAll\(\)|preUpdate/;

function sceneMutatingLayers(): string[] {
  return readdirSync(LAYER_DIR)
    .filter((f) => f.endsWith(".tsx") && !f.includes(".test."))
    .filter((f) => MUTATES.test(readFileSync(join(LAYER_DIR, f), "utf8")))
    .sort();
}

/** Scene-mutating files OUTSIDE components/layers. GoogleTiles.tsx is dead code. */
const NON_LAYER_SITES: readonly string[] = [
  "components/globe/GlobeViewer.tsx",
  "components/globe/spotlight/CapitalPulse.tsx",
  "components/globe/spotlight/SpotlightOverlay.tsx",
  "components/globe/visual-layers/CountryBorders.tsx",
  "components/globe/visual-layers/Graticule.tsx",
  "components/shaders/shaderUtils.ts",
  "spatial/cesium/CesiumSpatialScopeAdapter.ts",
  "spatial/cesium/buildScopePrimitives.ts",
];

const ANIMATOR_HOLDS: ReadonlyArray<readonly [string, string]> = [
  ["components/layers/FIRMSLayer.tsx", "firms-pulse"],
  ["components/layers/EarthquakeLayer.tsx", "earthquake-pulse"],
  ["components/layers/EventLayer.tsx", "event-pulse"],
  ["components/layers/FlightLayer.tsx", "flight-interpolation"],
  ["components/layers/MilAircraftLayer.tsx", "milair-tick"],
  // Fade-in and fade-out need SEPARATE owner ids: holds live in a Set, so one
  // shared id makes the second hold a no-op and lets whichever releases first
  // kill the other's hold. Switching spotlight target would freeze the fade.
  ["components/globe/spotlight/SpotlightOverlay.tsx", "spotlight-fade-in"],
  ["components/globe/spotlight/SpotlightOverlay.tsx", "spotlight-fade-out"],
  ["components/globe/spotlight/CapitalPulse.tsx", "capital-pulse"],
];

describe("explicit-render coverage", () => {
  it("pins the scene-mutating layer population", () => {
    // A NEW layer lands here and fails until it is considered. Silent omission
    // is the exact failure mode this task exists to prevent.
    expect(sceneMutatingLayers()).toEqual([
      "CCTVLayer.tsx", "CableLayer.tsx", "DatacenterLayer.tsx", "EONETLayer.tsx",
      "EarthquakeLayer.tsx", "EventLayer.tsx", "FIRMSLayer.tsx", "FlightLayer.tsx",
      "GDACSLayer.tsx", "MilAircraftLayer.tsx", "PipelineLayer.tsx", "ReconLayer.tsx",
      "RefineryLayer.tsx", "SatelliteLayer.tsx", "ShipLayer.tsx",
    ]);
  });

  it.each(sceneMutatingLayers())("layers/%s requests a render frame", (file) => {
    expect(readFileSync(join(LAYER_DIR, file), "utf8")).toContain("governorRequestRender");
  });

  it.each(NON_LAYER_SITES)("%s requests a render frame", (rel) => {
    expect(readFileSync(join(SRC, rel), "utf8")).toContain("governorRequestRender");
  });

  it("finds no scene-mutating file outside the known set", () => {
    // Guards against a new spotlight/overlay/adapter appearing unnoticed.
    const walk = (dir: string, acc: string[] = []): string[] => {
      for (const entry of readdirSync(dir, { withFileTypes: true })) {
        const abs = join(dir, entry.name);
        if (entry.isDirectory()) {
          if (entry.name !== "__tests__") walk(abs, acc);
        } else if (/\.tsx?$/.test(entry.name) && !entry.name.includes(".test.")) {
          acc.push(abs);
        }
      }
      return acc;
    };
    const known = new Set([
      ...sceneMutatingLayers().map((f) => join(LAYER_DIR, f)),
      ...NON_LAYER_SITES.map((r) => join(SRC, r)),
      join(SRC, "components/globe/GoogleTiles.tsx"), // dead code, imported nowhere
    ]);
    const unexpected = walk(SRC)
      .filter((abs) => MUTATES.test(readFileSync(abs, "utf8")))
      .filter((abs) => !known.has(abs))
      .map((abs) => abs.slice(SRC.length + 1));
    expect(unexpected).toEqual([]);
  });

  it.each(ANIMATOR_HOLDS)("%s balances its %s hold", (rel, ownerId) => {
    const src = readFileSync(join(SRC, rel), "utf8");
    const holds = src.split(`holdContinuousRender("${ownerId}")`).length - 1;
    const releases = src.split(`releaseContinuousRender("${ownerId}")`).length - 1;
    expect(holds).toBeGreaterThan(0);
    expect(releases).toBeGreaterThanOrEqual(holds);
  });

  it("gates the mil-air tick on visibility so idle is reachable at all", () => {
    // The clock.onTick effect guarded only on the viewer; the layer is mounted
    // unconditionally (WorldviewPage.tsx:391) with visible as a prop, so the
    // hold would be permanent and idle unreachable.
    const src = readFileSync(join(LAYER_DIR, "MilAircraftLayer.tsx"), "utf8");
    expect(src.slice(src.indexOf("viewer.clock.onTick") - 600)).toMatch(/if\s*\(!visible\)/);
  });
});
```

- [ ] **Step 2: Run to verify it fails**

`npx vitest run src/components/globe/__tests__/renderRequestCoverage.test.ts` → FAIL on every per-file assertion and the mil-air gate.

If `pins the scene-mutating layer population` or `finds no scene-mutating file outside the known set` fails, the codebase has changed since this plan. Update the lists **and** re-derive the coverage table — do not just make the assertions match.

- [ ] **Step 3: Gate the mil-air tick on visibility**

`MilAircraftLayer.tsx` — the effect owning `viewer.clock.onTick` (~:157) guards only on the viewer. Add a `visible` gate as the second guard (tear down the listener and release the hold in it), take `holdContinuousRender("milair-tick")` before registering the listener, release in the cleanup, and add `visible` to the dependency array.

Deliberate behaviour change, safe: while hidden the billboards are not drawn, so not repositioning them costs nothing; they reposition on the first tick after being shown.

- [ ] **Step 4: Hold the four layer animators**

Same shape — hold as the first statement after the visibility guard, release both in that guard and in the cleanup:
`FIRMSLayer` → `"firms-pulse"` · `EarthquakeLayer` → `"earthquake-pulse"` · `EventLayer` → `"event-pulse"` (all three rAF pulse effects, already `visible`-gated) · `FlightLayer` → `"flight-interpolation"` (hold before `setInterval`, release beside `clearInterval`).

- [ ] **Step 5: Hold the two `preUpdate` animators**

`SpotlightOverlay.tsx` — each mount function adds a primitive and registers a `preUpdate` listener that ramps `material.uniforms.alpha` from `performance.now()`.

**Use two distinct owner ids.** Take `holdContinuousRender("spotlight-fade-in")` where the fade-in listener is registered, release it when the ramp completes (`t >= FADE_IN_MS`) and in the teardown. `fadeOutAndRemove` takes `holdContinuousRender("spotlight-fade-out")` and releases it when it removes the primitive.

One shared id would be a latent bug: holds are a `Set`, so on a spotlight target switch the outgoing mount's `fadeOutAndRemove` and the incoming mount's fade-in both name the same owner — the second `hold` is a no-op, and whichever releases first drops the hold out from under the other. The remaining fade then freezes mid-ramp in idle.

Add `governorRequestRender("spotlight-add")` after each `primitives.add`.

`CapitalPulse.tsx:45` — the `preUpdate` listener projects a DOM element. It does not mutate the Cesium scene, so it needs no render request, but it does need frames to keep running: hold `"capital-pulse"` while the effect is active, release in its cleanup.

- [ ] **Step 6: Request frames from the remaining sites**

Add `import { governorRequestRender } from "…/lib/renderGovernor";` and call it as the **last statement** of every function that mutates:

- `Graticule.tsx:48` after `primitives.add`
- `CountryBorders.tsx:80,90` after `groundPrimitives.add` and after `.remove` — this one resolves from an async GeoJSON fetch, so it lands well after the governor is installed and is invisible until the next camera move without a request
- `shaderUtils.ts:24,32,40` after each `postProcessStages.add(stage)`, plus `governorRequestRender("globe-shader")` at the end of the visual-style effect in `GlobeViewer.tsx:212` that swaps CRT/NVG/FLIR
- `GlobeViewer.tsx:81,83,131,201,207` (tileset add / `.show`, border `.show`)
- `CesiumSpatialScopeAdapter.ts` after each `.show` transition batch and the `primitives.add`
- `buildScopePrimitives.ts` in the `show` setter

Then the 15 layer files: one call per *mutating function* (render/rebuild callback, visibility effect, style update) — typically two to four per file, not one per mutation. Reason strings name the layer: `"cable-render"`, `"satellite-orbits"`, `"gdacs-render"`, `"scope-handoff"`.

- [ ] **Step 7: Run the coverage test and the suite**

`npx vitest run src/components/globe/__tests__/renderRequestCoverage.test.ts && npm test` → both PASS.

**Known limitation, state it in the PR:** these tests prove each file *mentions* the function and that no unknown file mutates the scene. They cannot prove every mutation site inside a file is covered. Task 4 Step 5 is the behavioural gate that does.

- [ ] **Step 8: Commit**

```bash
git add services/frontend/src/components services/frontend/src/spatial
git commit -m "feat(frontend): request a render frame from every scene mutation"
```

---

### Task 4: Install the governor and measure

**Files:** Modify `components/globe/GlobeViewer.tsx` (install after `viewerRef.current = viewer` at `:164`; uninstall as the **first** cleanup statement so teardown mutations are not swallowed).

- [ ] **Step 1: Write the failing install test**

Append to `renderRequestCoverage.test.ts`:

```ts
describe("governor install", () => {
  it("installs and uninstalls the governor in GlobeViewer", () => {
    const src = readFileSync(join(SRC, "components/globe/GlobeViewer.tsx"), "utf8");
    expect(src).toContain("installRenderGovernor(viewer)");
    expect(src).toContain("uninstallRenderGovernor()");
  });
});
```

- [ ] **Step 2: Run to verify it fails** — `npx vitest run …/renderRequestCoverage.test.ts` → FAIL on the new block.

- [ ] **Step 3: Install** — add the import, `installRenderGovernor(viewer);` after `:164`, `uninstallRenderGovernor();` first in the cleanup.

- [ ] **Step 4: Run to verify it passes** — `npx vitest run …/renderRequestCoverage.test.ts && npm test` → PASS.

- [ ] **Step 5: Behavioural toggle matrix — the real gate**

With a temporary `setInterval(() => console.log("[governor]", getRenderGovernorDiagnostics()), 2000)` in the install effect:

1. **All layers off:** confirm `mode: "idle"`, `holds: []`. A leaking owner is named in `holds` — `milair-tick` there means Step 3 of Task 3 did not take.
2. **Each of the 15 layers:** toggle on → appears **without touching the camera**; toggle off → disappears likewise.
3. **Graticule, country borders, city buildings:** same, without camera movement.
4. **Spotlight:** click a country → the fade runs to full opacity, not frozen part-way.
5. **Capital pulse:** confirm the DOM marker still tracks the globe while idle.
6. **Spatial scope:** drill into a country → the boundary primitives appear without a camera nudge.
7. **Live data:** with Flights on, wait one refresh and confirm the update appears without camera movement.

Record all results as a checklist in the PR body. Anything appearing only after a camera nudge is a missing `governorRequestRender`.

- [ ] **Step 6: PerformanceGuard non-interaction**

`PerformanceGuard` counts its own rAF callbacks, not Cesium frames — rAF keeps firing whether or not Cesium paints, so idle must NOT trigger degradation. Idle for 30 s, confirm no degradation. If it climbs, stop and resolve before merging.

- [ ] **Step 7: Measure, remove the probe, commit**

Record idle GPU/CPU over 30 s with all layers off, before and after (`git stash` to compare). Both numbers into the PR body, **with the caveat from "What this plan does NOT deliver"** that the default layer set does not reach idle.

```bash
git add services/frontend/src/components/globe
git commit -m "feat(frontend): idle the globe render loop when nothing animates"
```

---

# Track B — Collective Label Budget

### Task 5: Label budget matrix

**Files:** Create `src/lib/labelBudget.ts` + `src/lib/__tests__/labelBudget.test.ts`.

**Interfaces:** Produces `LabelViewScale`, `DensityStop`, `DensityProfile`, `DENSITY_STOPS`, `VIEW_SCALE_BUDGETS`, `labelViewScaleForAltitude`, `canonicalizeDensity`, `profileForDensity`, `defaultDensityForProfile`, `labelBudgetFor`. Consumes `GLOBE_ALTITUDE_M`, `LOCAL_ALTITUDE_M`, `bandForHeight` from `lib/lod.ts` for the alignment invariant only.

**Matrix status: PROVISIONAL.** The `global` (≥8e6 m) and upper-`regional` rows govern a band where Task 1 may show that no labels are drawn at all. They are written now so the module is complete and testable; **Task 10 decides whether they are live, and Task 10 may delete them.** Do not present these numbers as calibrated before Task 10.

Thresholds subdivide the three `lod.ts` bands rather than crossing them: `street` <50 km, `city` <250 km, `metro` <1 000 km (= `LOCAL_ALTITUDE_M`), `regional` <8 000 km (= `GLOBE_ALTITUDE_M`), else `global`.

- [ ] **Step 1: Write the failing test**

Create `src/lib/__tests__/labelBudget.test.ts` covering: the five-scale classification; non-finite → `global` and negative → `street`; the four `lod.ts` alignment pairs (`LOCAL_ALTITUDE_M ∓ 1` → `metro`/`regional` matching `LOCAL`/`REGIONAL`, same at `GLOBE_ALTITUDE_M`); density snapping at every boundary (0, 10→0, 13→25, 25→25, 40→50, 74→50, 80→75, 95→100), clamping, and non-finite fallback with and without an explicit fallback; `profileForDensity` per stop plus a round-trip through `defaultDensityForProfile`; and for `VIEW_SCALE_BUDGETS` — integer at every cell, strictly increasing along density within each scale, non-increasing as the camera pulls back, and a worst-case cell below 250 (the old per-layer `MAX_QUAKES`). Finally `labelBudgetFor` resolving three altitude/density pairs against the matrix.

Write every assertion against `VIEW_SCALE_BUDGETS[...]` rather than literal counts, so Task 10 can change the matrix without editing this file.

- [ ] **Step 2: Run to verify it fails** — unresolved import.

- [ ] **Step 3: Write the implementation**

`src/lib/labelBudget.ts` with the Task 0 pointer header. Constants `STREET_CEILING_M = 50_000`, `CITY_CEILING_M = 250_000`, `METRO_CEILING_M = 1_000_000`, `REGIONAL_CEILING_M = 8_000_000`, each commented with the `lod.ts` constant it mirrors. Provisional matrix:

```ts
export const VIEW_SCALE_BUDGETS: Readonly<
  Record<LabelViewScale, Readonly<Record<DensityStop, number>>>
> = Object.freeze({
  street:   Object.freeze({ 0: 8, 25: 20, 50: 40, 75: 60, 100: 80 }),
  city:     Object.freeze({ 0: 6, 25: 16, 50: 32, 75: 48, 100: 64 }),
  metro:    Object.freeze({ 0: 5, 25: 12, 50: 24, 75: 36, 100: 48 }),
  regional: Object.freeze({ 0: 4, 25: 10, 50: 20, 75: 30, 100: 40 }),
  global:   Object.freeze({ 0: 3, 25:  8, 50: 16, 75: 24, 100: 32 }),
});
```

Deviation from upstream, documented in the module: God's Eye View gives `global` a *larger* budget than `regional` because its Earth leaves radial screen space at full-globe framing. ODIN's globe fills the viewport, so the budget shrinks all the way out — **if** Task 10 keeps the row at all.

`canonicalizeDensity` boundaries: `<12.5 → 0`, `<=25 → 25`, `<75 → 50`, `<87.5 → 75`, else `100`.

- [ ] **Step 4: Run, type-check, lint, commit** — `git commit -m "feat(frontend): add collective altitude-aware label budget matrix"`

---

### Task 6: Work-conserving quota allocation

**Files:** Create `src/lib/labelQuota.ts` + test.

**Interfaces:** Produces `AllocationStrategy`, `ALLOCATION_STRATEGIES`, `LAYER_LABEL_WEIGHTS`, `normalizeAllocationStrategy`, `allocateLayerQuotas(demandByLayer, capacity, strategy?, layerWeights?)`.

**Design:** `ELASTIC` splits evenly. `WEIGHTED` scores each layer `sqrt(count) × semanticWeight` — the root damps mass-data layers so a four-item alert layer is not rounded out by a four-thousand-item hotspot layer. Both deterministic, both work-conserving.

**Weighted redistribution must stay weighted.** When a layer saturates, the freed capacity is re-apportioned by recomputing the weighted split over the layers that still have room — not round-robin. Round-robin after saturation silently converts a weighted allocation into an elastic one exactly when the weights matter most.

- [ ] **Step 1: Write the failing test**

`src/lib/__tests__/labelQuota.test.ts`. Shared invariants via `it.each(ALLOCATION_STRATEGIES)`: never exceeds capacity; never exceeds a layer's demand; work-conserving (`{a:2,b:100}` @ 40 → `b` gets 38, total 40); capacity clamped to total demand; all-zero at capacity 0; zero-demand layers ignored; deterministic across repeated calls; every demanding layer gets ≥1 when `capacity >= layerCount`; empty demand handled.

ELASTIC: even split; indivisible remainder not lost.

WEIGHTED: sqrt damping (`{dense:4000, sparse:4}` @ 20 → `sparse` ≥ 2); semantic weight beats raw count at equal counts; zero/negative weight floored rather than zeroing a layer; and the saturation case —

```ts
  it("STAYS WEIGHTED after a layer saturates", () => {
    // 'tiny' saturates at 1. The 9 remaining slots must split by weight between
    // 'heavy' and 'light' (sqrt 20 : sqrt 5 = 4:1), NOT round-robin (~5:4),
    // which would quietly turn this into an elastic allocation.
    const q = allocateLayerQuotas(
      new Map([["tiny", 1], ["heavy", 400], ["light", 25]]),
      10, "WEIGHTED", { tiny: 1, heavy: 1, light: 1 },
    );
    expect(q.get("tiny")).toBe(1);
    expect([...q.values()].reduce((a, b) => a + b, 0)).toBe(10);
    expect(q.get("heavy")).toBeGreaterThanOrEqual(6);
    expect(q.get("light")).toBeLessThanOrEqual(3);
  });
```

`LAYER_LABEL_WEIGHTS`: covers all eight label layers with a positive weight; alert layers outrank static infrastructure.

- [ ] **Step 2: Run to verify it fails.**

- [ ] **Step 3: Write the implementation**

`src/lib/labelQuota.ts` with the Task 0 pointer header. Weights: `events 1.4, gdacs 1.3, earthquakes 1.2, eonet 1.0, refineries 0.7, datacenters 0.7, pipelines 0.5, cables 0.5`; `MIN_SEMANTIC_WEIGHT = 0.05`.

`allocateLayerQuotas`: filter to positive demand in stable id order; clamp capacity to total demand; ELASTIC = even split + `redistributeUnused` round-robin. WEIGHTED = a floor of one per demanding layer when `capacity >= layerCount`, then an **iterative** `apportionWeighted` that recomputes the weighted share over the unsaturated layers each round (bounded by `demand.size + 1` rounds), falling back to a largest-remainder pass when every exact share drops below 1, then `redistributeUnused` in weight order as a backstop.

- [ ] **Step 4: Run, type-check, lint, commit** — `git commit -m "feat(frontend): allocate label capacity across layers work-conservingly"`

---

### Task 7: Label arbiter

**Files:** Create `src/lib/labelArbiter.ts` + test.

**Interfaces:** Produces `ScreenRect`, `LABEL_CELL_SIZE_PX` (32), `LABEL_COLLISION_PADDING_PX` (4), `LABEL_ARBITER_TIMING` (`minimumLifetimeMs` 2500, `cooldownMs` 1200), `rectsOverlap`, `estimateLabelRect`, `LabelSpatialHash`, `LabelCandidate`, `SolveOptions`, `SolveDiagnostics`, `LabelArbiter`. Consumes Task 6.

The arbiter stays **pure and Cesium-free**: it takes rectangles, never world positions. Projection is the hook's job (Task 8).

**Two corrections over a naive port:**

1. **Priority is normalised per layer before any cross-layer comparison.** Layers hand in raw domain numbers — magnitude 7.1, FRP 480, severity 3. Comparing those directly means a wildfire always outranks an earthquake because FRP uses bigger numbers. The arbiter ranks within each layer and compares normalised ranks in [0,1]. A single-candidate layer normalises to 0 (its own best) — guard the divisor.
2. **Unused quota is lent at the arbiter level.** A layer can fail to spend its quota because its candidates collide or are cooling. A second pass fills remaining global capacity from the deferred pool, ignoring per-layer quota, so the scene never sits under budget with usable candidates on the table.

`estimateLabelRect(screenX, screenY, text, fontSizePx)` approximates from glyph count (`0.6 × fontSize` advance, `1.2 × fontSize` line height), centred on the anchor. Deliberately generous: an over-estimate costs one dropped label, an under-estimate costs an overlap. **The caller supplies the anchor already offset** — see Task 8, `pixelOffset`.

- [ ] **Step 1: Write the failing test**

`src/lib/__tests__/labelArbiter.test.ts`.

*Geometry:* `rectsOverlap` plain overlap, clear separation, the 4 px gutter (`x=42` collides, `x=45` does not, `padding: 0` disables), constants pinned. `estimateLabelRect` scaling, centring, non-zero for empty text. `LabelSpatialHash` empty/insert/cross-cell (`insert(28,0)` collides with `(60,0)` at 32 px cells) / clear / extreme + non-finite tolerance.

*Budget and quota:* never exceeds capacity; splits across layers (`firms` 400 + `gdacs` 4 at disjoint x, capacity 20, WEIGHTED → `gdacs` ≥ 1); prefers higher priority within a layer; empty for zero capacity and for no candidates.

*Cross-layer fairness — the test that actually exercises normalisation:*

```ts
  it("NORMALISES priority so raw scale does not decide a contested slot", () => {
    // capacity 1 forces a genuine cross-layer contest. Both layers offer their
    // own best candidate. Under raw comparison 'fires-top' (480) always beats
    // 'quakes-top' (7.1); under normalised rank both are 0 and the tie breaks
    // deterministically on key — so the assertion is that the OUTCOME does not
    // depend on the magnitude of the numbers.
    const solve = (fireTop: number, quakeTop: number) =>
      new LabelArbiter().solve(
        [
          { key: "a-quake", layerId: "quakes", rect: { x: 100, y: 100, w: 40, h: 12 }, priority: quakeTop },
          { key: "b-fire", layerId: "fires", rect: { x: 105, y: 100, w: 40, h: 12 }, priority: fireTop },
        ],
        { capacity: 1, now: 0 },
      );
    // Same winner whether the fire scores 480 or 0.5 — that is normalisation.
    expect([...solve(480, 7.1)]).toEqual([...solve(0.5, 7.1)]);
  });

  it("handles a single-candidate layer without dividing by zero", () => {
    expect(
      new LabelArbiter()
        .solve([{ key: "only", layerId: "solo", rect: { x: 0, y: 0, w: 40, h: 12 }, priority: 42 }],
               { capacity: 5, now: 0 })
        .has("only"),
    ).toBe(true);
  });
```

*Collision:* overlapping pair at capacity 2 → higher priority wins, `droppedToCollision === 1`; far-apart pair → both.

*Lending:* five candidates of layer `blocked` stacked on one rect plus 20 spread candidates of layer `open`, capacity 12 → exactly 12 selected, exactly 1 from `blocked`, `lentSlots > 0`. And lending never exceeds capacity.

*Hysteresis:* timings pinned; incumbent held through its lifetime (`heldByLifetime === 1`); released after it; a dropped label blocked during cooldown (`blockedByCooldown === 1`) and admitted after; stable selection across repeated identical solves; `clear()` forgets everything; withdrawn candidates drop their state.

- [ ] **Step 2: Run to verify it fails.**

- [ ] **Step 3: Write the implementation**

`src/lib/labelArbiter.ts` with the Task 0 pointer header. `LabelSpatialHash` as a uniform 32 px grid with a generation stamp instead of a rebuild, cell keys clamped to ±8192 cells. `LabelArbiter.solve`:

1. Drop state for keys no longer offered.
2. Count demand per layer → `allocateLayerQuotas`; `capacity` = the quota sum (already clamped to demand).
3. Compute `held` = currently-selected keys still inside `minimumLifetimeMs`.
4. `normalise(candidates)` → rank within layer, `index / max(1, bucket.length - 1)`.
5. Sort: held first, then ascending normalised rank, then key.
6. Pass 1 — per-layer quota respected; skip-to-`deferred` when the quota is spent; `admit()` returns `placed` | `collision` | `cooldown`.
7. Pass 2 — while `placed < capacity`, walk `deferred` through the same `admit()`, counting `lentSlots`.
8. Update `selectedAt` / `droppedAt`, publish `SolveDiagnostics`.

`cooling` is `!held.has(key) && state !== undefined && state.droppedAt !== null && now - state.droppedAt < cooldownMs` — no casts.

No fade animation, by design: a fade needs a per-frame animator, which under Track A means a continuous-render hold. The stability half of the hysteresis is what removes the flicker.

- [ ] **Step 4: Run, type-check, lint, commit** — `git commit -m "feat(frontend): add stable quota-aware label arbiter"`

---

### Task 8: React seam — the hook owns projection

**Files:** Create `src/hooks/useLabelArbiter.ts` + `src/hooks/__tests__/useLabelArbiter.test.tsx`.

**Interfaces:**
```ts
/** What a layer describes. NO screen coordinates — the hook projects. */
export interface LabelRequest {
  readonly key: string;
  readonly position: Cesium.Cartesian3;
  readonly text: string;
  readonly fontSizePx: number;
  /** The layer's own Cesium pixelOffset.y, so the collision box lands on the label. */
  readonly pixelOffsetY: number;
  readonly priority: number;
}
/**
 * Injectable so tests need no Cesium scene and no cast.
 * CONTRACT: returns null when the label is not on screen — behind the globe,
 * outside the frustum, OR projected outside the canvas. `worldToWindowCoordinates`
 * alone does NOT satisfy this: it happily returns coordinates far outside the
 * canvas for any point in front of the camera. The default projector applies the
 * canvas bounds itself; see Task 8 Step 3.
 */
export type LabelProjector = (position: Cesium.Cartesian3) => { x: number; y: number } | null;
export interface LabelArbiterApi {
  submit(layerId: string, requests: readonly LabelRequest[]): void;
  remove(layerId: string): void;
  isSelected(key: string): boolean;
  readonly version: number;
}
export interface LabelArbiterViewer {
  isDestroyed(): boolean;
  /** Structural, so no `as Cesium.Scene` cast is needed in the default projector. */
  readonly scene: Cesium.Scene & { readonly canvas: { clientWidth: number; clientHeight: number } };
  readonly camera: {
    readonly positionCartographic: { readonly height: number };
    readonly moveEnd: { addEventListener(fn: () => void): () => void };
  };
}
export function useLabelArbiter(
  viewer: LabelArbiterViewer | null,
  densityPct: number,
  projector?: LabelProjector,
): LabelArbiterApi
```

**Why projection moved into the hook.** If layers project and submit rectangles, a layer without a `camera.moveEnd` listener submits rectangles from the *previous* camera. `GDACSLayer.tsx` has exactly two effects, with dependency arrays `[viewer]` (`:137`) and `[events, visible, viewer]` (`:173`) — and **no** `moveEnd` listener, unlike `EarthquakeLayer.tsx:178`. After any pan its rectangles would be stale and the 2.5 s hysteresis would lock the wrong selection in. Projecting every candidate inside the hook at solve time, from one camera, makes stale rectangles structurally impossible for every layer, present and future. It also puts `pixelOffset` handling in one place instead of eight.

**And why viewport culling moved with it.** Projection in the hook fixes stale *rectangles*; it does nothing for a stale *candidate set*. If `GDACSLayer` ran `selectVisible` in its `[events, visible, viewer]` effect, then after a pan the events that scrolled into view would be missing and the ones that scrolled out would still hold quota — the same bug in a different coat. So the hook owns viewport truth too: the projector returns `null` for anything off-canvas, and that check happens at solve time, on every solve, for every layer.

Consequence for layers: **a layer must NOT viewport-cull before submitting.** It submits a set that does not depend on the camera at all (everything it has, or a generous rank-capped slice to bound projection work). The hook decides what is on screen. `EarthquakeLayer` keeps its existing `selectVisible` for *billboard* rendering — that is a separate concern with its own `moveEnd` rebuild — but its label requests are built from the same `shown` array, so no extra staleness is introduced there.

**Three further properties:**
- **`remove(layerId)`** — a layer going `visible=false` stops submitting; without removal its stale requests keep consuming quota and colliding forever.
- **Coalesced solve on a microtask** — `moveEnd` dispatches this hook's listener and every layer's listener synchronously in one batch; a microtask runs after all of them.
- **`version` bumps only on a real selection change** — the pilot layers depend on `version` in the effect that calls their render callback, and that callback calls `submit()`. An unconditional bump is an infinite loop.

- [ ] **Step 1: Write the failing test**

`src/hooks/__tests__/useLabelArbiter.test.tsx`. Build a `LabelArbiterViewer` fake (mutable `height`, a `moveEnd` registry returning an unsubscribe) and a `LabelProjector` fake that maps a request index to a spread-out x — **no `as any` anywhere**, both types are structural.

Assert: no-op API for a null viewer (`submit`/`remove` do not throw, `isSelected` false); selection respects `labelBudgetFor(height, 50)` — **read the budget from the module, never a literal, so Task 10 cannot break this file**; several submits in one tick produce exactly **one** version bump; one budget shared across two layers with both represented; `remove` frees the removed layer's quota to the other; `moveEnd` after a height change re-solves against the new budget (assert the new count equals `labelBudgetFor(newHeight, 50)`); repeated identical submits do not bump `version` (loop convergence); unmount removes the `moveEnd` listener; **a request whose projector returns `null` is silently dropped rather than throwing**; and `pixelOffsetY` shifts the collision rect (two requests at the same projected point but different offsets do not collide).

Plus the one that makes the hook the owner of viewport truth:

```tsx
  it("DROPS off-canvas candidates so they cannot consume quota", () => {
    // Layers submit camera-independent sets; the projector is what decides
    // what is on screen. A projector that reports half the requests off-canvas
    // must leave their quota to the rest, not silently spend it.
    const offCanvas = new Set(["gdacs-0", "gdacs-1", "gdacs-2"]);
    const projector: LabelProjector = () => ({ x: 0, y: 0 });
    const culling: LabelProjector = (p) => (offCanvas.has(keyFor(p)) ? null : projector(p));
    // …submit six well-separated requests, three of them in `offCanvas`…
    // …expect only the three on-canvas keys to be selected.
  });
```

Note the default projector's canvas check is exercised here only through the injected fake; the real `worldToWindowCoordinates` bounds behaviour is covered by Task 4's toggle matrix, not by a unit test.

- [ ] **Step 2: Run to verify it fails.**

- [ ] **Step 3: Write the implementation**

`src/hooks/useLabelArbiter.ts`. Refs for the arbiter, the per-layer request map, the last-selection fingerprint, a `solveScheduled` flag, density and viewer. `solveNow`:

```ts
    const capacity = labelBudgetFor(current.camera.positionCartographic.height, densityRef.current);
    const project = projectorRef.current;
    const candidates: LabelCandidate[] = [];
    for (const [layerId, requests] of requestsRef.current) {
      for (const r of requests) {
        const screen = project(r.position);
        if (!screen) continue; // behind the globe or off-frustum
        candidates.push({
          key: r.key,
          layerId,
          // Anchor the box where the label actually draws, not at the entity.
          rect: estimateLabelRect(screen.x, screen.y + r.pixelOffsetY, r.text, r.fontSizePx),
          priority: r.priority,
        });
      }
    }
    const selected = arbiter.solve(candidates, { capacity, strategy: "WEIGHTED" });
    const fingerprint = [...selected].sort().join(" ");
    if (fingerprint === lastSelectionRef.current) return;
    lastSelectionRef.current = fingerprint;
    setVersion((v) => v + 1);
    governorRequestRender("label-arbiter-solve");
```

Default projector, built from the viewer when none is injected. **The canvas-bounds check is not optional** — `worldToWindowCoordinates` returns coordinates for any point in front of the camera, including far outside the canvas, so without it off-screen labels would consume quota:

```ts
  const defaultProjector: LabelProjector = useCallback(
    (position) => {
      const scene = viewerRef.current?.scene;
      if (!scene) return null;
      const win = Cesium.SceneTransforms.worldToWindowCoordinates(scene, position);
      if (!win) return null; // behind the globe / outside the frustum
      const { clientWidth, clientHeight } = scene.canvas;
      // Generous margin so a label anchored just off-edge, whose box still
      // overlaps the canvas, is not dropped and then flickers back in.
      const margin = 64;
      if (win.x < -margin || win.y < -margin) return null;
      if (win.x > clientWidth + margin || win.y > clientHeight + margin) return null;
      return { x: win.x, y: win.y };
    },
    [],
  );
```

`LabelArbiterViewer.scene` is therefore typed structurally as what this needs — `{ canvas: { clientWidth: number; clientHeight: number } }` intersected with `Cesium.Scene` where the real one is passed — rather than `object` plus an `as Cesium.Scene` cast at the call site.

`scheduleSolve` guards with `solveScheduledRef` and `queueMicrotask`. `submit` sets the map entry then schedules; `remove` deletes and schedules only if something was deleted. Effects: `moveEnd` → `scheduleSolve` (with unsubscribe in cleanup); `densityPct` → `scheduleSolve`; unmount → `arbiter.clear()`, clear the map, reset the fingerprint.

- [ ] **Step 4: Run, type-check, lint, commit** — `git commit -m "feat(frontend): add label arbiter react seam with owned projection"`

---

### Task 9: Wire the two pilot layers

**Files:** Modify `components/layers/EarthquakeLayer.tsx`, `components/layers/GDACSLayer.tsx`, `pages/WorldviewPage.tsx`. Extend `components/layers/__tests__/EarthquakeLayer.test.tsx` and add `components/layers/__tests__/GDACSLayer.test.tsx`.

**Mount paths, verified at `9ee06cc`** — the previous revision got this wrong:
- `GDACSLayer` is mounted at `WorldviewPage.tsx:312`, **inside `GlobeChildren`** (declared `:202`, props interface `:188`, mounted `:931`). `GlobeChildrenProps` has **no** `labelArbiter` — it needs one.
- `EarthquakeLayer` is mounted at `WorldviewPage.tsx:909`, at page level.
- `WorldviewPage.tsx:391` is **`MilAircraftLayer`**, not a pilot.

There must be exactly **one** arbiter. Create it at page level and drill it into `GlobeChildren`. Calling `useLabelArbiter` in both places compiles cleanly and silently splits the budget in two — the compiler cannot catch that, so Step 1 asserts it.

**GDACS has no viewport culling, and Task 9 must not add any.** `GDACSLayer` does not import `selectVisible`; `EarthquakeLayer` does (`:8`, used `:109`) because it also rebuilds on `moveEnd` (`:178`). Off-screen GDACS events would consume quota if the hook did not drop them — that drop lives in the projector (Task 8), not in this layer. A previous draft said "add culling before submitting"; that reconstructs CRIT-002. Do not.

- [ ] **Step 1: Write the failing wiring tests**

This is the step the previous two revisions omitted, and both times the wiring is where the plan broke.

Extend `components/layers/__tests__/EarthquakeLayer.test.tsx` — note its viewer is a hand-built stub (`:17` `scene`, `:23` `camera`, cast `as unknown as Cesium.Viewer` at `:35`) with no real Cesium scene, so the layer must never call Cesium projection itself. With projection living in the hook (Task 8), it does not — assert that:

```ts
  it("submits label requests with world positions, never screen coordinates", () => {
    const submit = vi.fn();
    const arbiter = { submit, remove: vi.fn(), isSelected: () => true, version: 0 };
    render(<EarthquakeLayer viewer={stubViewer} earthquakes={fixtures} visible labelArbiter={arbiter} />);
    expect(submit).toHaveBeenCalledWith("earthquakes", expect.any(Array));
    const requests = submit.mock.calls[0]![1] as ReadonlyArray<{ position: unknown; text: string }>;
    expect(requests.length).toBeGreaterThan(0);
    expect(requests[0]).toHaveProperty("position");
    expect(requests[0]).not.toHaveProperty("rect");
  });

  it("removes its requests when it goes invisible", () => {
    const remove = vi.fn();
    const arbiter = { submit: vi.fn(), remove, isSelected: () => true, version: 0 };
    const { rerender } = render(<EarthquakeLayer viewer={stubViewer} earthquakes={fixtures} visible labelArbiter={arbiter} />);
    rerender(<EarthquakeLayer viewer={stubViewer} earthquakes={fixtures} visible={false} labelArbiter={arbiter} />);
    expect(remove).toHaveBeenCalledWith("earthquakes");
  });

  it("KEEPS existing label behaviour when no arbiter is supplied", () => {
    // The prop is optional. `arbiter?.isSelected(k)` alone yields undefined,
    // and `!undefined` is true — which would suppress every label and blank
    // the globe for any caller that does not pass one.
    render(<EarthquakeLayer viewer={stubViewer} earthquakes={fixtures} visible />);
    expect(labelCollectionAddSpy).toHaveBeenCalled();
  });
```

Add the equivalent three for `GDACSLayer` in a new `components/layers/__tests__/GDACSLayer.test.tsx`. `EarthquakeLayer.test.tsx:10` already defines a suitable `fakeViewer(rect = Cesium.Rectangle.fromDegrees(-180, -85, 180, 85))` with `scene.primitives`, `scene.requestRender`, a `moveEnd` registry and a mocked `computeViewRectangle` — extract it to `components/layers/__tests__/fakeViewer.ts` and import it from both files rather than copying it.

Plus one asserting the layer does **not** cull:

```ts
  it("submits a camera-independent set — the hook owns viewport truth", () => {
    // GDACSLayer has NO moveEnd listener (deps [viewer] :137 and
    // [events, visible, viewer] :173). If it culled to the viewport here, the
    // set would go stale on the first pan: events scrolling in would be missing,
    // events scrolling out would still hold quota. So it submits everything it
    // has and the hook's projector drops what is off-canvas, on every solve.
    const submit = vi.fn();
    render(<GDACSLayer viewer={fakeViewer(Cesium.Rectangle.fromDegrees(0, 0, 1, 1))}
                       events={[insideBox, farAway]} visible
                       labelArbiter={{ submit, remove: vi.fn(), isSelected: () => true, version: 0 }} />);
    const requests = submit.mock.calls.at(-1)![1] as ReadonlyArray<{ key: string }>;
    // Both, despite the viewer reporting a one-degree view rectangle.
    expect(requests.map((r) => r.key).sort())
      .toEqual([`gdacs:${farAway.id}`, `gdacs:${insideBox.id}`].sort());
  });
```

And a single-arbiter assertion in `src/test/pages/` :

```ts
  it("creates exactly one label arbiter", () => {
    const src = readFileSync(join(process.cwd(), "src/pages/WorldviewPage.tsx"), "utf8");
    expect(src.split("useLabelArbiter(").length - 1).toBe(1);
  });
```

- [ ] **Step 2: Run to verify they fail.**

- [ ] **Step 3: Wire `EarthquakeLayer`**

Add `labelArbiter?: LabelArbiterApi` to the props and a ref beside the existing ones. In `renderVisible`, after `shown` is computed, build `LabelRequest[]` — `key` `` `earthquakes:${quake.id}` ``, `position` from `Cesium.Cartesian3.fromDegrees(quake.longitude, quake.latitude, 0)`, `text` `` `M${quake.magnitude.toFixed(1)}` ``, `fontSizePx: 11` (matching `font: "11px monospace"` at `:146` — not 12; an over-sized box costs dropped labels), `pixelOffsetY` matching the layer's own `pixelOffset` (`:151`, `-size - 5`), `priority` `quake.magnitude` — and `submit("earthquakes", requests)`.

Gate the `lc.add` pass:

```ts
      const arbiter = labelArbiterRef.current;
      if (arbiter && !arbiter.isSelected(`earthquakes:${quake.id}`)) continue;
```
— note the `arbiter &&`, not `arbiter?.`; see the third test above.

Call `remove("earthquakes")` inside the `if (!visibleRef.current)` early-out and in an unmount effect. Add `labelArbiter?.version` to the render effect's dependency array.

**Leave `distanceDisplayCondition` exactly as it is (`:153`).** Task 10 owns that decision; changing it here would pre-empt the measurement.

- [ ] **Step 4: Wire `GDACSLayer`**

`GDACSEvent` (`types/index.ts:361`) is `{ id, event_type, event_name, alert_level, severity: number, country, latitude, longitude, from_date, to_date }`. Note: **`latitude`/`longitude`**, not `lat`/`lon` as on `Earthquake`; and `severity` is **already numeric**, so `priority: ev.severity` — do not re-derive a coarser rank from `alert_level`.

Add the same four pieces (props + ref, submit, `arbiter &&` guard on the `lc.add` at `:160`, remove on invisible + unmount, `version` in deps), with `layerId: "gdacs"`, `` key: `gdacs:${ev.id}` ``, `pixelOffsetY: -22` (matching `:168`), `fontSizePx: 11` (matching `font: "11px monospace"` at `:163`).

**Do NOT add viewport culling here.** It is tempting — this layer has none, unlike `EarthquakeLayer.tsx:109` — but it would reintroduce exactly the staleness that moving projection into the hook removed: with dependency arrays `[viewer]` and `[events, visible, viewer]` and no `moveEnd`, a viewport-culled set goes wrong on the first pan. The hook's projector drops off-canvas candidates at solve time, every solve.

To keep projection work bounded, cap the submitted set by rank instead of by camera — sort by `ev.severity` descending and take a generous slice (say 300). That is camera-independent, so it cannot go stale.

- [ ] **Step 5: Create one arbiter and drill it through `GlobeChildren`**

In `WorldviewPage.tsx`: `const labelArbiter = useLabelArbiter(viewer, 50);` at page level. Add `labelArbiter: LabelArbiterApi` to `GlobeChildrenProps` (`:188`), accept it in the `GlobeChildren` signature (`:202`), pass it at the `<GlobeChildren …>` mount (`:931`), forward it to `<GDACSLayer …>` (`:312`), and pass it to `<EarthquakeLayer …>` (`:909`).

`50` is `defaultDensityForProfile("BALANCED")`. A density UI control is out of scope.

- [ ] **Step 6: Run the full suite** — `npm test && npm run type-check && npm run lint` → all PASS, no regressions.

- [ ] **Step 7: Visual check within the measured band**

`npm run dev`, GDACS + Earthquakes on. Walk the camera through the altitudes where Task 1 showed labels are actually drawn. Confirm: no overlap; both layers represented; panning does not flicker labels; toggling GDACS off lets earthquake labels expand into the freed budget (that is `remove()` working). Screenshots into the PR.

**Do not calibrate `VIEW_SCALE_BUDGETS` yet** — Task 10 may delete rows.

- [ ] **Step 8: Commit** — `git commit -m "feat(frontend): arbitrate earthquake and gdacs labels against one budget"`

---

## Task 10: The DDC decision

**Files:** Modify `docs/reports/2026-08-25-task-114-label-baseline.md` (decision record) and, depending on the outcome, `lib/labelBudget.ts` and the two pilot layers.

**Inputs:** Task 1's measurements and Task 9 Step 7's observations.

This is the deferred decision the whole plan has been protecting. Do not take it before both are in hand.

- [ ] **Step 1: State the finding**

From Task 1: the highest altitude at which any label is drawn, whether created ≫ drawn, and whether tilting changes the count.

- [ ] **Step 2: Choose, and record why**

**Option A — the arbiter replaces the DDC.** Remove `distanceDisplayCondition` from the two pilots; the budget becomes the sole label authority. Coherent: the DDC *is* the incumbent per-layer declutter, and replacing ad-hoc per-layer thresholds with one coordinated budget is exactly TASK-114's stated goal. Product-visible: labels appear at globe and high-regional scale where today there are none — bounded by the `global` row (3–32) rather than unbounded. Requires a visual sign-off at globe scale and makes the `global`/`regional` rows live and calibratable.

**Option B — the budget works inside the DDC.** Leave the DDC alone and **clip the matrix to the measured live envelope** — do not guess where it ends.

Read the envelope off the DDC table at the top of this plan, then confirm it against Task 1. Six of the eight layers cap at 5e6 m, including both pilots, so labels are alive well above `metro` (which ends at 1e6 m): the whole `regional` band from 1e6 to ~5e6 is live and is exactly the mid-range view the TASK-114 screenshot sits above.

The expected clip is therefore:

| Row | Band | Under Option B |
|---|---|---|
| `street` | <50 km | live |
| `city` | <250 km | live |
| `metro` | <1 000 km | live |
| `regional` | 1 000–8 000 km | **live up to the measured cut (~5 000 km), keep it** |
| `global` | ≥8 000 km | above every DDC → **delete the row** |

Concretely: drop `global` from `VIEW_SCALE_BUDGETS` and from `LabelViewScale`, fold `≥8e6` into `regional`, and set acceptance to **0 – the measured cut**, not "street/city/metro only". Then state in the PR that only the band above the cut is unaddressed by this slice.

⚠ A previous revision of this plan wrote "restrict acceptance to street/city/metro". That contradicts this document's own DDC table and would leave the pilot with no budget across 1e6–5e6, the very band where its labels are drawn. Do not reintroduce it.

There is no third option: all eight label layers carry a DDC (2.5e6–5e6 m), so "pick a pilot layer without one" does not exist.

- [ ] **Step 3: Execute the choice**

*If A:* remove the DDC from `EarthquakeLayer.tsx:153` and `GDACSLayer.tsx:169`; add a regression test asserting the arbiter is now the only label gate; re-run the Task 9 Step 7 visual check **including globe scale**; then calibrate `VIEW_SCALE_BUDGETS` — adjusting **only** that constant and re-running `labelBudget.test.ts`, whose invariants (monotonic in density, non-increasing outward) must still hold.

*If B:* delete the `global` entry from `VIEW_SCALE_BUDGETS` and its `LabelViewScale` member; fold `≥8e6` into `regional`; update `labelBudget.test.ts` (its assertions read the matrix, so only the scale list changes); calibrate the **four** live rows (`street`, `city`, `metro`, `regional`). Do not drop `regional`.

- [ ] **Step 4: Record and commit**

Append the decision, its rationale, and the final matrix to the baseline report.

```bash
git add docs/reports/2026-08-25-task-114-label-baseline.md services/frontend/src
git commit -m "feat(frontend): resolve label distance-condition policy for TASK-114"
```

---

## Task 11: Documentation and PR

- [ ] **Step 1: Update the TASK-114 status block in `TASKS.md`**

Record: the measured label baseline and where it lives; explicit-render mode live with coverage across all scene-mutating sites (15 layers plus Graticule, both spotlights, capital pulse, GlobeViewer, spatial adapter); mil-air tick now visibility-gated; collective budget shipped as a **two-layer pilot**; the DDC decision and its rationale; and what stays open — six label layers, `EventLayer`'s label suppression, fade, density UI, default-view idle, sun/terminator in idle, FIRMS heatmap, clustering, Noir palette tokens.

- [ ] **Step 2: Run everything**

```bash
cd services/frontend && npm test && npm run type-check && npm run lint && npm run build
```

- [ ] **Step 3: Commit** — `git commit -m "docs(frontend): record TASK-114 render and label pilot"`

- [ ] **Step 4: Open the PR**

Use **superpowers:finishing-a-development-branch**. Base `main`. Title: `feat(frontend): WorldView declutter P1 — explicit render + label budget pilot`.

Body must include: links to TASK-114, this plan and the baseline report; the before/after idle GPU/CPU numbers **with the default-view caveat**; the full toggle-matrix results from Task 4 Step 5; the DDC decision from Task 10; before/after screenshots and the final `VIEW_SCALE_BUDGETS`; the attribution note (adapted from `bilawalsidhu/gods-eye-view` @ `880a672`, MIT, full text in `LICENSES/`); and the **"What this plan does NOT deliver" list verbatim** — the label work is a pilot, not a completed global budget.

---

## Deferred (explicitly out of scope)

| Item | Why |
|---|---|
| Wiring EONET / Cable / Pipeline / Datacenter / Refinery to the arbiter | Same pattern; each needs its own priority function, `pixelOffsetY`, and visual check. |
| `EventLayer` labels | Blocked by the deliberate `getTimeMs`-mode suppression at `EventLayer.tsx:236`. Product decision. |
| Idle in the default view | `DEFAULT_LAYERS` ships four animated layers on; each takes a hold while visible, not only while genuinely animating. Narrowing holds (e.g. FIRMS with an empty pulse list) is its own slice. |
| Sun/terminator advancing in idle | `enableLighting` + `maximumRenderTimeChange = Infinity` freezes it. Needs a low-frequency time-driven request. |
| Label fade in/out | Needs a per-frame animator → a continuous-render hold → undoes Track A. |
| Density UI control | Module supports the five stops; the control is a design task. |
| First-paint label flash | `submit` resolves on a microtask, so the first frame after a rebuild draws no labels. Cosmetic; fixing it means a synchronous first solve. |
| FIRMS density surface / heatmap · spatial clustering | TASK-114 P1/P0, independent of labels. |
| Hlíðskjalf Noir colour tokens | TASK-114 P1. Calibrate counts first, or you calibrate against noise. |
| Layer dedup (EONET/GDACS/FIRMS/USGS overlap) | Open editorial decision in TASK-114; not a rendering problem. |
