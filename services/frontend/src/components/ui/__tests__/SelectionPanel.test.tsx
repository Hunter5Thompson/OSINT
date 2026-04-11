import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { SelectionPanel } from "../SelectionPanel";
import type { FIRMSHotspot, AircraftTrack } from "../../../types";

const hotspot: FIRMSHotspot = {
  id: "h1",
  latitude: 48.1234,
  longitude: 37.5678,
  frp: 87.3,
  brightness: 382.1,
  confidence: "h",
  acq_date: "2026-04-11",
  acq_time: "1423",
  satellite: "VIIRS_SNPP_NRT",
  bbox_name: "ukraine",
  possible_explosion: true,
  firms_map_url: "https://example/map",
};

const track: AircraftTrack = {
  icao24: "AE1234",
  callsign: "RCH842",
  type_code: "C17",
  military_branch: "USAF",
  registration: "05-5140",
  points: [
    { lat: 51, lon: 12, altitude_m: 10000, speed_ms: 240, heading: 90, timestamp: 1 },
    { lat: 52, lon: 13, altitude_m: 10100, speed_ms: 245, heading: 92, timestamp: 2 },
  ],
};

describe("SelectionPanel", () => {
  it("returns null when selected is null", () => {
    const { container } = render(
      <SelectionPanel selected={null} onClose={vi.fn()} viewer={null} />,
    );
    expect(container.firstChild).toBeNull();
  });

  it("renders FIRMS details with explosion badge and link", () => {
    render(
      <SelectionPanel
        selected={{ type: "firms", data: hotspot }}
        onClose={vi.fn()}
        viewer={null}
      />,
    );
    expect(screen.getByText(/THERMAL ANOMALY/i)).toBeInTheDocument();
    expect(screen.getByText(/POSSIBLE EXPLOSION/i)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /FIRMS Map/i })).toHaveAttribute(
      "href",
      "https://example/map",
    );
  });

  it("renders aircraft details with callsign and points count", () => {
    render(
      <SelectionPanel
        selected={{ type: "aircraft", data: track }}
        onClose={vi.fn()}
        viewer={null}
      />,
    );
    expect(screen.getByText(/RCH842/)).toBeInTheDocument();
    expect(screen.getByText(/C17/)).toBeInTheDocument();
    expect(screen.getByText(/2 points/i)).toBeInTheDocument();
  });

  it("calls onClose when × is clicked", () => {
    const onClose = vi.fn();
    render(
      <SelectionPanel
        selected={{ type: "firms", data: hotspot }}
        onClose={onClose}
        viewer={null}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: /close/i }));
    expect(onClose).toHaveBeenCalled();
  });
});
