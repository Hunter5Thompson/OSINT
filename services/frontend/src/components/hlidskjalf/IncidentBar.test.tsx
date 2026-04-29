import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import type { Incident } from "../../types/incident";
import { IncidentBar } from "./IncidentBar";

const baseIncident: Incident = {
  id: "inc-001",
  kind: "firms.cluster",
  title: "Kurdistan · Thermal Escalation",
  severity: "high",
  coords: [36.34, 41.87],
  location: "Sinjar ridge",
  status: "open",
  trigger_ts: "2026-04-25T10:00:00Z",
  closed_ts: null,
  sources: ["firms·1"],
  layer_hints: ["firmsHotspots"],
  timeline: [],
};

describe("IncidentBar", () => {
  it("renders title + LIVE tag + coords", () => {
    render(<IncidentBar incident={baseIncident} />);
    expect(screen.getByText(/INCIDENT · LIVE/i)).toBeInTheDocument();
    expect(screen.getByText(/Kurdistan/)).toBeInTheDocument();
    expect(screen.getByText(/36\.340N · 41\.870E/)).toBeInTheDocument();
  });

  it("renders T+ clock with sentinel tone", () => {
    render(<IncidentBar incident={baseIncident} />);
    const clock = screen.getByTestId("incident-tplus");
    expect(clock.textContent).toMatch(/^T\+/);
  });
});
