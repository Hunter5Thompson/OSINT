import { afterEach, describe, it, expect, vi } from "vitest";
import { act, render, screen, waitFor } from "@testing-library/react";
import * as api from "../../../services/api";
import { EventCallout } from "../EventCallout";
import type { TimelineEventDetail } from "../../../types";

afterEach(() => vi.restoreAllMocks());

const DETAIL = {
  id: "e1", title: "Strike", time: "2026-06-01T00:00:00Z", time_basis: "indexed",
  codebook_type: "military.airstrike", severity: "critical", source: "gdelt",
  url: "http://x", location_name: "Kyiv", country: "UA", lat: 50.4, lon: 30.5,
} as const;

describe("EventCallout", () => {
  it("clears A immediately when B starts and B fails", async () => {
    const fetch = vi.spyOn(api, "getEventDetail").mockResolvedValueOnce(DETAIL as never);
    const props = { onClose: vi.fn(), onInspect: vi.fn() };
    const view = render(<EventCallout {...props} eventId="e1" />);
    await waitFor(() => expect(screen.getByText("Strike")).toBeInTheDocument());
    let reject!: (e: Error) => void;
    fetch.mockReturnValueOnce(new Promise((_resolve, fail) => { reject = fail; }));
    view.rerender(<EventCallout {...props} eventId="e2" />);
    expect(screen.queryByText("Strike")).not.toBeInTheDocument();
    expect(screen.queryByText("→ Inspector")).not.toBeInTheDocument();
    await act(async () => reject(new Error("unavailable")));
    expect(screen.getByText("e2")).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("Detail nicht verfügbar");
  });

  it("keeps B when A returns later", async () => {
    const resolves: ((d: TimelineEventDetail) => void)[] = [];
    vi.spyOn(api, "getEventDetail").mockImplementation(() => new Promise(resolve => resolves.push(resolve)));
    const props = { onClose: vi.fn(), onInspect: vi.fn() };
    const view = render(<EventCallout {...props} eventId="e1" />);
    view.rerender(<EventCallout {...props} eventId="e2" />);
    await act(async () => resolves[1]!({ ...DETAIL, id: "e2", title: "B" }));
    await act(async () => resolves[0]!(DETAIL));
    expect(screen.getByText("B")).toBeInTheDocument();
    expect(screen.queryByText("Strike")).not.toBeInTheDocument();
  });

  it("invalidates deselected responses even if the fetch ignores abort", async () => {
    let resolve!: (d: TimelineEventDetail) => void;
    vi.spyOn(api, "getEventDetail").mockReturnValueOnce(new Promise(done => { resolve = done; }))
      .mockRejectedValueOnce(new Error("B unavailable"));
    const props = { onClose: vi.fn(), onInspect: vi.fn() };
    const view = render(<EventCallout {...props} eventId="e1" />);
    view.rerender(<EventCallout {...props} eventId={null} />);
    await act(async () => resolve(DETAIL));
    view.rerender(<EventCallout {...props} eventId="e2" />);
    await waitFor(() => expect(screen.getByText("e2")).toBeInTheDocument());
    expect(screen.queryByText("Strike")).not.toBeInTheDocument();
  });

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
