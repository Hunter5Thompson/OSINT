# ODIN S2 · Worldview-Port Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

## Context

**Why this change is being made.** Sprint 1 (Foundation) landed the Hlíðskjalf Noir shell, Landing page, and live signal feed — but it did so by merging three *temporary workarounds* to main (commit `7864b76`) because the existing Cesium globe code (`services/frontend/src/App.tsx` + `components/layers/*`) cannot coexist with the new shell: StrictMode crashes Cesium, legacy `position: fixed; top: 0` chrome collides with the 48px TopBar, and layer cleanup races throw `_cesiumWidget is undefined` during React 19 double-mount. Those workarounds now sit on main as shipped-with-debt (StrictMode off, route-level error boundary, TopBar hidden on `/worldview`).

Sprint 2's job is to do what §4.2 of the spec always intended: **replace the legacy fullscreen chrome with four Hlíðskjalf overlay panels (§ Layers · § Search · § Inspector · § Ticker), eliminate the three workarounds at the root cause, and ship a Worldview that lives under the shared shell.** No new globe logic. The intended outcome: `/worldview` renders the TopBar normally, StrictMode is back on globally, and the Cesium globe sits under four semi-transparent overlay panels that match Landing's visual language.

Plus a handful of S1-review follow-ups that belong in S2 because they share a file or aesthetic surface: the `SIGNAL_EVENT_TYPES` whitelist (F3), three polling-hook race conditions, one SatelliteLayer NaN bug, the `/api` vs `/api/v1` prefix split (F1), and a contract doc for the signals stream (F2).

**Goal:** Port the Cesium globe into a Hlíðskjalf-styled `/worldview` page, eliminate all three S1 workarounds at their root causes, and clear the S2 backlog from S1 review.

**Architecture:** App.tsx's fullscreen chrome (`StatusBar`, `ClockBar`, `OperationsPanel`, `RightPanel`, `ThreatRegister`, `SelectionPanel`) is deleted. Its Cesium primitives (`GlobeViewer`, `*Layer` components, `EntityClickHandler`) migrate into `WorldviewPage.tsx` unchanged. Four new overlay panels wrap the globe via a new `<OverlayPanel>` primitive, each at `rgba(18,17,14,0.84)` with 1px granite border and backdrop-blur 12px. StrictMode and the error boundary come off; TopBar renders on all routes.

**Tech Stack:** React 19, TypeScript, React Router v7, Vitest + RTL, CesiumJS 1.135, existing `useSignalFeed` hook from S1, existing Hlíðskjalf primitives (`SectionHeading`, `SignalFeedItem`, `GrainOverlay`) from `src/components/hlidskjalf/`.

---

## File Structure

**New files:**
| Path | Responsibility |
|---|---|
| `services/frontend/src/components/hlidskjalf/OverlayPanel.tsx` | Generic overlay-panel primitive: collapsed/expanded/hidden variants, § number, close button |
| `services/frontend/src/components/hlidskjalf/OverlayPanel.test.tsx` | Unit tests for panel variants & keyboard handling |
| `services/frontend/src/components/worldview/LayersPanel.tsx` | § Layers overlay — layer toggles grouped by dimension |
| `services/frontend/src/components/worldview/SearchPanel.tsx` | § Search overlay — entity search, `/` hotkey |
| `services/frontend/src/components/worldview/InspectorPanel.tsx` | § Inspector overlay — slide-in entity details |
| `services/frontend/src/components/worldview/TickerPanel.tsx` | § Ticker overlay — live signal feed |
| `docs/contracts/signals-stream.md` | F2 — Redis `events:new` stream contract |
| `docs/adr/0001-api-prefix-consolidation.md` | F1 — ADR for `/api` consolidation (executed in Task 15) |

**Modified files:**
| Path | Change |
|---|---|
| `services/frontend/src/theme/hlidskjalf.css` | Add `--hl-panel-bg`, `--hl-panel-border`, `--hl-panel-blur` tokens (Task 1) |
| `services/frontend/src/components/layers/SatelliteLayer.tsx` | Guard NaN `satData.lat` in mouse-move cone (Task 3) |
| `services/frontend/src/hooks/useEarthquakes.ts` | `cancelled` guard (Task 4) |
| `services/frontend/src/hooks/useFIRMSHotspots.ts` | `cancelled` guard (Task 4) |
| `services/frontend/src/hooks/useAircraftTracks.ts` | `cancelled` guard (Task 4) |
| `services/frontend/src/main.tsx` | Re-enable `<StrictMode>` (Task 5) |
| `services/frontend/src/app/AppShell.tsx` | Remove `isWorldview` hiding (Task 6) |
| `services/frontend/src/app/router.tsx` | Remove `errorElement` (Task 8) |
| `services/frontend/src/test/routing/legacyRedirect.test.tsx` | Drop S1 comment about TopBar hide (Task 6) |
| `services/frontend/src/pages/WorldviewPage.tsx` | Absorb globe + panels (Task 7) |
| `services/frontend/src/hooks/useSignalFeed.ts` | Drop whitelist, accept any codebook_type via wildcard + register-by-CustomEvent, add cleanup (Task 13) |
| `services/frontend/src/services/api.ts` | `BASE = "/api"` + new paths (Task 15) |
| `services/backend/app/main.py` | Remount REST routers at `/api`; dual-mount `@app.get` health/config via `add_api_route`; `/api/v1` back-compat aliases (Task 15) |

**Deleted files:**
| Path | Reason |
|---|---|
| `services/frontend/src/App.tsx` | Replaced by WorldviewPage content |
| `services/frontend/src/pages/WorldviewErrorBoundary.tsx` | S1 workaround no longer needed |
| `services/frontend/src/components/ui/OperationsPanel.tsx` | Replaced by LayersPanel |
| `services/frontend/src/components/ui/RightPanel.tsx` | Out of scope for S2; Munin moves to Briefing in S3 |
| `services/frontend/src/components/ui/ThreatRegister.tsx` | Replaced by Landing hotspots |
| `services/frontend/src/components/ui/ClockBar.tsx` | Replaced by TopBar clock |
| `services/frontend/src/components/ui/StatusBar.tsx` | Merged into Ticker / Inspector |
| `services/frontend/src/components/ui/SelectionPanel.tsx` | Replaced by InspectorPanel |

---

## Task Decomposition

### Task 0: Setup — Branch & Worktree

**Files:**
- Worktree: `../osint-s2-worldview` (outside main checkout)

- [ ] **Step 1: Verify main is clean and ahead of origin**

Run: `git status --short && git log main..origin/main --oneline`
Expected: no uncommitted changes that would leak; no unpushed commits on main.

- [ ] **Step 2: Create worktree on new branch**

```bash
git worktree add -b feature/odin-s2-worldview-port ../osint-s2-worldview main
cd ../osint-s2-worldview
```

Expected: new directory with detached tree, checked out to `feature/odin-s2-worldview-port`.

- [ ] **Step 3: Baseline test run — capture green state**

```bash
cd services/frontend
npm install
npx vitest run
```

Expected: all tests PASS. Record count (e.g. "100/100").

- [ ] **Step 4: Baseline lint + type-check**

```bash
npm run lint && npm run type-check
```

Expected: both PASS.

- [ ] **Step 5: Commit the (empty) branch-start marker**

Not needed — the worktree creation creates no new commit. Proceed to Task 1.

---

### Task 1: Add Hlidskjalf panel CSS tokens

**Files:**
- Modify: `services/frontend/src/theme/hlidskjalf.css` (add lines in `:root, .hlid` block, currently ends ~line 81)
- Test: `services/frontend/src/test/theme/panelTokens.test.ts` (new)

- [ ] **Step 1: Write the failing token-availability test**

Create `services/frontend/src/test/theme/panelTokens.test.ts`:

```typescript
import { describe, it, expect, beforeAll } from "vitest";

describe("hlidskjalf panel tokens", () => {
  beforeAll(async () => {
    const css = await import("../../theme/hlidskjalf.css?raw");
    const style = document.createElement("style");
    style.textContent = css.default;
    document.head.appendChild(style);
  });

  it("exposes --hl-panel-bg as a CSS variable on :root", () => {
    const value = getComputedStyle(document.documentElement).getPropertyValue("--hl-panel-bg");
    expect(value.trim()).toBe("rgba(18, 17, 14, 0.84)");
  });

  it("exposes --hl-panel-border as 1px solid granite", () => {
    const value = getComputedStyle(document.documentElement).getPropertyValue("--hl-panel-border");
    expect(value.trim()).toBe("1px solid var(--granite)");
  });

  it("exposes --hl-panel-blur as 12px blur", () => {
    const value = getComputedStyle(document.documentElement).getPropertyValue("--hl-panel-blur");
    expect(value.trim()).toBe("blur(12px)");
  });
});
```

- [ ] **Step 2: Run tests — verify failure**

Run: `npx vitest run src/test/theme/panelTokens.test.ts`
Expected: 3 FAIL with empty token values.

- [ ] **Step 3: Add the tokens**

Open `services/frontend/src/theme/hlidskjalf.css`, locate the `:root, .hlid {` block (ends at `--rust`) and append *before the closing brace*:

```css
  /* Panel / overlay (Hlíðskjalf § surfaces — Worldview, Briefing, War Room) */
  --hl-panel-bg: rgba(18, 17, 14, 0.84);
  --hl-panel-border: 1px solid var(--granite);
  --hl-panel-blur: blur(12px);
```

- [ ] **Step 4: Run tests — verify pass**

Run: `npx vitest run src/test/theme/panelTokens.test.ts`
Expected: 3 PASS.

- [ ] **Step 5: Commit**

```bash
git add services/frontend/src/theme/hlidskjalf.css services/frontend/src/test/theme/panelTokens.test.ts
git commit -m "feat(frontend): add Hlidskjalf panel CSS tokens for § overlays"
```

---

### Task 2: `<OverlayPanel>` primitive

**Files:**
- Create: `services/frontend/src/components/hlidskjalf/OverlayPanel.tsx`
- Create: `services/frontend/src/components/hlidskjalf/OverlayPanel.test.tsx`

- [ ] **Step 1: Write the failing test**

Create `services/frontend/src/components/hlidskjalf/OverlayPanel.test.tsx`:

```typescript
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { OverlayPanel } from "./OverlayPanel";

describe("OverlayPanel", () => {
  it("renders § number and label when expanded", () => {
    render(
      <OverlayPanel paragraph="I" label="Layers" variant="expanded">
        <p>body</p>
      </OverlayPanel>,
    );
    expect(screen.getByText(/§ I · Layers/i)).toBeInTheDocument();
    expect(screen.getByText("body")).toBeInTheDocument();
  });

  it("hides body when variant is 'collapsed' and shows tab affordance", () => {
    render(
      <OverlayPanel paragraph="II" label="Search" variant="collapsed">
        <p data-testid="body">body</p>
      </OverlayPanel>,
    );
    expect(screen.queryByTestId("body")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /expand Search/i })).toBeInTheDocument();
  });

  it("does not render at all when variant is 'hidden'", () => {
    const { container } = render(
      <OverlayPanel paragraph="III" label="Inspector" variant="hidden">
        <p>body</p>
      </OverlayPanel>,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("calls onClose when close button is clicked", () => {
    const onClose = vi.fn();
    render(
      <OverlayPanel paragraph="I" label="Layers" variant="expanded" onClose={onClose}>
        <p>body</p>
      </OverlayPanel>,
    );
    fireEvent.click(screen.getByRole("button", { name: /close Layers/i }));
    expect(onClose).toHaveBeenCalledOnce();
  });

  it("calls onExpand when tab is clicked in collapsed variant", () => {
    const onExpand = vi.fn();
    render(
      <OverlayPanel paragraph="II" label="Search" variant="collapsed" onExpand={onExpand}>
        <p>body</p>
      </OverlayPanel>,
    );
    fireEvent.click(screen.getByRole("button", { name: /expand Search/i }));
    expect(onExpand).toHaveBeenCalledOnce();
  });

  it("applies panel bg + border + blur from CSS tokens", () => {
    render(
      <OverlayPanel paragraph="I" label="Layers" variant="expanded">
        <p>body</p>
      </OverlayPanel>,
    );
    const panel = screen.getByRole("region");
    expect(panel).toHaveStyle({
      background: "var(--hl-panel-bg)",
      border: "var(--hl-panel-border)",
      backdropFilter: "var(--hl-panel-blur)",
    });
  });
});
```

