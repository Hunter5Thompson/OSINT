import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { routes } from "../../app/router";

// Cesium viewer is heavy and not relevant to AppShell tests — stub the Worldview
// page so `/worldview` renders without spinning up a globe.
vi.mock("../../pages/WorldviewPage", () => ({
  WorldviewPage: () => <div data-testid="worldview-page">worldview</div>,
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
});
