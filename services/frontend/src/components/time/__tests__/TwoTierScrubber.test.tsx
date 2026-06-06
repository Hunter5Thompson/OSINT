import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { TwoTierScrubber } from "../TwoTierScrubber";
import type { WindowEventSample } from "../../../types";

const ev: WindowEventSample = {
  kind: "event", id: "ev1", time: "2026-05-01T06:00:00Z", time_basis: "indexed",
  title: "Airstrike", codebook_type: "military.airstrike", severity: "high",
};

describe("TwoTierScrubber", () => {
  it("renders an event tick and selecting it calls onSelectEvent", () => {
    const onSelectEvent = vi.fn();
    render(
      <TwoTierScrubber
        events={[ev]} mode="live" cursorMs={Date.parse(ev.time)}
        onSelectEvent={onSelectEvent} onSeek={vi.fn()} onToggleMode={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: /Airstrike/i }));
    expect(onSelectEvent).toHaveBeenCalledWith(ev);
  });

  it("shows replay empty state when no events", () => {
    render(
      <TwoTierScrubber
        events={[]} mode="replay" cursorMs={0}
        onSelectEvent={vi.fn()} onSeek={vi.fn()} onToggleMode={vi.fn()}
      />,
    );
    expect(screen.getByText(/no events in window/i)).toBeInTheDocument();
  });
});