- [ ] **Step 2: Run tests — verify failure**

Run: `npx vitest run src/components/hlidskjalf/OverlayPanel.test.tsx`
Expected: 6 FAIL with "Cannot find module './OverlayPanel'".

- [ ] **Step 3: Implement `OverlayPanel`**

Create `services/frontend/src/components/hlidskjalf/OverlayPanel.tsx`:

```typescript
import type { ReactNode, CSSProperties } from "react";

export type OverlayPanelVariant = "expanded" | "collapsed" | "hidden";

export interface OverlayPanelProps {
  paragraph: string;
  label: string;
  variant: OverlayPanelVariant;
  onClose?: () => void;
  onExpand?: () => void;
  width?: number;
  children: ReactNode;
  style?: CSSProperties;
}

const panelBase: CSSProperties = {
  background: "var(--hl-panel-bg)",
  border: "var(--hl-panel-border)",
  backdropFilter: "var(--hl-panel-blur)",
  WebkitBackdropFilter: "var(--hl-panel-blur)",
  color: "var(--bone)",
  fontFamily: "'Hanken Grotesk', sans-serif",
  fontSize: "12px",
  pointerEvents: "auto",
};

const headerStyle: CSSProperties = {
  display: "flex",
  alignItems: "center",
  justifyContent: "space-between",
  padding: "10px 12px",
  borderBottom: "var(--hl-panel-border)",
};

const paragraphStyle: CSSProperties = {
  fontFamily: "'Hanken Grotesk', sans-serif",
  fontSize: "10px",
  letterSpacing: "0.22em",
  textTransform: "uppercase",
  color: "var(--stone)",
};

const closeBtn: CSSProperties = {
  background: "transparent",
  border: "none",
  color: "var(--ash)",
  cursor: "pointer",
  fontFamily: "'Martian Mono', monospace",
  fontSize: "11px",
  padding: "0 4px",
};

const tabStyle: CSSProperties = {
  ...panelBase,
  width: "32px",
  padding: "12px 6px",
  writingMode: "vertical-rl",
  transform: "rotate(180deg)",
  cursor: "pointer",
};

export function OverlayPanel({
  paragraph,
  label,
  variant,
  onClose,
  onExpand,
  width = 320,
  children,
  style,
}: OverlayPanelProps) {
  if (variant === "hidden") return null;

  if (variant === "collapsed") {
    return (
      <button
        type="button"
        aria-label={`expand ${label}`}
        onClick={onExpand}
        style={{ ...tabStyle, ...style }}
      >
        § {paragraph} · {label}
      </button>
    );
  }

  return (
    <section
      role="region"
      aria-label={label}
      style={{ ...panelBase, width: `${width}px`, ...style }}
    >
      <header style={headerStyle}>
        <span style={paragraphStyle}>§ {paragraph} · {label}</span>
        {onClose ? (
          <button
            type="button"
            aria-label={`close ${label}`}
            onClick={onClose}
            style={closeBtn}
          >
            ×
          </button>
        ) : null}
      </header>
      <div style={{ padding: "12px" }}>{children}</div>
    </section>
  );
}
```

- [ ] **Step 4: Run tests — verify pass**

Run: `npx vitest run src/components/hlidskjalf/OverlayPanel.test.tsx`
Expected: 6 PASS.

- [ ] **Step 5: Commit**

```bash
git add services/frontend/src/components/hlidskjalf/OverlayPanel.tsx services/frontend/src/components/hlidskjalf/OverlayPanel.test.tsx
git commit -m "feat(frontend): add OverlayPanel primitive for § worldview overlays"
```

---

### Task 3: Fix SatelliteLayer NaN guard

**Files:**
- Modify: `services/frontend/src/components/layers/SatelliteLayer.tsx:241-307`
- Test: `services/frontend/src/components/layers/SatelliteLayer.test.tsx` (new — add just the pick test)

- [ ] **Step 1: Write the failing test**

Create `services/frontend/src/components/layers/SatelliteLayer.test.tsx`:

```typescript
import { describe, it, expect, vi } from "vitest";

describe("SatelliteLayer satData guard", () => {
  it("returns early when satData.lat is NaN", async () => {
    const module = await import("./SatelliteLayer");
    const { shouldRenderCone } = module as unknown as {
      shouldRenderCone: (sat: { lat: number; lon: number; footprint_radius_km?: number }) => boolean;
    };
    expect(shouldRenderCone({ lat: NaN, lon: 10, footprint_radius_km: 100 })).toBe(false);
    expect(shouldRenderCone({ lat: 50, lon: NaN, footprint_radius_km: 100 })).toBe(false);
    expect(shouldRenderCone({ lat: 50, lon: 10, footprint_radius_km: 100 })).toBe(true);
    expect(shouldRenderCone({ lat: 50, lon: 10, footprint_radius_km: 0 })).toBe(false);
  });
});
```

- [ ] **Step 2: Run tests — verify failure**

Run: `npx vitest run src/components/layers/SatelliteLayer.test.tsx`
Expected: FAIL with "shouldRenderCone is not a function".

- [ ] **Step 3: Extract and export pure guard**

In `services/frontend/src/components/layers/SatelliteLayer.tsx`, add at module top (below imports):

```typescript
export function shouldRenderCone(sat: {
  lat: number;
  lon: number;
  footprint_radius_km?: number;
}): boolean {
  if (!Number.isFinite(sat.lat) || !Number.isFinite(sat.lon)) return false;
  if (!sat.footprint_radius_km || sat.footprint_radius_km <= 0) return false;
  return true;
}
```

Then replace the current check inside the mouse-move handler (around line 249, the `if (!satData || !satData.footprint_radius_km || ...)` line) with:

```typescript
if (!satData || !shouldRenderCone(satData)) return;
```

- [ ] **Step 4: Run tests — verify pass**

Run: `npx vitest run src/components/layers/SatelliteLayer.test.tsx`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add services/frontend/src/components/layers/SatelliteLayer.tsx services/frontend/src/components/layers/SatelliteLayer.test.tsx
git commit -m "fix(frontend): guard NaN lat/lon in SatelliteLayer footprint cone"
```

---

### Task 4: Polling-hook cancelled guards

**Files:**
- Modify: `services/frontend/src/hooks/useEarthquakes.ts`
- Modify: `services/frontend/src/hooks/useFIRMSHotspots.ts`
- Modify: `services/frontend/src/hooks/useAircraftTracks.ts`
- Test: `services/frontend/src/test/hooks/pollingRace.test.tsx` (new)

- [ ] **Step 1: Write the failing test**

Create `services/frontend/src/test/hooks/pollingRace.test.tsx`:

```typescript
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import * as api from "../../services/api";
import { useEarthquakes } from "../../hooks/useEarthquakes";

describe("useEarthquakes cancelled guard", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("does not setState after unmount when fetch resolves late", async () => {
    let resolve!: (v: unknown) => void;
    const pending = new Promise<unknown>((r) => { resolve = r; });
    vi.spyOn(api, "getEarthquakes").mockReturnValue(pending as never);

    const { result, unmount } = renderHook(() => useEarthquakes(true));
    unmount();

    // Resolve AFTER unmount — must not produce a React warning and list stays empty.
    await act(async () => {
      resolve([{ id: "eq1", latitude: 0, longitude: 0, magnitude: 4.5, time: "2026-04-21T00:00:00Z" }]);
      await Promise.resolve();
    });

    expect(result.current.earthquakes).toEqual([]);
  });
});
```

- [ ] **Step 2: Run tests — verify failure**

Run: `npx vitest run src/test/hooks/pollingRace.test.tsx`
Expected: FAIL — React logs "state update on unmounted component" or test sees data leak.

- [ ] **Step 3: Patch `useEarthquakes.ts`**

Replace the hook body with:

```typescript
import { useCallback, useEffect, useState } from "react";
import { getEarthquakes } from "../services/api";
import type { Earthquake } from "../types";

const POLL_INTERVAL = 60_000;

export function useEarthquakes(enabled: boolean) {
  const [earthquakes, setEarthquakes] = useState<Earthquake[]>([]);
  const [lastUpdate, setLastUpdate] = useState<Date | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!enabled) {
      setEarthquakes([]);
      return;
    }
    let cancelled = false;
    const run = async () => {
      setLoading(true);
      try {
        const data = await getEarthquakes();
        if (cancelled) return;
        setEarthquakes(data);
        setLastUpdate(new Date());
      } catch {
        // swallow — UI stays on last-known state
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    void run();
    const timer = setInterval(() => { void run(); }, POLL_INTERVAL);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [enabled]);

  return { earthquakes, lastUpdate, loading };
}
```

- [ ] **Step 4: Apply the same pattern to `useFIRMSHotspots.ts` and `useAircraftTracks.ts`**

For `useFIRMSHotspots.ts` — same structure, replace `getEarthquakes` with `getFIRMSHotspots`, state with `hotspots`, return `{ hotspots, lastUpdate, loading }`.

For `useAircraftTracks.ts` — same structure, replace with `getAircraftTracks(sinceHours)`, state with `tracks`, return `{ tracks, lastUpdate, loading }`. Preserve the `sinceHours` parameter.

- [ ] **Step 5: Run tests — verify pass**

Run: `npx vitest run src/test/hooks/pollingRace.test.tsx`
Expected: PASS, no unmount warnings.

- [ ] **Step 6: Run full FE test suite — verify no regressions**

Run: `npx vitest run`
Expected: all existing tests still PASS.

- [ ] **Step 7: Commit**

```bash
git add services/frontend/src/hooks/useEarthquakes.ts services/frontend/src/hooks/useFIRMSHotspots.ts services/frontend/src/hooks/useAircraftTracks.ts services/frontend/src/test/hooks/pollingRace.test.tsx
git commit -m "fix(frontend): guard polling hooks against post-unmount setState"
```

---

### Task 5: Re-enable `<StrictMode>`

**Files:**
- Modify: `services/frontend/src/main.tsx`
- Test: `services/frontend/src/test/strictMode.test.tsx` (new)

- [ ] **Step 1: Write the failing test**

Create `services/frontend/src/test/strictMode.test.tsx` — note the ESM-safe path resolution (`__dirname` is undefined in Vitest ESM):

```typescript
import { describe, it, expect } from "vitest";
import fs from "node:fs";

