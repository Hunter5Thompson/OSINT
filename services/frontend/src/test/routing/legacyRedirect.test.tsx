/**
 * Routing + AppShell tests for ODIN S1 Task 1.
 *
 * Verifies:
 *  1. `/?entity=...` redirects to `/worldview?entity=...`
 *  2. `/?layer=...` redirects to `/worldview?layer=...`
 *  3. `/` without query stays on Landing placeholder
 *  4. AppShell (TopBar stub) is present across all four routes
 */
import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { routes } from "../../app/router";

// Cesium viewer is heavy and not relevant to routing tests — stub the Worldview
// page so `/worldview` renders without spinning up a globe.
vi.mock("../../pages/WorldviewPage", () => ({
  WorldviewPage: () => <div data-testid="worldview-page">worldview</div>,
}));

function renderAt(path: string) {
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  return render(<RouterProvider router={router} />);
}

describe("legacy query redirect + AppShell", () => {
  it("redirects /?entity=sinjar to /worldview?entity=sinjar", async () => {
    renderAt("/?entity=sinjar");
    expect(await screen.findByTestId("worldview-page")).toBeInTheDocument();
    // LandingPage no longer renders as placeholder after Task 6.
  });

  it("redirects /?layer=firmsHotspots to /worldview?layer=firmsHotspots", async () => {
    renderAt("/?layer=firmsHotspots");
    expect(await screen.findByTestId("worldview-page")).toBeInTheDocument();
  });

  it("stays on Landing when / has no migration query", async () => {
    renderAt("/");
    expect(await screen.findByText(/Index Rerum/i)).toBeInTheDocument();
    expect(screen.queryByTestId("worldview-page")).not.toBeInTheDocument();
  });

  it("renders AppShell TopBar stub on Landing", async () => {
    renderAt("/");
    expect(await screen.findByText("Hlíðskjalf")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /home/i })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /worldview/i })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /briefing/i })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /war room/i })).toBeInTheDocument();
  });

  it("hides TopBar on Worldview and lets legacy chrome take over (S1 temporary)", async () => {
    renderAt("/worldview");
    // S1 workaround: App.tsx StatusBar+ClockBar collide with TopBar and
    // Cesium needs a 100vh parent. S2 Worldview-Port will restore TopBar.
    expect(screen.queryByText("Hlíðskjalf")).not.toBeInTheDocument();
    expect(await screen.findByTestId("worldview-page")).toBeInTheDocument();
  });

  it("renders AppShell TopBar stub on Briefing", async () => {
    renderAt("/briefing");
    expect(await screen.findByText("Hlíðskjalf")).toBeInTheDocument();
    expect(screen.getByText(/§ Briefing · pending sprint 3/)).toBeInTheDocument();
  });

  it("renders AppShell TopBar stub on War Room", async () => {
    renderAt("/warroom");
    expect(await screen.findByText("Hlíðskjalf")).toBeInTheDocument();
    expect(screen.getByText(/§ War Room · pending sprint 4/)).toBeInTheDocument();
  });
});
