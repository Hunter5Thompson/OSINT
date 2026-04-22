import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { routes } from "../../app/router";

// Cesium viewer is heavy and not relevant to AppShell tests — stub the Worldview
// page so `/worldview` renders without spinning up a globe.
vi.mock("../../pages/WorldviewPage", () => ({
  WorldviewPage: () => <div data-testid="worldview-page">worldview</div>,
}));
vi.mock("../../pages/LandingPage", () => ({
  LandingPage: () => <div data-testid="landing-page">landing</div>,
}));

describe("AppShell", () => {
  it("renders TopBar on /", async () => {
    const router = createMemoryRouter(routes, { initialEntries: ["/"] });
    render(<RouterProvider router={router} />);
    expect(await screen.findByText("Hlíðskjalf")).toBeInTheDocument();
  });

  it("renders TopBar on /worldview (no S1 hide)", () => {
    const router = createMemoryRouter(routes, { initialEntries: ["/worldview"] });
    render(<RouterProvider router={router} />);
    expect(screen.getByText("Hlíðskjalf")).toBeInTheDocument();
  });

  it("worldview route has no errorElement", async () => {
    const { routes: r } = await import("../../app/router");
    expect(r.length).toBeGreaterThan(0);
    const appShellRoute = r[0]!;
    expect(appShellRoute.children).toBeDefined();
    const worldview = appShellRoute.children!.find((c) => c.path === "/worldview");
    expect(worldview).toBeDefined();
    expect(worldview?.errorElement).toBeUndefined();
  });
});
