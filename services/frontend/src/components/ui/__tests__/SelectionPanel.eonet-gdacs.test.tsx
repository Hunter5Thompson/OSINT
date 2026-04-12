import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { SelectionPanel } from "../SelectionPanel";

describe("SelectionPanel — EONET selection", () => {
  it("renders EONET event fields", () => {
    render(
      <SelectionPanel
        selected={{
          type: "eonet",
          data: { id: "e1", title: "Wildfire California", category: "wildfires", status: "open", latitude: 34.0, longitude: -118.5, event_date: "2026-04-10" },
        }}
        onClose={vi.fn()}
        viewer={null}
      />,
    );
    expect(screen.getByText("Wildfire California")).toBeDefined();
    expect(screen.getByText("WILDFIRES")).toBeDefined();
    expect(screen.getByText("OPEN")).toBeDefined();
  });
});

describe("SelectionPanel — GDACS selection", () => {
  it("renders GDACS event fields", () => {
    render(
      <SelectionPanel
        selected={{
          type: "gdacs",
          data: { id: "g1", event_type: "EQ", event_name: "Earthquake Indonesia", alert_level: "Red", severity: 6.8, country: "Indonesia", latitude: 3.5, longitude: 95.0, from_date: "2026-04-10", to_date: "2026-04-10" },
        }}
        onClose={vi.fn()}
        viewer={null}
      />,
    );
    expect(screen.getByText("Earthquake Indonesia")).toBeDefined();
    expect(screen.getByText("Earthquake")).toBeDefined();
    expect(screen.getByText("Red")).toBeDefined();
    expect(screen.getByText("Indonesia")).toBeDefined();
  });
});