// ESM: resolve via import.meta.url rather than __dirname (which is undefined).
const mainSrc = fs.readFileSync(
  new URL("../main.tsx", import.meta.url),
  "utf8",
);

describe("main.tsx StrictMode", () => {
  it("wraps RouterProvider in StrictMode", () => {
    expect(mainSrc).toMatch(/<StrictMode>[\s\S]*<RouterProvider[\s\S]*<\/StrictMode>/);
  });

  it("imports StrictMode from react", () => {
    expect(mainSrc).toMatch(/import\s+\{[^}]*StrictMode[^}]*\}\s+from\s+"react"/);
  });
});
```

- [ ] **Step 2: Run tests — verify failure**

Run: `npx vitest run src/test/strictMode.test.tsx`
Expected: 2 FAIL (StrictMode not imported, not wrapping).

- [ ] **Step 3: Restore StrictMode in `main.tsx`**

Replace `services/frontend/src/main.tsx` entirely:

```typescript
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { RouterProvider } from "react-router-dom";
import { router } from "./app/router";
import "./index.css";

const root = document.getElementById("root");
if (!root) throw new Error("Root element not found");

createRoot(root).render(
  <StrictMode>
    <RouterProvider router={router} />
  </StrictMode>,
);
```

- [ ] **Step 4: Run tests — verify pass + no regressions**

Run: `npx vitest run`
Expected: all PASS including new strictMode test.

- [ ] **Step 5: Smoke-test the dev server (manual)**

```bash
npm run dev
```

Open `http://localhost:5173/worldview` in a browser. Verify: globe renders, no console errors about `_cesiumWidget is undefined` or "Resource already being fetched", no entity-cleanup crashes. Close dev server after verification.

Note: if a crash surfaces, it means Task 3/4 missed a code path — fix in those tasks before proceeding, don't work around here.

- [ ] **Step 6: Commit**

```bash
git add services/frontend/src/main.tsx services/frontend/src/test/strictMode.test.tsx
git commit -m "fix(frontend): re-enable StrictMode now that Cesium races are guarded"
```

---

### Task 6: Revert AppShell TopBar-hiding workaround

**Files:**
- Modify: `services/frontend/src/app/AppShell.tsx`
- Modify: `services/frontend/src/test/routing/legacyRedirect.test.tsx` (update assertion)
- Test: `services/frontend/src/test/app/appShell.test.tsx` (new)

- [ ] **Step 1: Write the failing test**

Create `services/frontend/src/test/app/appShell.test.tsx`:

```typescript
import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { routes } from "../../app/router";

vi.mock("../../pages/WorldviewPage", () => ({
  WorldviewPage: () => <div data-testid="worldview-page">worldview</div>,
}));
vi.mock("../../pages/LandingPage", () => ({
  LandingPage: () => <div data-testid="landing-page">landing</div>,
}));

describe("AppShell", () => {
  it("renders TopBar on /", () => {
    const router = createMemoryRouter(routes, { initialEntries: ["/"] });
    render(<RouterProvider router={router} />);
    expect(screen.getByRole("banner")).toBeInTheDocument();
  });

  it("renders TopBar on /worldview (no S1 hide)", () => {
    const router = createMemoryRouter(routes, { initialEntries: ["/worldview"] });
    render(<RouterProvider router={router} />);
    expect(screen.getByRole("banner")).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run tests — verify failure**

Run: `npx vitest run src/test/app/appShell.test.tsx`
Expected: FAIL — TopBar not present on /worldview.

- [ ] **Step 3: Remove the `isWorldview` hide from AppShell**

Replace `services/frontend/src/app/AppShell.tsx`:

```typescript
import { Outlet } from "react-router-dom";
import { TopBar } from "../components/hlidskjalf/TopBar";

export function AppShell() {
  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100vh" }}>
      <TopBar />
      <main
        style={{
          flex: 1,
          display: "flex",
          flexDirection: "column",
          minHeight: 0,
          position: "relative",
        }}
      >
        <Outlet />
      </main>
    </div>
  );
}
```

- [ ] **Step 4: Rewrite the stale `/worldview` assertion in `legacyRedirect.test.tsx`**

The existing test at lines 53-59 explicitly asserts `queryByText("Hlíðskjalf")).not.toBeInTheDocument()` on `/worldview` (the S1 workaround behaviour). With the AppShell change in Step 3 this assertion becomes false, so the test case must be *inverted*, not just de-commented.

Open `services/frontend/src/test/routing/legacyRedirect.test.tsx` and replace the entire test case:

```typescript
  it("hides TopBar on Worldview and lets legacy chrome take over (S1 temporary)", async () => {
    renderAt("/worldview");
    // S1 workaround: App.tsx StatusBar+ClockBar collide with TopBar and
    // Cesium needs a 100vh parent. S2 Worldview-Port will restore TopBar.
    expect(screen.queryByText("Hlíðskjalf")).not.toBeInTheDocument();
    expect(await screen.findByTestId("worldview-page")).toBeInTheDocument();
  });
```

with:

```typescript
  it("renders AppShell TopBar on Worldview", async () => {
    renderAt("/worldview");
    expect(await screen.findByText("Hlíðskjalf")).toBeInTheDocument();
    expect(screen.getByTestId("worldview-page")).toBeInTheDocument();
  });
```

- [ ] **Step 5: Run tests — verify pass**

Run: `npx vitest run`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add services/frontend/src/app/AppShell.tsx services/frontend/src/test/app/appShell.test.tsx services/frontend/src/test/routing/legacyRedirect.test.tsx
git commit -m "refactor(frontend): TopBar always renders (revert S1 /worldview hide)"
```

---

### Task 7: Migrate App.tsx → WorldviewPage.tsx (strip legacy chrome)

**Files:**
- Modify: `services/frontend/src/pages/WorldviewPage.tsx` (absorb globe)
- Delete: `services/frontend/src/App.tsx`
- Delete: `services/frontend/src/components/ui/ClockBar.tsx`
- Delete: `services/frontend/src/components/ui/StatusBar.tsx`
- Delete: `services/frontend/src/components/ui/OperationsPanel.tsx`
- Delete: `services/frontend/src/components/ui/RightPanel.tsx`
- Delete: `services/frontend/src/components/ui/ThreatRegister.tsx`
- Delete: `services/frontend/src/components/ui/SelectionPanel.tsx`
- Test: `services/frontend/src/test/pages/worldviewPage.test.tsx` (new)

- [ ] **Step 1: Write the failing structural test**

Create `services/frontend/src/test/pages/worldviewPage.test.tsx`:

```typescript
import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";

vi.mock("../../components/globe/GlobeViewer", () => ({
  GlobeViewer: ({ onViewerReady }: { onViewerReady: (v: unknown) => void }) => {
    onViewerReady(null);
    return <div data-testid="globe-viewer" />;
  },
}));
vi.mock("../../components/globe/PerformanceGuard", () => ({
  PerformanceGuard: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));
vi.mock("../../services/api", () => ({
  getConfig: vi.fn().mockResolvedValue({
    cesium_ion_token: "",
    default_layers: {},
    api_version: "v1",
  }),
  getHotspots: vi.fn().mockResolvedValue([]),
}));

import { WorldviewPage } from "../../pages/WorldviewPage";

describe("WorldviewPage", () => {
  it("renders the globe and four overlay panel tabs/expanded forms", async () => {
    render(<WorldviewPage />);
    expect(await screen.findByTestId("globe-viewer")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /expand Layers/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /expand Search/i })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: /Ticker/i })).toBeInTheDocument();
  });

  it("does not render legacy ClockBar / StatusBar / ThreatRegister", () => {
    render(<WorldviewPage />);
    expect(screen.queryByTestId("clock-bar")).not.toBeInTheDocument();
    expect(screen.queryByTestId("status-bar")).not.toBeInTheDocument();
    expect(screen.queryByTestId("threat-register")).not.toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run tests — verify failure**

Run: `npx vitest run src/test/pages/worldviewPage.test.tsx`
Expected: FAIL — legacy chrome still renders, overlay panels don't exist yet.

- [ ] **Step 3: Rewrite `WorldviewPage.tsx` with globe + placeholder panels**

Replace `services/frontend/src/pages/WorldviewPage.tsx`:

```typescript
import { useCallback, useEffect, useState } from "react";
import * as Cesium from "cesium";
import { PerformanceGuard } from "../components/globe/PerformanceGuard";
import { GlobeViewer } from "../components/globe/GlobeViewer";
import { EntityClickHandler } from "../components/globe/EntityClickHandler";
import { FlightLayer } from "../components/layers/FlightLayer";
import { SatelliteLayer } from "../components/layers/SatelliteLayer";
import { EarthquakeLayer } from "../components/layers/EarthquakeLayer";
import { ShipLayer } from "../components/layers/ShipLayer";
import { CCTVLayer } from "../components/layers/CCTVLayer";
import { EventLayer } from "../components/layers/EventLayer";
import { CableLayer } from "../components/layers/CableLayer";
import { PipelineLayer } from "../components/layers/PipelineLayer";
import { FIRMSLayer } from "../components/layers/FIRMSLayer";
import { MilAircraftLayer } from "../components/layers/MilAircraftLayer";
import { DatacenterLayer } from "../components/layers/DatacenterLayer";
import { RefineryLayer } from "../components/layers/RefineryLayer";
import { EONETLayer } from "../components/layers/EONETLayer";
import { GDACSLayer } from "../components/layers/GDACSLayer";
import { OverlayPanel } from "../components/hlidskjalf/OverlayPanel";
import { LayersPanel } from "../components/worldview/LayersPanel";
import { SearchPanel } from "../components/worldview/SearchPanel";
import { InspectorPanel } from "../components/worldview/InspectorPanel";
import { TickerPanel } from "../components/worldview/TickerPanel";
import { useFlights } from "../hooks/useFlights";
import { useSatellites } from "../hooks/useSatellites";
import { useEarthquakes } from "../hooks/useEarthquakes";
import { useEvents } from "../hooks/useEvents";
import { useCables } from "../hooks/useCables";
import { useVessels } from "../hooks/useVessels";
import { usePipelines } from "../hooks/usePipelines";
import { useFIRMSHotspots } from "../hooks/useFIRMSHotspots";
import { useAircraftTracks } from "../hooks/useAircraftTracks";
import { useDatacenters } from "../hooks/useDatacenters";
import { useRefineries } from "../hooks/useRefineries";
import { useEONETEvents } from "../hooks/useEONETEvents";
import { useGDACSEvents } from "../hooks/useGDACSEvents";
import { getConfig } from "../services/api";
import type {
  LayerVisibility,
  ShaderType,
  ClientConfig,
  DatacenterProperties,
  RefineryProperties,
} from "../types";
import type { Selected } from "../components/worldview/InspectorPanel";

type PanelId = "layers" | "search";

const DEFAULT_LAYERS: LayerVisibility = {
  flights: true,
  satellites: true,
  earthquakes: true,
  vessels: false,
  cctv: false,
  events: false,
  cables: false,
  pipelines: false,
  countryBorders: true,
  cityBuildings: true,
  firmsHotspots: true,
  milAircraft: true,
  datacenters: false,
  refineries: false,
  eonet: false,
  gdacs: false,
};

