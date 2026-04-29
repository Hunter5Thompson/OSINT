import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { TimelineQuadrant } from "./TimelineQuadrant";
import type { Incident } from "../../types/incident";

const inc: Incident = {
  id: "inc-001",
  kind: "firms.cluster",
  title: "x",
  severity: "high",
  coords: [0, 0],
  location: "-",
  status: "open",
  trigger_ts: "2026-04-25T10:00:00Z",
  closed_ts: null,
  sources: [],
  layer_hints: [],
  timeline: [
    { t_offset_s: 0, kind: "trigger", text: "FIRMS threshold" },
    { t_offset_s: 68, kind: "signal", text: "UCDP severity HIGH", severity: "high" },
    { t_offset_s: 134, kind: "agent", text: "qdrant.search → 12 hits" },
  ],
};

describe("TimelineQuadrant", () => {
  it("renders newest-first list with trigger as baseline", () => {
    render(<TimelineQuadrant incident={inc} />);
    const items = screen.getAllByTestId("timeline-row");
    expect(items[0]?.textContent).toMatch(/qdrant\.search/);
    expect(items[items.length - 1]?.textContent).toMatch(/Trigger/i);
  });

  it("formats T-offsets as T+mm:ss", () => {
    render(<TimelineQuadrant incident={inc} />);
    expect(screen.getByText("T+01:08")).toBeInTheDocument();
  });
});
