import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { InspectorPanel } from "./InspectorPanel";

describe("InspectorPanel", () => {
  it("is hidden when nothing is selected", () => {
    const { container } = render(
      <InspectorPanel selected={null} onClose={vi.fn()} viewer={null} />,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("shows a firms hotspot with coordinates in Martian Mono", () => {
    render(
      <InspectorPanel
        selected={{
          type: "firms",
          data: {
            id: "firms-1",
            latitude: 12.34,
            longitude: 56.78,
            frp: 4.2,
            brightness: 320.5,
            confidence: "nominal",
            acq_date: "2026-04-21",
            acq_time: "1000",
            satellite: "VIIRS",
            bbox_name: "sinjar-ridge",
            possible_explosion: false,
            firms_map_url: "https://firms.modaps.eosdis.nasa.gov/...",
          },
        }}
        onClose={vi.fn()}
        viewer={null}
      />,
    );
    expect(screen.getByRole("region", { name: /Inspector/i })).toBeInTheDocument();
    expect(screen.getByText(/12.340 N, 56.780 E/)).toBeInTheDocument();
    expect(screen.getByText(/FIRMS hotspot · VIIRS/)).toBeInTheDocument();
  });

  it("calls onClose when × is clicked", () => {
    const onClose = vi.fn();
    render(
      <InspectorPanel
        selected={{
          type: "aircraft",
          data: {
            icao24: "abc123",
            callsign: null,
            type_code: null,
            military_branch: null,
            registration: null,
            points: [],
          },
        }}
        onClose={onClose}
        viewer={null}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: /close Inspector/i }));
    expect(onClose).toHaveBeenCalledOnce();
  });
});
