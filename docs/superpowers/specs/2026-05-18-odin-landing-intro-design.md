# ODIN Landing Intro Design

Date: 2026-05-18

## Context

ODIN already has a React landing route at `/` through `services/frontend/src/app/router.tsx`. The current `LandingPage` renders live 24h metrics, the Signal Feed, and an Orrery, and it deep-links into `/worldview`.

The loose root-level `test.html` is a standalone historical WWII analysis page using Tailwind and Chart.js CDNs. It is not the ODIN operational landing surface and should not be ported for this task.

## Goal

Make the existing React landing page feel like an intentional ODIN entry point before the live dashboard content appears.

The first screen should introduce ODIN as a tactical intelligence platform, then hand the user directly into operational workflows without breaking the existing live data surface.

## Chosen Approach

Use the existing React landing page as the canonical homepage and add a compact ODIN intro section above the current metrics.

This keeps the current routing, API calls, Signal Feed hydration, SSE updates, and Worldview deep links intact. The work is a focused frontend integration rather than a broad redesign.

## Page Structure

The landing page will render in this order:

1. ODIN intro section.
2. Existing 24h metric tiles.
3. Existing Signal Feed and Orrery section.

The intro section contains:

- A concise platform kicker: `ODIN Tactical Intelligence Platform`.
- A short hero headline that explains the operational purpose.
- Supporting copy that frames ODIN as a fused live-signals, infrastructure, incident, and briefing workspace.
- Three clear entry actions:
  - `Enter Worldview` -> `/worldview`
  - `Open Briefing` -> `/briefing`
  - `War Room` -> `/warroom`
- A compact system status panel using static labels for currently wired subsystems:
  - Ingestion
  - Signal Feed
  - Vector Search
  - Graph Memory
  - Window

The status panel is presentational only for this task. It must not introduce new backend dependencies.

## Components

Primary file:

- `services/frontend/src/pages/LandingPage.tsx`

Existing components remain in use:

- `NumericHero`
- `Orrery`
- `SectionHeading`
- `SignalFeedItem`

The intro can be implemented inline inside `LandingPage.tsx` because it is currently page-specific and does not justify a shared abstraction. If the markup becomes noisy, a private helper component in the same file is acceptable.

## Data Flow

No API contracts change.

Existing flow remains:

- `getLandingSummary("24h")` fetches `/api/landing/summary?window=24h`.
- `useSignalFeed()` hydrates from `/api/signals/latest` and listens for SSE updates.
- Metric tile clicks navigate to `/worldview?filter=<key>`.
- Signal clicks navigate to `/worldview?entity=<source:id>`.

New intro actions use `useNavigate` or router links and navigate to existing routes only.

## Error Handling

Existing summary error behavior stays in place: the landing header shows the error string when the summary request fails.

The new intro status panel must not report dynamic health unless that data already exists in the frontend state. Static status labels avoid misleading failed-health states and avoid adding a brittle dependency.

## Responsive Behavior

The intro section should use stable CSS grid/flex rules that collapse cleanly on narrow screens:

- Desktop: intro copy and status panel side-by-side.
- Mobile: intro copy followed by status panel.
- Existing metric tiles should remain a grid, but may collapse to two columns or one column if needed to avoid cramped text.

Text must not overlap controls or overflow buttons.

## Testing

Use TDD for the implementation.

Add or update frontend tests to verify:

- `/` renders the ODIN intro headline or kicker.
- The three intro actions are present and navigate to `/worldview`, `/briefing`, and `/warroom`.
- Existing landing behavior still works:
  - Metric values render from the mocked summary endpoint.
  - Hotspots tile still navigates to `/worldview?filter=hotspots`.
  - Feed hydration from `/api/signals/latest` still renders items.

Run focused tests first, then frontend type/lint checks if available in the local dependency state.

## Out of Scope

- Porting `test.html`.
- Adding Chart.js or Tailwind CDNs.
- Adding new backend health endpoints.
- Reworking the global `TopBar`.
- Redesigning Worldview, Briefing, or War Room.
