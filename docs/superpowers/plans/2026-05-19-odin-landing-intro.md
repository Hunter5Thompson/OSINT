# ODIN Landing Intro Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Hlíðskjalf-consistent ODIN intro section to the existing React landing page while preserving live metrics, Signal Feed, Orrery, and deep-link navigation.

**Architecture:** Keep `/` routed to the existing `LandingPage`. Add page-local presentational data and markup in `LandingPage.tsx`, with router links for the three intro actions and no new API calls. Extend the existing landing tests so the new intro is covered and current landing behavior stays pinned.

**Tech Stack:** React, TypeScript strict mode, React Router, Vitest, Testing Library, existing Hlíðskjalf CSS variables/utilities.

---

## File Structure

- Modify `services/frontend/src/test/landing/landingSummary.test.tsx`
  - Add failing tests for the intro kicker/headline, capability labels, `Index Rerum` preservation, and CTA navigation.
  - Keep existing summary/feed/navigation regression tests intact.
- Modify `services/frontend/src/pages/LandingPage.tsx`
  - Add typed local constants for intro actions and capability labels.
  - Add a small page-local `LandingIntro` component.
  - Render `LandingIntro` before the existing `Index Rerum · last 24h` header.
  - Preserve existing `getLandingSummary`, `useSignalFeed`, tile clicks, feed clicks, and error display behavior.

No new shared component or CSS file is required for this scoped change.

## Task 1: Add Failing Intro And Capability Tests

**Files:**
- Modify: `services/frontend/src/test/landing/landingSummary.test.tsx`

- [ ] **Step 1: Add intro render tests**

Append this block before `describe("LandingPage · numerals", ...)`:

```tsx
describe("LandingPage · intro", () => {
  it("renders the ODIN Hlíðskjalf intro before the existing Index Rerum header", async () => {
    installFetch({ summary: fullSummary });
    renderAt("/");

    expect(await screen.findByText(/ODIN · Hlíðskjalf/i)).toBeInTheDocument();
    expect(
      screen.getByRole("heading", {
        name: /operating picture/i,
      }),
    ).toBeInTheDocument();
    expect(screen.getByText(/Index Rerum · last 24h/i)).toBeInTheDocument();
  });

  it("renders static capability labels without health status claims", async () => {
    installFetch({ summary: fullSummary });
    renderAt("/");

    expect(await screen.findByText(/Hugin/i)).toBeInTheDocument();
    expect(screen.getByText(/Signalia/i)).toBeInTheDocument();
    expect(screen.getByText(/Vectorium/i)).toBeInTheDocument();
    expect(screen.getByText(/Memoria/i)).toBeInTheDocument();
    expect(screen.getByText(/Fenestra/i)).toBeInTheDocument();
    expect(screen.queryByText(/online/i)).not.toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
cd services/frontend && npm test -- src/test/landing/landingSummary.test.tsx
```

Expected: FAIL because `ODIN · Hlíðskjalf`, the hero heading, and capability labels do not exist yet.

## Task 2: Add Failing CTA Navigation Tests

**Files:**
- Modify: `services/frontend/src/test/landing/landingSummary.test.tsx`

- [ ] **Step 1: Import user-event**

Add the import near the existing Testing Library imports:

```tsx
import userEvent from "@testing-library/user-event";
```

Also add `within` to the existing Testing Library import:

```tsx
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
```

- [ ] **Step 2: Add CTA navigation tests**

Append this block after the intro tests:

```tsx
describe("LandingPage · intro navigation", () => {
  it("navigates from the Worldview intro action to /worldview", async () => {
    const user = userEvent.setup();
    installFetch({ summary: fullSummary });
    renderAt("/");

    const entryNav = await screen.findByRole("navigation", { name: /landing entry points/i });
    await user.click(within(entryNav).getByRole("link", { name: /enter worldview/i }));

    expect(await screen.findByTestId("worldview-page")).toBeInTheDocument();
  });

  it("renders Briefing from the intro action", async () => {
    const user = userEvent.setup();
    installFetch({ summary: fullSummary });
    renderAt("/");

    const entryNav = await screen.findByRole("navigation", { name: /landing entry points/i });
    await user.click(within(entryNav).getByRole("link", { name: /open briefing/i }));

    expect(await screen.findByText(/Dossier Archive/i)).toBeInTheDocument();
  });

  it("renders War Room from the intro action", async () => {
    const user = userEvent.setup();
    installFetch({ summary: fullSummary });
    renderAt("/");

    const entryNav = await screen.findByRole("navigation", { name: /landing entry points/i });
    await user.click(within(entryNav).getByRole("link", { name: /^war room$/i }));

    expect(await screen.findByText(/no active incident/i)).toBeInTheDocument();
  });
});
```

- [ ] **Step 3: Run tests to verify they fail**

Run:

```bash
cd services/frontend && npm test -- src/test/landing/landingSummary.test.tsx
```

Expected: FAIL because the three intro links do not exist yet.

## Task 3: Implement The Landing Intro

**Files:**
- Modify: `services/frontend/src/pages/LandingPage.tsx`

- [ ] **Step 1: Add Link import**

Change the router import:

```tsx
import { Link, useNavigate } from "react-router-dom";
```

- [ ] **Step 2: Add intro constants above `export function LandingPage()`**

