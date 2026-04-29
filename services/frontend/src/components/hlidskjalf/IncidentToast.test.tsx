import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

import { IncidentToast } from "./IncidentToast";
import type { Incident } from "../../types/incident";

const inc: Incident = {
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

describe("IncidentToast", () => {
  it("renders nothing when incident is null", () => {
    const { container } = render(
      <MemoryRouter>
        <IncidentToast incident={null} onDismiss={() => {}} />
      </MemoryRouter>,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("shows title + Open War Room link when incident present", () => {
    render(
      <MemoryRouter>
        <IncidentToast incident={inc} onDismiss={() => {}} />
      </MemoryRouter>,
    );
    expect(screen.getByText(/Kurdistan/)).toBeInTheDocument();
    const link = screen.getByRole("link", { name: /open war room/i });
    expect(link).toHaveAttribute("href", "/warroom/inc-001");
  });

  it("auto-dismisses after the configured ttl", () => {
    vi.useFakeTimers();
    const onDismiss = vi.fn();
    render(
      <MemoryRouter>
        <IncidentToast incident={inc} onDismiss={onDismiss} ttlMs={500} />
      </MemoryRouter>,
    );
    vi.advanceTimersByTime(600);
    expect(onDismiss).toHaveBeenCalled();
    vi.useRealTimers();
  });
});