export function WorldviewPage() {
  const [viewer, setViewer] = useState<Cesium.Viewer | null>(null);
  const [config, setConfig] = useState<ClientConfig | null>(null);
  const [layers, setLayers] = useState<LayerVisibility>(DEFAULT_LAYERS);
  const [activeShader, setActiveShader] = useState<ShaderType>("none");
  const [selected, setSelected] = useState<Selected | null>(null);
  const [expanded, setExpanded] = useState<Record<PanelId, boolean>>({
    layers: false,
    search: false,
  });

  const { flights } = useFlights(layers.flights);
  const { satellites } = useSatellites(layers.satellites);
  const { earthquakes } = useEarthquakes(layers.earthquakes);
  const { events } = useEvents(layers.events);
  const { cables, landingPoints } = useCables(layers.cables);
  const { vessels } = useVessels(layers.vessels);
  const { pipelines: pipelineData } = usePipelines(layers.pipelines);
  const { hotspots: firmsHotspots } = useFIRMSHotspots(layers.firmsHotspots);
  const { tracks: milTracks } = useAircraftTracks(layers.milAircraft);
  const { datacenters: datacenterData } = useDatacenters(layers.datacenters);
  const { refineries: refineryData } = useRefineries(layers.refineries);
  const { events: eonetEvents } = useEONETEvents(layers.eonet);
  const { events: gdacsEvents } = useGDACSEvents(layers.gdacs);

  useEffect(() => {
    void getConfig()
      .then(setConfig)
      .catch(() => {
        setConfig({
          cesium_ion_token: "",
          default_layers: DEFAULT_LAYERS,
          api_version: "v1",
        });
      });
  }, []);

  useEffect(() => {
    if (config?.default_layers) {
      setLayers((prev) => ({ ...prev, ...config.default_layers }));
    }
  }, [config]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "/") {
        e.preventDefault();
        setExpanded((p) => ({ ...p, search: true }));
      } else if (e.key.toLowerCase() === "l" && !e.ctrlKey && !e.metaKey) {
        const target = e.target as HTMLElement | null;
        if (target && ["INPUT", "TEXTAREA"].includes(target.tagName)) return;
        setExpanded((p) => ({ ...p, layers: !p.layers }));
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const handleToggleLayer = useCallback((layer: keyof LayerVisibility) => {
    setLayers((prev) => ({ ...prev, [layer]: !prev[layer] }));
  }, []);

  const handleViewerReady = useCallback((v: Cesium.Viewer) => {
    setViewer(v);
  }, []);

  if (!config) {
    return (
      <div style={{ flex: 1, display: "grid", placeItems: "center", color: "var(--stone)" }}>
        <span className="mono">§ Initializing worldview…</span>
      </div>
    );
  }

  return (
    <PerformanceGuard>
      <div style={{ flex: 1, position: "relative", minHeight: 0 }}>
        <GlobeViewer
          onViewerReady={handleViewerReady}
          cesiumToken={config.cesium_ion_token}
          activeShader={activeShader}
          showCountryBorders={layers.countryBorders}
          showCityBuildings={layers.cityBuildings}
        />

        <FlightLayer viewer={viewer} flights={flights} visible={layers.flights} />
        <SatelliteLayer viewer={viewer} satellites={satellites} visible={layers.satellites} />
        <EarthquakeLayer viewer={viewer} earthquakes={earthquakes} visible={layers.earthquakes} />
        <ShipLayer viewer={viewer} vessels={vessels} visible={layers.vessels} />
        <CCTVLayer viewer={viewer} visible={layers.cctv} />
        <EventLayer viewer={viewer} events={events} visible={layers.events} />
        <CableLayer viewer={viewer} cables={cables} landingPoints={landingPoints} visible={layers.cables} />
        <PipelineLayer viewer={viewer} pipelines={pipelineData} visible={layers.pipelines} />
        <FIRMSLayer
          viewer={viewer}
          hotspots={firmsHotspots}
          visible={layers.firmsHotspots}
          onSelect={(h) => setSelected({ type: "firms", data: h })}
        />
        <MilAircraftLayer
          viewer={viewer}
          tracks={milTracks}
          visible={layers.milAircraft}
          onSelect={(t) => setSelected({ type: "aircraft", data: t })}
        />
        <DatacenterLayer
          viewer={viewer}
          datacenters={datacenterData}
          visible={layers.datacenters}
          onSelect={(d: DatacenterProperties) => setSelected({ type: "datacenter", data: d })}
        />
        <RefineryLayer
          viewer={viewer}
          refineries={refineryData}
          visible={layers.refineries}
          onSelect={(r: RefineryProperties) => setSelected({ type: "refinery", data: r })}
        />
        <EONETLayer
          viewer={viewer}
          events={eonetEvents}
          visible={layers.eonet}
          onSelect={(e) => setSelected({ type: "eonet", data: e })}
        />
        <GDACSLayer
          viewer={viewer}
          events={gdacsEvents}
          visible={layers.gdacs}
          onSelect={(e) => setSelected({ type: "gdacs", data: e })}
        />
        <EntityClickHandler viewer={viewer} />

        {/* § Layers — top-left, default collapsed */}
        <div style={{ position: "absolute", top: 16, left: 16, zIndex: 10 }}>
          {expanded.layers ? (
            <OverlayPanel
              paragraph="I"
              label="Layers"
              variant="expanded"
              onClose={() => setExpanded((p) => ({ ...p, layers: false }))}
            >
              <LayersPanel
                layers={layers}
                onToggle={handleToggleLayer}
                activeShader={activeShader}
                onShaderChange={setActiveShader}
              />
            </OverlayPanel>
          ) : (
            <OverlayPanel
              paragraph="I"
              label="Layers"
              variant="collapsed"
              onExpand={() => setExpanded((p) => ({ ...p, layers: true }))}
            >
              {null}
            </OverlayPanel>
          )}
        </div>

        {/* § Search — top-right, default collapsed, / hotkey */}
        <div style={{ position: "absolute", top: 16, right: 16, zIndex: 10 }}>
          {expanded.search ? (
            <OverlayPanel
              paragraph="II"
              label="Search"
              variant="expanded"
              onClose={() => setExpanded((p) => ({ ...p, search: false }))}
            >
              <SearchPanel viewer={viewer} />
            </OverlayPanel>
          ) : (
            <OverlayPanel
              paragraph="II"
              label="Search"
              variant="collapsed"
              onExpand={() => setExpanded((p) => ({ ...p, search: true }))}
            >
              {null}
            </OverlayPanel>
          )}
        </div>

        {/* § Inspector — right slide-in on entity click */}
        <div style={{ position: "absolute", top: 16, right: 64, zIndex: 10 }}>
          <InspectorPanel
            selected={selected}
            onClose={() => setSelected(null)}
            viewer={viewer}
          />
        </div>

        {/* § Ticker — bottom-left, default expanded */}
        <div style={{ position: "absolute", bottom: 16, left: 16, zIndex: 10 }}>
          <TickerPanel />
        </div>
      </div>
    </PerformanceGuard>
  );
}
```

- [ ] **Step 4: Create placeholder stubs for the four panels (real content in Tasks 9-12)**

Create `services/frontend/src/components/worldview/LayersPanel.tsx`:

```typescript
import type { LayerVisibility, ShaderType } from "../../types";

export interface LayersPanelProps {
  layers: LayerVisibility;
  onToggle: (layer: keyof LayerVisibility) => void;
  activeShader: ShaderType;
  onShaderChange: (shader: ShaderType) => void;
}

export function LayersPanel(_props: LayersPanelProps) {
  return <div className="mono" style={{ color: "var(--stone)" }}>§ placeholder</div>;
}
```

Create `services/frontend/src/components/worldview/SearchPanel.tsx`:

```typescript
import type * as Cesium from "cesium";

export interface SearchPanelProps {
  viewer: Cesium.Viewer | null;
}

export function SearchPanel(_props: SearchPanelProps) {
  return <div className="mono" style={{ color: "var(--stone)" }}>§ placeholder</div>;
}
```

Create `services/frontend/src/components/worldview/InspectorPanel.tsx`:

```typescript
import type * as Cesium from "cesium";
import type { FIRMSHotspot } from "../../types";
import { OverlayPanel } from "../hlidskjalf/OverlayPanel";

export type Selected =
  | { type: "firms"; data: FIRMSHotspot }
  | { type: "aircraft"; data: unknown }
  | { type: "datacenter"; data: unknown }
  | { type: "refinery"; data: unknown }
  | { type: "eonet"; data: unknown }
  | { type: "gdacs"; data: unknown };

export interface InspectorPanelProps {
  selected: Selected | null;
  onClose: () => void;
  viewer: Cesium.Viewer | null;
}

export function InspectorPanel({ selected, onClose }: InspectorPanelProps) {
  return (
    <OverlayPanel
      paragraph="III"
      label="Inspector"
      variant={selected ? "expanded" : "hidden"}
      onClose={onClose}
      width={360}
    >
      <div className="mono" style={{ color: "var(--stone)" }}>
        § placeholder — {selected?.type ?? "nothing selected"}
      </div>
    </OverlayPanel>
  );
}
```

Create `services/frontend/src/components/worldview/TickerPanel.tsx`:

```typescript
import { OverlayPanel } from "../hlidskjalf/OverlayPanel";

export function TickerPanel() {
  return (
    <OverlayPanel paragraph="IV" label="Ticker" variant="expanded" width={320}>
      <div className="mono" style={{ color: "var(--stone)" }}>§ placeholder</div>
    </OverlayPanel>
  );
}
```

- [ ] **Step 5: Delete legacy chrome + App.tsx**

```bash
git rm services/frontend/src/App.tsx \
  services/frontend/src/components/ui/OperationsPanel.tsx \
  services/frontend/src/components/ui/RightPanel.tsx \
  services/frontend/src/components/ui/ThreatRegister.tsx \
  services/frontend/src/components/ui/ClockBar.tsx \
  services/frontend/src/components/ui/StatusBar.tsx \
  services/frontend/src/components/ui/SelectionPanel.tsx
```

Also grep for any imports still referencing these files:

```bash
grep -rn "from \"\.\./App\"" services/frontend/src || true
grep -rn "from \"\.\./components/ui/\(OperationsPanel\|RightPanel\|ThreatRegister\|ClockBar\|StatusBar\|SelectionPanel\)\"" services/frontend/src || true
```

If any appear, delete the stale import — these files are gone.

- [ ] **Step 6: Run tests — verify pass**

Run: `npx vitest run`
Expected: worldviewPage test PASS; full suite green.

- [ ] **Step 7: Lint + type-check**

```bash
npm run lint && npm run type-check
```

Expected: both PASS. If type errors reference removed components, fix the importing site.

- [ ] **Step 8: Commit**

```bash
git add services/frontend/src/pages/WorldviewPage.tsx services/frontend/src/components/worldview/ services/frontend/src/test/pages/worldviewPage.test.tsx
git commit -m "refactor(frontend): port App.tsx to WorldviewPage with § overlay stubs"
```

---

### Task 8: Remove WorldviewErrorBoundary

**Files:**
- Modify: `services/frontend/src/app/router.tsx`
- Delete: `services/frontend/src/pages/WorldviewErrorBoundary.tsx`

- [ ] **Step 1: Write the failing test**

Append to `services/frontend/src/test/app/appShell.test.tsx`:

```typescript
  it("worldview route has no errorElement", async () => {
    const { routes: r } = await import("../../app/router");
    const worldview = r[0].children?.find((c) => c.path === "/worldview");
    expect(worldview?.errorElement).toBeUndefined();
  });
```

- [ ] **Step 2: Run tests — verify failure**

Run: `npx vitest run src/test/app/appShell.test.tsx`
Expected: FAIL — errorElement is still registered.

- [ ] **Step 3: Remove `errorElement` from router**

Open `services/frontend/src/app/router.tsx` and remove the `errorElement: <WorldviewErrorBoundary />` line from the `/worldview` route. Also remove the `import { WorldviewErrorBoundary } from "../pages/WorldviewErrorBoundary";` line at the top.

- [ ] **Step 4: Delete the boundary file**

```bash
git rm services/frontend/src/pages/WorldviewErrorBoundary.tsx
```

- [ ] **Step 5: Run tests — verify pass**

Run: `npx vitest run`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add services/frontend/src/app/router.tsx services/frontend/src/test/app/appShell.test.tsx
git commit -m "refactor(frontend): remove WorldviewErrorBoundary S1 workaround"
```

---

### Task 9: § Layers overlay panel (real content)

**Files:**
- Modify: `services/frontend/src/components/worldview/LayersPanel.tsx`
- Test: `services/frontend/src/components/worldview/LayersPanel.test.tsx` (new)

- [ ] **Step 1: Write the failing test**

Create `services/frontend/src/components/worldview/LayersPanel.test.tsx`:

```typescript
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { LayersPanel } from "./LayersPanel";
import type { LayerVisibility } from "../../types";

const allOff: LayerVisibility = {
  flights: false, satellites: false, earthquakes: false, vessels: false,
  cctv: false, events: false, cables: false, pipelines: false,
  countryBorders: false, cityBuildings: false, firmsHotspots: false,
  milAircraft: false, datacenters: false, refineries: false, eonet: false, gdacs: false,
};

describe("LayersPanel", () => {
  it("groups toggles by dimension and shows amber dot when active", () => {
    render(
      <LayersPanel
        layers={{ ...allOff, flights: true }}
        onToggle={vi.fn()}
        activeShader="none"
        onShaderChange={vi.fn()}
      />,
    );
    expect(screen.getByText(/Transport/i)).toBeInTheDocument();
    expect(screen.getByText(/Incidents/i)).toBeInTheDocument();
    expect(screen.getByText(/Infrastructure/i)).toBeInTheDocument();
    expect(screen.getByText(/Atmosphere/i)).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: /flights/i })).toBeChecked();
  });

  it("calls onToggle with the layer key when clicked", () => {
    const onToggle = vi.fn();
    render(
      <LayersPanel
        layers={allOff}
        onToggle={onToggle}
        activeShader="none"
        onShaderChange={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByRole("checkbox", { name: /satellites/i }));
    expect(onToggle).toHaveBeenCalledWith("satellites");
  });
});
```

- [ ] **Step 2: Run tests — verify failure**

Run: `npx vitest run src/components/worldview/LayersPanel.test.tsx`
Expected: FAIL — placeholder shows no groups.

- [ ] **Step 3: Implement `LayersPanel`**

Replace `services/frontend/src/components/worldview/LayersPanel.tsx`:

```typescript
import type { CSSProperties } from "react";
import type { LayerVisibility, ShaderType } from "../../types";

export interface LayersPanelProps {
  layers: LayerVisibility;
  onToggle: (layer: keyof LayerVisibility) => void;
  activeShader: ShaderType;
  onShaderChange: (shader: ShaderType) => void;
}

interface Group {
  title: string;
  keys: (keyof LayerVisibility)[];
}

const GROUPS: Group[] = [
  { title: "Incidents", keys: ["earthquakes", "firmsHotspots", "events", "eonet", "gdacs"] },
  { title: "Transport", keys: ["flights", "milAircraft", "vessels"] },
  { title: "Infrastructure", keys: ["cables", "pipelines", "datacenters", "refineries", "countryBorders", "cityBuildings"] },
  { title: "Atmosphere", keys: ["satellites", "cctv"] },
];

const groupStyle: CSSProperties = {
  marginBottom: "14px",
};

const groupTitle: CSSProperties = {
  fontFamily: "'Hanken Grotesk', sans-serif",
  fontSize: "10px",
  letterSpacing: "0.3em",
  textTransform: "uppercase",
  color: "var(--ash)",
  marginBottom: "6px",
};

const rowStyle: CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: "8px",
  padding: "4px 0",
  fontFamily: "'Hanken Grotesk', sans-serif",
  fontSize: "12px",
  color: "var(--bone)",
  cursor: "pointer",
};

const dotOn: CSSProperties = {
  width: "6px", height: "6px", borderRadius: "50%", background: "var(--amber)",
};
const dotOff: CSSProperties = {
  width: "6px", height: "6px", borderRadius: "50%", background: "transparent", border: "1px solid var(--granite)",
};

// Visually hidden but keeps the input in the accessibility tree so
// getByRole("checkbox") still finds it. `display: none` would remove it.
const visuallyHidden: CSSProperties = {
  position: "absolute",
  width: 1,
  height: 1,
  padding: 0,
  margin: -1,
  overflow: "hidden",
  clip: "rect(0 0 0 0)",
  whiteSpace: "nowrap",
  border: 0,
};

export function LayersPanel({ layers, onToggle }: LayersPanelProps) {
  return (
    <div>
      {GROUPS.map((group) => (
        <div key={group.title} style={groupStyle}>
          <div style={groupTitle}>§ {group.title}</div>
          {group.keys.map((key) => (
            <label key={key} style={rowStyle}>
              <input
                type="checkbox"
                checked={layers[key]}
                onChange={() => onToggle(key)}
                aria-label={key}
                style={visuallyHidden}
              />
              <span style={layers[key] ? dotOn : dotOff} aria-hidden="true" />
              <span>{key}</span>
            </label>
          ))}
        </div>
      ))}
    </div>
  );
}
```

- [ ] **Step 4: Run tests — verify pass**

Run: `npx vitest run src/components/worldview/LayersPanel.test.tsx`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add services/frontend/src/components/worldview/LayersPanel.tsx services/frontend/src/components/worldview/LayersPanel.test.tsx
git commit -m "feat(frontend): § Layers overlay panel with dimension groups"
```

---

### Task 10: § Search overlay panel

**Files:**
- Modify: `services/frontend/src/components/worldview/SearchPanel.tsx`
- Test: `services/frontend/src/components/worldview/SearchPanel.test.tsx` (new)

- [ ] **Step 1: Write the failing test**

Create `services/frontend/src/components/worldview/SearchPanel.test.tsx`:

```typescript
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { SearchPanel } from "./SearchPanel";

describe("SearchPanel", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("renders the input with search placeholder", () => {
    render(<SearchPanel viewer={null} />);
    const input = screen.getByPlaceholderText(/search entities/i);
    expect(input).toBeInTheDocument();
  });

  it("calls /api/v1/graph/search with typed query after debounce", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        nodes: [{ id: "ucdp:44821", name: "Sinjar ridge", type: "Location" }],
        total_count: 1,
      }),
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<SearchPanel viewer={null} />);
    fireEvent.change(screen.getByPlaceholderText(/search entities/i), {
      target: { value: "sinj" },
    });
    await waitFor(() => expect(screen.getByText(/Sinjar ridge/i)).toBeInTheDocument());
    const calledUrl = fetchMock.mock.calls[0][0] as string;
    expect(calledUrl).toMatch(/\/api\/v1\/graph\/search\?q=sinj/);
  });

  it("renders node.type as an Eyebrow next to the name", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        nodes: [{ id: "loc:1", name: "Barents Sea", type: "Location" }],
        total_count: 1,
      }),
    }));
    render(<SearchPanel viewer={null} />);
    fireEvent.change(screen.getByPlaceholderText(/search entities/i), {
      target: { value: "bare" },
    });
    await waitFor(() => {
      expect(screen.getByText(/Barents Sea/i)).toBeInTheDocument();
      expect(screen.getByText(/Location/i)).toBeInTheDocument();
    });
  });

  it("shows no-matches placeholder when nodes is empty", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ nodes: [], total_count: 0 }),
    }));
    render(<SearchPanel viewer={null} />);
    fireEvent.change(screen.getByPlaceholderText(/search entities/i), {
      target: { value: "zzz" },
    });
    await waitFor(() => expect(screen.getByText(/— no matches —/i)).toBeInTheDocument());
  });
});
```

- [ ] **Step 2: Run tests — verify failure**

Run: `npx vitest run src/components/worldview/SearchPanel.test.tsx`
Expected: FAIL.

- [ ] **Step 3: Implement `SearchPanel`**

Replace `services/frontend/src/components/worldview/SearchPanel.tsx`. Uses the real `/api/v1/graph/search` endpoint — returns `{ nodes: [{id, name, type}], total_count }`. The backend does not return lat/lon, so **v1 has no flyTo**; clicking a result is a no-op placeholder (properly wired once Inspector can look up coords by id in S3).

```typescript
import { useEffect, useRef, useState } from "react";
import type * as Cesium from "cesium";

