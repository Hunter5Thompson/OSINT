import { afterEach, describe, it, expect, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import * as api from "../../../services/api";
import { EventCallout } from "../EventCallout";

afterEach(() => vi.restoreAllMocks());

const DETAIL = {
  id: "e1", title: "Strike", time: "2026-06-01T00:00:00Z", time_basis: "indexed",
  codebook_type: "military.airstrike", severity: "critical", source: "gdelt",
  url: "http://x", location_name: "Kyiv", country: "UA", lat: 50.4, lon: 30.5,
} as const;

describe("EventCallout", () => {
  it("renders nothing when eventId is null", () => {
    const { container } = render(
      <EventCallout eventId={null} onClose={vi.fn()} onInspect={vi.fn()} />,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("fetches detail and renders a single callout", async () => {
    const spy = vi.spyOn(api, "getEventDetail").mockResolvedValue(DETAIL as never);
    render(<EventCallout eventId="e1" onClose={vi.fn()} onInspect={vi.fn()} />);
    await waitFor(() => expect(screen.getByText("Strike")).toBeInTheDocument());
    expect(spy).toHaveBeenCalledWith("e1", expect.anything());
    expect(screen.getAllByRole("group", { name: /event callout/i })).toHaveLength(1);
  });

  it("falls back to codebook_type when title is missing", async () => {
    vi.spyOn(api, "getEventDetail").mockResolvedValue({ ...DETAIL, title: null } as never);
    render(<EventCallout eventId="e1" onClose={vi.fn()} onInspect={vi.fn()} />);
    await waitFor(() => expect(screen.getByText("military.airstrike")).toBeInTheDocument());
  });
});
