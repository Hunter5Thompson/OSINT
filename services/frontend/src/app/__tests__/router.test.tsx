import { render, screen } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { routes } from "../router";

vi.mock("../../pages/WorldviewPage", () => ({
  WorldviewPage: () => <div data-testid="worldview-page">worldview</div>,
}));

describe("root spatial-scope redirect", () => {
  it("preserves scope and all foreign parameters when redirecting to worldview", async () => {
    const router = createMemoryRouter(routes, {
      initialEntries: [
        "/?scope=country%3AUKR&layer=flights&filter=hot&foreign=one&foreign=two",
      ],
    });
    render(<RouterProvider router={router} />);

    expect(await screen.findByTestId("worldview-page")).toBeInTheDocument();
    expect(router.state.location.pathname).toBe("/worldview");
    const search = new URLSearchParams(router.state.location.search);
    expect(search.get("scope")).toBe("country:UKR");
    expect(search.get("layer")).toBe("flights");
    expect(search.get("filter")).toBe("hot");
    expect(search.getAll("foreign")).toEqual(["one", "two"]);
  });
});