export interface GraphNode {
  id: string;
  name: string;
  type: string;
}

interface GraphSearchResponse {
  nodes: GraphNode[];
  total_count: number;
}

export interface SearchPanelProps {
  viewer: Cesium.Viewer | null;
}

export function SearchPanel(_props: SearchPanelProps) {
  const [q, setQ] = useState("");
  const [results, setResults] = useState<GraphNode[] | null>(null);
  const [loading, setLoading] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  useEffect(() => {
    if (q.trim().length < 2) {
      setResults(null);
      return;
    }
    let cancelled = false;
    const t = setTimeout(async () => {
      setLoading(true);
      try {
        const res = await fetch(
          `/api/v1/graph/search?q=${encodeURIComponent(q.trim())}&limit=20`,
        );
        if (!res.ok) throw new Error("search failed");
        const data = (await res.json()) as GraphSearchResponse;
        if (cancelled) return;
        setResults(data.nodes);
      } catch {
        if (!cancelled) setResults([]);
      } finally {
        if (!cancelled) setLoading(false);
      }
    }, 180);
    return () => {
      cancelled = true;
      clearTimeout(t);
    };
  }, [q]);

  return (
    <div>
      <input
        ref={inputRef}
        value={q}
        onChange={(e) => setQ(e.target.value)}
        placeholder="search entities…"
        style={{
          width: "100%",
          background: "transparent",
          border: "none",
          borderBottom: "1px solid var(--granite)",
          color: "var(--bone)",
          fontFamily: "'Instrument Serif', serif",
          fontStyle: "italic",
          fontSize: "14px",
          padding: "6px 0",
          outline: "none",
        }}
      />
      <div style={{ marginTop: 10, minHeight: 24 }}>
        {loading && (
          <span className="mono" style={{ color: "var(--ash)", fontSize: 10 }}>
            § searching…
          </span>
        )}
        {!loading && results?.length === 0 && (
          <span className="mono" style={{ color: "var(--ash)", fontSize: 10 }}>
            — no matches —
          </span>
        )}
        {!loading && results && results.length > 0 && (
          <ul style={{ listStyle: "none", padding: 0, margin: 0 }}>
            {results.map((node) => (
              <li key={node.id} style={{ padding: "6px 0", display: "flex", flexDirection: "column", gap: 2 }}>
                <span
                  className="mono"
                  style={{
                    color: "var(--ash)",
                    fontSize: 10,
                    letterSpacing: "0.22em",
                    textTransform: "uppercase",
                  }}
                >
                  § {node.type}
                </span>
                <span
                  style={{
                    color: "var(--bone)",
                    fontFamily: "'Instrument Serif', serif",
                    fontStyle: "italic",
                    fontSize: 13,
                  }}
                >
                  {node.name}
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
```

> **Known limitation (S2):** The graph-search endpoint returns entity names/types but no coordinates. flyTo + Inspector integration on click is deferred to S3, when the Inspector gains a "look up entity by id" query that hits both Qdrant and the relevant layer cache for coordinates. This is a conscious scope boundary — S2 ships a usable entity-name lookup; S3 wires it to the globe.

- [ ] **Step 4: Run tests — verify pass**

Run: `npx vitest run src/components/worldview/SearchPanel.test.tsx`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add services/frontend/src/components/worldview/SearchPanel.tsx services/frontend/src/components/worldview/SearchPanel.test.tsx
git commit -m "feat(frontend): § Search overlay panel with entity autocomplete"
```

> **Note:** `/api/v1/graph/search` is the live endpoint (see `services/backend/app/routers/graph.py:203`). Step 5b of Task 15 flips this to `/api/graph/search` once the consolidation lands.

---

### Task 11: § Inspector overlay panel (real content)

**Files:**
- Modify: `services/frontend/src/components/worldview/InspectorPanel.tsx`
- Test: `services/frontend/src/components/worldview/InspectorPanel.test.tsx` (new)

- [ ] **Step 1: Write the failing test**

Create `services/frontend/src/components/worldview/InspectorPanel.test.tsx`:

```typescript
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { InspectorPanel } from "./InspectorPanel";

describe("InspectorPanel", () => {
  it("is hidden when nothing is selected", () => {
    const { container } = render(
      <InspectorPanel selected={null} onClose={vi.fn()} viewer={null} />,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("shows a firms hotspot with coordinates in Martian Mono", () => {
    render(
      <InspectorPanel
        selected={{
          type: "firms",
          data: {
            id: "firms-1",
            latitude: 12.34,
            longitude: 56.78,
            frp: 4.2,
            brightness: 320.5,
            confidence: "nominal",
            acq_date: "2026-04-21",
            acq_time: "1000",
            satellite: "VIIRS",
            bbox_name: "sinjar-ridge",
            possible_explosion: false,
            firms_map_url: "https://firms.modaps.eosdis.nasa.gov/...",
          },
        }}
        onClose={vi.fn()}
        viewer={null}
      />,
    );
    expect(screen.getByRole("region", { name: /Inspector/i })).toBeInTheDocument();
    expect(screen.getByText(/12.340° N · 56.780° E/)).toBeInTheDocument();
    expect(screen.getByText(/VIIRS/)).toBeInTheDocument();
  });

  it("calls onClose when × is clicked", () => {
    const onClose = vi.fn();
    render(
      <InspectorPanel
        selected={{ type: "aircraft", data: { icao24: "abc123" } }}
        onClose={onClose}
        viewer={null}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: /close Inspector/i }));
    expect(onClose).toHaveBeenCalledOnce();
  });
});
```

- [ ] **Step 2: Run tests — verify failure**

Run: `npx vitest run src/components/worldview/InspectorPanel.test.tsx`
Expected: FAIL — placeholder doesn't render entity-specific data.

- [ ] **Step 3: Replace `InspectorPanel` with real content**

Replace `services/frontend/src/components/worldview/InspectorPanel.tsx`:

```typescript
import type { CSSProperties } from "react";
import type * as Cesium from "cesium";
import type { FIRMSHotspot } from "../../types";
import { OverlayPanel } from "../hlidskjalf/OverlayPanel";

export type Selected =
  | { type: "firms"; data: FIRMSHotspot }
  | { type: "aircraft"; data: { icao24?: string; callsign?: string; latitude?: number; longitude?: number; altitude_m?: number } }
  | { type: "datacenter"; data: { name?: string; operator?: string; latitude?: number; longitude?: number } }
  | { type: "refinery"; data: { name?: string; capacity_bpd?: number; latitude?: number; longitude?: number } }
  | { type: "eonet"; data: { title?: string; category?: string; latitude?: number; longitude?: number } }
  | { type: "gdacs"; data: { title?: string; severity?: string; latitude?: number; longitude?: number } };

export interface InspectorPanelProps {
  selected: Selected | null;
  onClose: () => void;
  viewer: Cesium.Viewer | null;
}

const labelStyle: CSSProperties = {
  fontFamily: "'Hanken Grotesk', sans-serif",
  fontSize: 10,
  letterSpacing: "0.22em",
  textTransform: "uppercase",
  color: "var(--ash)",
};

const valueStyle: CSSProperties = {
  fontFamily: "'Martian Mono', monospace",
  fontSize: 11,
  color: "var(--bone)",
  marginTop: 2,
  marginBottom: 10,
};

const titleStyle: CSSProperties = {
  fontFamily: "'Instrument Serif', serif",
  fontStyle: "italic",
  fontSize: 18,
  color: "var(--parchment)",
  marginBottom: 12,
};

function coords(lat?: number, lon?: number): string {
  if (!Number.isFinite(lat) || !Number.isFinite(lon)) return "—";
  const ns = (lat as number) >= 0 ? "N" : "S";
  const ew = (lon as number) >= 0 ? "E" : "W";
  return `${Math.abs(lat as number).toFixed(3)}° ${ns} · ${Math.abs(lon as number).toFixed(3)}° ${ew}`;
}

function Body({ selected }: { selected: Selected }) {
  switch (selected.type) {
    case "firms": {
      const h = selected.data;
      return (
        <>
          <div style={titleStyle}>FIRMS hotspot · {h.satellite}</div>
          <div style={labelStyle}>§ coords</div>
          <div style={valueStyle}>{coords(h.latitude, h.longitude)}</div>
          <div style={labelStyle}>§ FRP / brightness</div>
          <div style={valueStyle}>{h.frp.toFixed(1)} MW · {h.brightness.toFixed(1)} K · {h.confidence}</div>
          <div style={labelStyle}>§ acquired</div>
          <div style={valueStyle}>{h.acq_date} {h.acq_time}Z</div>
          {h.possible_explosion ? (
            <>
              <div style={labelStyle}>§ flag</div>
              <div style={{ ...valueStyle, color: "var(--sentinel)" }}>possible explosion</div>
            </>
          ) : null}
        </>
      );
    }
    case "aircraft": {
      const a = selected.data;
      return (
        <>
          <div style={titleStyle}>{a.callsign ?? a.icao24 ?? "aircraft"}</div>
          <div style={labelStyle}>§ icao24</div>
          <div style={valueStyle}>{a.icao24 ?? "—"}</div>
          <div style={labelStyle}>§ coords</div>
          <div style={valueStyle}>{coords(a.latitude, a.longitude)}</div>
          <div style={labelStyle}>§ altitude</div>
          <div style={valueStyle}>{Number.isFinite(a.altitude_m) ? `${a.altitude_m} m` : "—"}</div>
        </>
      );
    }
    case "datacenter": {
      const d = selected.data;
      return (
        <>
          <div style={titleStyle}>{d.name ?? "datacenter"}</div>
          <div style={labelStyle}>§ operator</div>
          <div style={valueStyle}>{d.operator ?? "—"}</div>
          <div style={labelStyle}>§ coords</div>
          <div style={valueStyle}>{coords(d.latitude, d.longitude)}</div>
        </>
      );
    }
    case "refinery": {
      const r = selected.data;
      return (
        <>
          <div style={titleStyle}>{r.name ?? "refinery"}</div>
          <div style={labelStyle}>§ capacity</div>
          <div style={valueStyle}>{r.capacity_bpd ? `${r.capacity_bpd.toLocaleString()} bpd` : "—"}</div>
          <div style={labelStyle}>§ coords</div>
          <div style={valueStyle}>{coords(r.latitude, r.longitude)}</div>
        </>
      );
    }
    case "eonet": {
      const e = selected.data;
      return (
        <>
          <div style={titleStyle}>{e.title ?? "EONET event"}</div>
          <div style={labelStyle}>§ category</div>
          <div style={valueStyle}>{e.category ?? "—"}</div>
          <div style={labelStyle}>§ coords</div>
          <div style={valueStyle}>{coords(e.latitude, e.longitude)}</div>
        </>
      );
    }
    case "gdacs": {
      const g = selected.data;
      return (
        <>
          <div style={titleStyle}>{g.title ?? "GDACS event"}</div>
          <div style={labelStyle}>§ severity</div>
          <div style={valueStyle}>{g.severity ?? "—"}</div>
          <div style={labelStyle}>§ coords</div>
          <div style={valueStyle}>{coords(g.latitude, g.longitude)}</div>
        </>
      );
    }
  }
}

export function InspectorPanel({ selected, onClose }: InspectorPanelProps) {
  return (
    <OverlayPanel
      paragraph="III"
      label="Inspector"
      variant={selected ? "expanded" : "hidden"}
      onClose={onClose}
      width={360}
    >
      {selected ? <Body selected={selected} /> : null}
    </OverlayPanel>
  );
}
```

- [ ] **Step 4: Run tests — verify pass**

Run: `npx vitest run src/components/worldview/InspectorPanel.test.tsx`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add services/frontend/src/components/worldview/InspectorPanel.tsx services/frontend/src/components/worldview/InspectorPanel.test.tsx
git commit -m "feat(frontend): § Inspector overlay panel for entity details"
```

---

### Task 12: § Ticker overlay panel (real content)

**Files:**
- Modify: `services/frontend/src/components/worldview/TickerPanel.tsx`
- Test: `services/frontend/src/components/worldview/TickerPanel.test.tsx` (new)

- [ ] **Step 1: Write the failing test**

Create `services/frontend/src/components/worldview/TickerPanel.test.tsx`:

```typescript
import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { TickerPanel } from "./TickerPanel";

vi.mock("../../hooks/useSignalFeed", () => ({
  useSignalFeed: () => ({
    status: "live",
    items: [
      {
        event_id: "01ABC",
        ts: "2026-04-21T14:32:00Z",
        type: "signal.firms",
        payload: { title: "sinjar cluster", severity: "high", source: "firms", url: "" },
      },
      {
        event_id: "01ABD",
        ts: "2026-04-21T13:58:00Z",
        type: "signal.gdelt",
        payload: { title: "tu-95 barents", severity: "medium", source: "gdelt", url: "" },
      },
    ],
    lastEventId: "01ABD",
  }),
}));

describe("TickerPanel", () => {
  it("renders live signal items using Landing's feed hook", () => {
    render(<TickerPanel />);
    expect(screen.getByRole("region", { name: /Ticker/i })).toBeInTheDocument();
    expect(screen.getByText(/sinjar cluster/i)).toBeInTheDocument();
    expect(screen.getByText(/tu-95 barents/i)).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run tests — verify failure**

Run: `npx vitest run src/components/worldview/TickerPanel.test.tsx`
Expected: FAIL — placeholder has no feed rendering.

- [ ] **Step 3: Implement `TickerPanel`**

Replace `services/frontend/src/components/worldview/TickerPanel.tsx`:

```typescript
import { useSignalFeed } from "../../hooks/useSignalFeed";
import { SignalFeedItem } from "../hlidskjalf/SignalFeedItem";
import { OverlayPanel } from "../hlidskjalf/OverlayPanel";

type Severity = "sent" | "amb" | "sage" | "dim";

function mapSeverity(s: string | undefined): Severity {
  switch (s) {
    case "critical": return "sent";
    case "high": return "amb";
    case "medium": return "sage";
    default: return "dim";
  }
}

function formatTime(ts: string): string {
  const d = new Date(ts);
  if (Number.isNaN(d.getTime())) return "—";
  const hh = d.getUTCHours().toString().padStart(2, "0");
  const mm = d.getUTCMinutes().toString().padStart(2, "0");
  return `${hh}:${mm}Z`;
}

export function TickerPanel() {
  const { items, status } = useSignalFeed();
  return (
    <OverlayPanel paragraph="IV" label="Ticker" variant="expanded" width={320}>
      <div style={{ display: "flex", flexDirection: "column", gap: 4, maxHeight: 220, overflowY: "auto" }}>
        {status === "reconnecting" && (
          <span className="mono" style={{ color: "var(--ash)", fontSize: 10 }}>§ reconnecting…</span>
        )}
        {items.length === 0 && status !== "reconnecting" && (
          <span className="mono" style={{ color: "var(--ash)", fontSize: 10 }}>— no signals yet —</span>
        )}
        {items.map((env) => (
          <SignalFeedItem
            key={env.event_id}
            severity={mapSeverity(env.payload.severity)}
            ts={formatTime(env.ts)}
            text={env.payload.title || env.type}
          />
        ))}
      </div>
    </OverlayPanel>
  );
}
```

- [ ] **Step 4: Run tests — verify pass**

Run: `npx vitest run src/components/worldview/TickerPanel.test.tsx`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add services/frontend/src/components/worldview/TickerPanel.tsx services/frontend/src/components/worldview/TickerPanel.test.tsx
git commit -m "feat(frontend): § Ticker overlay panel reusing useSignalFeed"
```

---

### Task 13: F3 — `SIGNAL_EVENT_TYPES` wildcard listener

**Files:**
- Modify: `services/frontend/src/hooks/useSignalFeed.ts` (remove `signal.*` gate; unfiltered wildcard ingest)
- Modify: `services/backend/app/routers/signals.py` (emit a generic message frame in addition to typed frames)
- Test: `services/frontend/src/test/hooks/signalFeedWildcard.test.tsx` (new)
- Test: `services/backend/tests/unit/test_signals_stream.py` (extend with mixed taxonomy-type assertion)

- [ ] **Step 1: Write the failing frontend test**

Create `services/frontend/src/test/hooks/signalFeedWildcard.test.tsx`:

```typescript
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, act, waitFor } from "@testing-library/react";

const listeners = new Map<string, (ev: MessageEvent) => void>();
class FakeEventSource {
  url: string;
  addEventListener = vi.fn((type: string, cb: (ev: MessageEvent) => void) => {
    listeners.set(type, cb);
  });
  removeEventListener = vi.fn();
  close = vi.fn();
  onopen?: () => void;
  onerror?: () => void;
  set onmessage(cb: ((ev: MessageEvent) => void) | undefined) {
    if (cb) listeners.set("message", cb);
  }
  constructor(url: string) {
    this.url = url;
    setTimeout(() => this.onopen?.(), 0);
  }
}

describe("useSignalFeed wildcard", () => {
  beforeEach(() => {
    listeners.clear();
    vi.stubGlobal("EventSource", FakeEventSource as unknown as typeof EventSource);
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => [] }));
  });
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("accepts a non-signal taxonomy type from generic message frames", async () => {
    const { useSignalFeed } = await import("../../hooks/useSignalFeed");
    const { result } = renderHook(() => useSignalFeed());
    await waitFor(() => expect(result.current.status).toBe("live"));

    const onmessage = listeners.get("message");
    expect(onmessage).toBeDefined();

    act(() => {
      onmessage!({
        data: JSON.stringify({
          event_id: "01A",
          ts: "2026-04-21T00:00:00Z",
          type: "military.air_activity",
          payload: { title: "tu-95 barents", severity: "medium", source: "gdelt", url: "" },
        }),
        lastEventId: "01A",
      } as MessageEvent);
    });

    await waitFor(() => {
      expect(result.current.items.some((i) => i.type === "military.air_activity")).toBe(true);
    });
  });
});
```

- [ ] **Step 2: Run tests — verify failure**

Run: `npx vitest run src/test/hooks/signalFeedWildcard.test.tsx`
Expected: FAIL — existing whitelist / type gate drops non-`signal.*` envelopes.

- [ ] **Step 3: Make wildcard truly taxonomy-wide (frontend + backend)**

**Why both sides:** backend currently emits typed SSE frames (`event: <codebook_type>`). Browser `EventSource` delivers these to per-type listeners, not reliably to `onmessage`. To guarantee future types without frontend edits, the stream must also emit a generic frame.

1) In `services/frontend/src/hooks/useSignalFeed.ts`:
- Remove the `env.type?.startsWith("signal.")` gate.
- Keep acceptance criterion: any envelope with valid `event_id` + `type` is ingested.
- Keep `es.onmessage = ...` as the primary wildcard path.
- Keep existing dedupe logic unchanged.

2) In `services/backend/app/routers/signals.py`:
- Keep existing typed frame emission for compatibility.
- Add a generic (unnamed) frame for each envelope so clients using `onmessage` always receive every taxonomy type (`military.*`, `other.*`, `armed_conflict.*`, etc.).
- Apply this to replay and live frames.

Reference shape:

```python
def _frame_named(envelope: SignalEnvelope) -> dict[str, str]:
    return {
        "id": envelope.event_id,
        "event": envelope.type,
        "data": envelope.model_dump_json(),
    }

def _frame_wildcard(envelope: SignalEnvelope) -> dict[str, str]:
    return {
        "id": envelope.event_id,
        "data": envelope.model_dump_json(),
    }
```

Then emit both in `sse_generator`:

```python
yield _frame_named(envelope)
yield _frame_wildcard(envelope)
```

Deduping in `useSignalFeed` already prevents duplicate UI inserts when both paths are observed.

- [ ] **Step 4: Add/extend backend assertion**

In `services/backend/tests/unit/test_signals_stream.py`, add one assertion that a non-`signal.*` type (e.g. `military.air_activity`) is present in the generic message path (unnamed frame) while typed frame compatibility remains intact.

- [ ] **Step 5: Run tests — verify pass**

```bash
cd services/frontend && npx vitest run src/test/hooks/signalFeedWildcard.test.tsx
cd ../backend && uv run pytest tests/unit/test_signals_stream.py
```

Expected: PASS.

- [ ] **Step 6: Run full suite — verify Landing still works**

Run: `cd services/frontend && npx vitest run`
Expected: all PASS.

- [ ] **Step 7: Commit**

```bash
git add services/frontend/src/hooks/useSignalFeed.ts services/frontend/src/test/hooks/signalFeedWildcard.test.tsx services/backend/app/routers/signals.py services/backend/tests/unit/test_signals_stream.py
git commit -m "feat(signals): accept any codebook_type via wildcard SSE path"
```

---

### Task 14: F2 — Signals stream contract doc

**Files:**
- Create: `docs/contracts/signals-stream.md`

- [ ] **Step 1: Write the contract doc**

Create `docs/contracts/signals-stream.md`:

````markdown
# Signals Stream Contract

**Source of truth:** Redis Stream `events:new` (key defined by `settings.redis_stream_events` in `services/data-ingestion/config.py`).

**Producers (XADD):**
- `services/data-ingestion/pipeline.py` (all RSS/GDELT/UCDP/FIRMS/EONET/GDACS collectors funnel here)

**Consumers:**
- `services/backend/app/services/signal_stream.py` → SSE via `/api/signals/stream`
- `services/backend/app/routers/landing.py` reads the same source for last-24h counts

## XADD payload fields

| Field | Type | Example | Notes |
|---|---|---|---|
| `title` | str | `"Sinjar cluster expansion"` | Human-readable event title |
| `codebook_type` | str | `"signal.firms"` \| `"military.air_activity"` \| `"other.unclassified"` | Codebook type — **any taxonomy value**, see `services/intelligence/codebook/` |
| `severity` | str | `"low"` \| `"medium"` \| `"high"` \| `"critical"` | Used by frontend to map to dot color |
| `source` | str | `"firms"` \| `"ucdp"` \| `"gdelt"` \| `"eonet"` \| `"gdacs"` \| `"rss"` \| `"telegram"` | Origin collector |
| `url` | str | `"https://…"` | Source URL, empty string if not applicable |

Any additional producer-specific fields are passed through into `SignalEnvelope.payload` unchanged.

## SSE envelope (client-facing)

The backend wraps the Redis record into this envelope before streaming. The SSE `type` is the raw `codebook_type` — there is **no `signal.*` normalisation**; `military.air_activity`, `armed_conflict.skirmish`, etc. all come through unchanged.

```json
{
  "event_id": "<ms>-<seq>",
  "ts": "ISO-8601 UTC",
  "type": "<codebook_type>",
  "payload": { "title": "...", "severity": "...", "source": "...", "url": "...", ... }
}
```

- `event_id` encodes the Redis record ID for Last-Event-ID reconnect replay.
- `type` is routed as a named SSE event (e.g. `event: military.air_activity`); clients register per-type via `addEventListener(type, …)` or fall back to `onmessage` as an unfiltered wildcard.

## Replay contract

- Ring buffer: last 15 minutes
- Reconnect header: `Last-Event-ID`
- Query fallback: `?last_event_id=…`
- Beyond 15 min → server emits `event: reset`, clients re-hydrate from `/api/signals/latest`

## Adding a new signal type

1. Add a new codebook entry under `services/intelligence/codebook/`.
2. Ensure `pipeline.py` XADDs with that `codebook_type`.
3. No frontend change required — backend emits both typed and generic SSE frames, and the wildcard listener in `useSignalFeed` ingests any codebook type.
4. Add a row to the table above.

## Testing

- Integration test (backend): `services/backend/tests/streams/test_signals_stream.py` — see §6.1 acceptance criteria in `docs/superpowers/specs/2026-04-14-odin-4layer-hlidskjalf-design.md`.
- Frontend test: `services/frontend/src/test/hooks/signalFeedWildcard.test.tsx`.
````

- [ ] **Step 2: Commit**

```bash
mkdir -p docs/contracts
git add docs/contracts/signals-stream.md
git commit -m "docs: signals-stream contract (F2 follow-up from S1 review)"
```

---

### Task 15: F1 — API prefix consolidation to `/api`

**Files:**
- Create: `docs/adr/0001-api-prefix-consolidation.md`
- Modify: `services/backend/app/main.py` (router prefixes)
- Modify: `services/frontend/src/services/api.ts` (`BASE` constant)

**Decision (recorded in the ADR before any code change):** consolidate to `/api/*`. Keep `/api/v1/*` as transparent alias (same routers mounted twice) for 30 days to cover any external callers, then delete. This honours spec §5.1 ("alle Backend-Calls vom Frontend nutzen /api/*") without breaking anything during S2 merge.

- [ ] **Step 1: Write the ADR**

Create `docs/adr/0001-api-prefix-consolidation.md`:

```markdown
# ADR-0001: API prefix consolidation to `/api`

**Date:** 2026-04-21
**Status:** Accepted
**Supersedes:** N/A

## Context

S1 shipped new endpoints (`/api/signals`, `/api/landing`) without the `/v1` suffix used by legacy routers (`/api/v1/flights`, `/api/v1/satellites`, …). Spec §5.1 explicitly mandates `/api/*` for all frontend calls. The current split is inconsistent and documented as F1 in the S1 review.

## Decision

1. Remount every router in `services/backend/app/main.py` at `prefix="/api"`.
2. Migrate the in-line `@app.get("/api/v1/health")` and `@app.get("/api/v1/config")` endpoints (defined directly on `app`, not on a router) to the canonical `/api/health` and `/api/config` paths via `add_api_route`.
3. Keep `/api/v1/*` aliases (for both routers and in-line endpoints) live for 30 days — transparent to external callers (Telegram links, test dashboards).
4. Frontend `services/api.ts`: change `BASE` from `/api/v1` to `/api`.
5. Frontend hardcoded callsites (grep: `SearchPanel.tsx`) flip to `/api/*` directly.
6. Schedule removal of `/api/v1` aliases for 2026-05-21.

## Consequences

- Frontend callsites using the `fetchJSON` helper (most `services/api.ts` exports) need zero change — the helper prepends `BASE`.
- Any frontend call that hardcodes `/api/v1/…` must be rewritten. Current hardcoded paths: `SignalFeedItem`-adjacent callers use `/api/signals/*` already at bare `/api`; SearchPanel needs the update.
- External API consumers have 30 days to migrate.
- WebSocket routers remain unchanged (no prefix on either side).
- Alias `add_api_route` uses `include_in_schema=False` to keep the OpenAPI surface clean.

## Rollback

Revert the `BASE` constant and the `/api/v1` aliases become authoritative again.
```

- [ ] **Step 2: Write the failing test**

Create `services/frontend/src/test/services/apiBase.test.ts`:

```typescript
import { describe, it, expect, vi, beforeEach } from "vitest";

describe("api BASE", () => {
  beforeEach(() => vi.restoreAllMocks());

  it("uses /api (not /api/v1) for getFlights", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => [] });
    vi.stubGlobal("fetch", fetchMock);
    const { getFlights } = await import("../../services/api");
    await getFlights();
    const url = fetchMock.mock.calls[0][0] as string;
    expect(url).toBe("/api/flights");
  });
});
```

- [ ] **Step 3: Run tests — verify failure**

Run: `npx vitest run src/test/services/apiBase.test.ts`
Expected: FAIL — URL is `/api/v1/flights`.

- [ ] **Step 4: Flip `BASE` in `services/api.ts`**

In `services/frontend/src/services/api.ts`:

```typescript
const BASE = "/api";
```

- [ ] **Step 5: Update backend router mounts AND the in-line `@app.get` routes**

Two call-sites need updating in `services/backend/app/main.py`:

**(a) Router block (~lines 103-118):**

```python
# REST Routers — unified prefix
for r in (
    flights.router, satellites.router, earthquakes.router, vessels.router,
    hotspots.router, intel.router, rag.router, graph.router, cables.router,
    firms.router, aircraft.router, eonet.router, gdacs.router,
):
    app.include_router(r, prefix="/api")
    # Back-compat alias — remove 2026-05-21
    app.include_router(r, prefix="/api/v1")

# S1 Hlidskjalf routers (already at /api, no alias needed)
app.include_router(signals.router, prefix="/api")
app.include_router(landing.router, prefix="/api")

# WebSocket Routers
app.include_router(flight_ws.router)
app.include_router(vessel_ws.router)
```

**(b) In-line `@app.get` endpoints (~lines 137, 146)** — `health` and `client_config` are registered directly on the app, not on a router. They must be dual-mounted too. Replace the current decorators with:

```python
class HealthResponse(BaseModel):
    status: str
    timestamp: datetime
    version: str


class ClientConfig(BaseModel):
    cesium_ion_token: str
    default_layers: dict[str, bool]
    api_version: str


async def health() -> HealthResponse:
    return HealthResponse(
        status="ok",
        timestamp=datetime.now(UTC),
        version="0.1.0",
    )


async def client_config() -> ClientConfig:
    """Return client configuration. Never exposes secret keys."""
    return ClientConfig(
        cesium_ion_token=settings.cesium_ion_token,
        default_layers={
            "flights": True,
            "satellites": True,
            "earthquakes": True,
            "vessels": False,
            "cctv": False,
            "events": False,
            "cables": False,
            "pipelines": False,
            "firmsHotspots": True,
            "milAircraft": True,
            "eonet": False,
            "gdacs": False,
        },
        api_version="v1",
    )


# New primary mount at /api
app.add_api_route("/api/health", health, response_model=HealthResponse, methods=["GET"])
app.add_api_route("/api/config", client_config, response_model=ClientConfig, methods=["GET"])

# Back-compat aliases — remove 2026-05-21
app.add_api_route("/api/v1/health", health, response_model=HealthResponse, methods=["GET"], include_in_schema=False)
app.add_api_route("/api/v1/config", client_config, response_model=ClientConfig, methods=["GET"], include_in_schema=False)
```

> **Note:** `include_router` twice is safe — FastAPI registers the routes at both prefixes. If a duplicate-operation-id warning appears, disambiguate via `operation_id=None` override; otherwise ignore. `add_api_route` with `include_in_schema=False` on the alias keeps OpenAPI docs clean.

- [ ] **Step 5b: Update the SearchPanel URL to the new prefix**

Task 10 ships `/api/v1/graph/search` (only working path at that time). After Step 5 the `/api` prefix is live — switch the SearchPanel call to the canonical form.

In `services/frontend/src/components/worldview/SearchPanel.tsx`, replace:

```typescript
`/api/v1/graph/search?q=${encodeURIComponent(q.trim())}&limit=20`
```

with:

```typescript
`/api/graph/search?q=${encodeURIComponent(q.trim())}&limit=20`
```

Update the matching assertion in `SearchPanel.test.tsx`:

```typescript
expect(calledUrl).toMatch(/\/api\/graph\/search\?q=sinj/);
```

- [ ] **Step 6: Update backend tests that assert URLs**

Run a grep:

```bash
grep -rn "/api/v1" services/backend/tests services/frontend/src/test || true
```

For each test URL hardcoded to `/api/v1/…`, change to `/api/…`. Preserve one `/api/v1` test per router as the alias regression check.

- [ ] **Step 7: Run tests — verify pass**

```bash
cd services/frontend && npx vitest run
cd ../backend && uv run pytest
```

Expected: both PASS.

- [ ] **Step 8: Commit**

```bash
git add docs/adr/0001-api-prefix-consolidation.md services/frontend/src/services/api.ts services/backend/app/main.py services/frontend/src/test/services/apiBase.test.ts services/frontend/src/components/worldview/SearchPanel.tsx services/frontend/src/components/worldview/SearchPanel.test.tsx
git commit -m "refactor: consolidate API prefix to /api (ADR-0001, F1 follow-up)"
```

---

### Task 16: Final verification & smoke test

- [ ] **Step 1: Full frontend suite**

```bash
cd services/frontend
npx vitest run
```

Expected: all PASS. Record count (e.g. "115/115").

- [ ] **Step 2: Lint + type-check**

```bash
npm run lint && npm run type-check
```

Expected: both PASS, zero errors.

- [ ] **Step 3: Full backend suite**

```bash
cd services/backend
uv run pytest
uv run ruff check app/
```

Expected: all PASS.

- [ ] **Step 4: Build the frontend**

```bash
cd services/frontend
npm run build
```

Expected: SUCCESS, no TS errors.

- [ ] **Step 5: Start the stack & manual visual check**

```bash
cd /home/deadpool-ultra/ODIN/OSINT
./odin.sh up interactive
```

Then open a browser to `http://localhost:5173/` and check:

- **`/`** — Landing renders; four numerals + signal feed + orrery; TopBar visible.
- **`/worldview`** — Globe renders; TopBar visible at top; § Layers tab top-left (collapsed); § Search tab top-right (collapsed); § Ticker expanded bottom-left; no legacy StatusBar/ClockBar/ThreatRegister; no console errors about `_cesiumWidget` or "Resource already being fetched"; keyboard `/` opens Search; `L` toggles Layers.
- **`/briefing`** — Placeholder from S1, TopBar visible.
- **`/warroom`** — Placeholder from S1, TopBar visible.

Close the stack after check:

```bash
./odin.sh down
```

- [ ] **Step 6: If all green — final commit (no-op but marks sprint complete)**

```bash
git log --oneline main..HEAD
```

Expected: 15–16 commits matching the task list. No workaround commits remain (`git log --oneline | grep -i workaround` → empty).

- [ ] **Step 7: Offer merge path**

Sprint 2 is mergeable. Options:
- Squash-merge to main via `gh pr create --base main --head feature/odin-s2-worldview-port`
- Keep as feature branch until S3 is ready and merge both together

Defer to user — do not merge automatically.

---

## Verification (end-to-end)

After Task 16:

1. **Spec §4.2 coverage.** `/worldview` has § Layers (top-left, collapsed), § Search (top-right, collapsed + `/` hotkey), § Inspector (right slide-in on click), § Ticker (bottom-left, expanded). Panel-Stil: `rgba(18,17,14,0.84)` + 1px granite + 12px blur. ✔ via Tasks 2, 7, 9, 10, 11, 12.
2. **Workaround elimination.** StrictMode on (Task 5), error boundary gone (Task 8), TopBar on /worldview (Task 6). ✔ verified manually in Task 16 Step 5.
3. **Root-cause fixes.** SatelliteLayer NaN guard (Task 3), polling-hook cancelled guards (Task 4). ✔ via unit tests.
4. **Follow-ups cleared.** F1 API prefix (Task 15), F2 signals contract doc (Task 14), F3 wildcard listener (Task 13). ✔ via unit tests + doc presence.
5. **Spec §9.5 (no page reload).** React Router handles all four routes under one `<RouterProvider>`; TopBar NavLinks don't trigger reload. Verify manually via DevTools Network tab in Task 16 Step 5.
6. **Success Criterion §9.1 (visual coherence).** Worldview panels use the same palette/typography as Landing. Manual visual review in Task 16 Step 5.

## Notes for the executing engineer

- **Do not re-add pauschal isDestroyed() hardening** to layer cleanups — exploration confirmed all 14 layers already have the guards (memory was wrong). If StrictMode misbehaves after Task 5, the cause is elsewhere (most likely `GlobeViewer.tsx` Ion tileset fetch) — debug the actual error, don't bulk-patch.
- **Aircraft timestamp units are already aligned** — both sides use UNIX seconds. Do not "fix" this.
- **Munin chat panel** (S1 backlog mentioned it) belongs in S3 Briefing Room, not here. Don't try to preserve the old `RightPanel` intel chat — delete it, it's S3's job.
- **`RightPanel` deletion** removes the ability to query Munin from the Worldview. If a user complains before S3 lands, they can still use the backend `/api/intel` endpoint directly. Do not block S2 merge on this.
- **`useIntel` hook** becomes unused after Task 7 — leave it in the codebase. S3 will reuse it in the Briefing Room's chat panel.