```tsx
const INTRO_ACTIONS = [
  { to: "/worldview", label: "Enter Worldview" },
  { to: "/briefing", label: "Open Briefing" },
  { to: "/warroom", label: "War Room" },
] as const;

const CAPABILITIES = [
  { label: "Hugin", detail: "ingestion pipeline" },
  { label: "Signalia", detail: "Signal Feed / SSE" },
  { label: "Vectorium", detail: "Qdrant vector search" },
  { label: "Memoria", detail: "Neo4j graph memory" },
  { label: "Fenestra", detail: "24h landing window" },
] as const;
```

- [ ] **Step 3: Add page-local `LandingIntro` component**

```tsx
function LandingIntro() {
  return (
    <section
      data-part="landing-intro"
      style={{
        display: "grid",
        gridTemplateColumns: "minmax(0, 1.25fr) minmax(18rem, 0.75fr)",
        gap: "2rem",
        alignItems: "stretch",
        paddingBottom: "2rem",
        borderBottom: "1px solid var(--granite)",
      }}
    >
      <div style={{ display: "flex", flexDirection: "column", justifyContent: "center" }}>
        <span className="eyebrow">ODIN · Hlíðskjalf</span>
        <h1
          className="serif"
          style={{
            margin: "0.65rem 0 1rem",
            maxWidth: "46rem",
            color: "var(--parchment)",
            fontSize: "clamp(3rem, 6vw, 5.75rem)",
            lineHeight: 0.95,
            fontWeight: 400,
          }}
        >
          See the operating picture before it becomes a report.
        </h1>
        <p
          style={{
            maxWidth: "42rem",
            margin: 0,
            color: "var(--bone)",
            fontSize: "1rem",
            lineHeight: 1.65,
          }}
        >
          ODIN fuses live signals, infrastructure layers, incident context, and
          briefing workflows into one tactical intelligence surface.
        </p>
        <nav
          aria-label="Landing entry points"
          style={{
            display: "flex",
            flexWrap: "wrap",
            gap: "0.75rem",
            marginTop: "1.5rem",
          }}
        >
          {INTRO_ACTIONS.map((action, index) => (
            <Link
              key={action.to}
              to={action.to}
              className="mono"
              style={{
                border: `1px solid ${index === 0 ? "var(--amber)" : "var(--granite)"}`,
                color: index === 0 ? "var(--parchment)" : "var(--stone)",
                textDecoration: "none",
                textTransform: "uppercase",
                letterSpacing: "0.12em",
                fontSize: "0.72rem",
                padding: "0.75rem 0.95rem",
                background: index === 0 ? "rgba(196, 129, 58, 0.08)" : "transparent",
              }}
            >
              {action.label}
            </Link>
          ))}
        </nav>
      </div>

      <aside
        aria-label="ODIN capabilities"
        style={{
          border: "1px solid var(--granite)",
          padding: "1rem",
          display: "grid",
          gap: "0.75rem",
          alignContent: "start",
        }}
      >
        <SectionHeading label="Subsystemata" />
        {CAPABILITIES.map((capability) => (
          <div
            key={capability.label}
            style={{
              borderTop: "1px solid var(--granite)",
              paddingTop: "0.75rem",
            }}
          >
            <span className="mono" style={{ color: "var(--parchment)", fontSize: "0.78rem" }}>
              {capability.label}
            </span>
            <span
              style={{
                display: "block",
                marginTop: "0.2rem",
                color: "var(--stone)",
                fontSize: "0.84rem",
              }}
            >
              {capability.detail}
            </span>
          </div>
        ))}
      </aside>
    </section>
  );
}
```

- [ ] **Step 4: Render the intro before the existing header**

Inside `LandingPage`'s root `<div>`, before the existing `<header ...>`, add:

```tsx
<LandingIntro />
```

- [ ] **Step 5: Run focused tests**

Run:

```bash
cd services/frontend && npm test -- src/test/landing/landingSummary.test.tsx
```

Expected: PASS.

## Task 4: Adjust Responsive Behavior Without Changing Data Flow

**Files:**
- Modify: `services/frontend/src/pages/LandingPage.tsx`

- [ ] **Step 1: Add stable responsive inline styles**

If the intro grid is cramped in narrow test/browser viewports, replace the intro `gridTemplateColumns` with a responsive CSS grid expression:

```tsx
gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 18rem), 1fr))",
```

If the metrics grid is cramped, replace its `gridTemplateColumns` with:

```tsx
gridTemplateColumns: "repeat(auto-fit, minmax(10rem, 1fr))",
```

- [ ] **Step 2: Re-run focused tests**

Run:

```bash
cd services/frontend && npm test -- src/test/landing/landingSummary.test.tsx
```

Expected: PASS.

## Task 5: Final Verification

**Files:**
- Verify: `services/frontend/src/pages/LandingPage.tsx`
- Verify: `services/frontend/src/test/landing/landingSummary.test.tsx`

- [ ] **Step 1: Run focused landing tests**

Run:

```bash
cd services/frontend && npm test -- src/test/landing/landingSummary.test.tsx
```

Expected: PASS.

- [ ] **Step 2: Run frontend type check**

Run:

```bash
cd services/frontend && npm run type-check
```

Expected: PASS.

- [ ] **Step 3: Run frontend lint**

Run:

```bash
cd services/frontend && npm run lint
```

Expected: PASS.

- [ ] **Step 4: Inspect git diff**

Run:

```bash
git diff -- services/frontend/src/pages/LandingPage.tsx services/frontend/src/test/landing/landingSummary.test.tsx
```

Expected: only the landing intro implementation and related tests changed.

- [ ] **Step 5: Commit implementation**

Run:

```bash
git add services/frontend/src/pages/LandingPage.tsx services/frontend/src/test/landing/landingSummary.test.tsx
git commit -m "feat(frontend): add odin landing intro"
```
