import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";

import { WarRoomPage } from "./WarRoomPage";

const fakeActive = {
  id: "inc-global",
  kind: "firms.cluster",
  title: "Global Active Incident",
  severity: "high" as const,
  coords: [0, 0] as [number, number],
  location: "—",
  status: "open" as const,
  trigger_ts: "2026-04-25T10:00:00Z",
  closed_ts: null,
  sources: [],
  layer_hints: [],
  timeline: [],
};

const useIncidentsMock = vi.fn();
vi.mock("../hooks/useIncidents", () => ({ useIncidents: () => useIncidentsMock() }));

vi.mock("../services/api", async (orig) => {
  const actual = (await orig()) as Record<string, unknown>;
  return {
    ...actual,
    getConfig: vi.fn().mockResolvedValue({ cesium_ion_token: "" }),
    getIncident: vi.fn().mockResolvedValue(null),
    queryIntel: vi.fn().mockReturnValue({ abort: vi.fn() } as unknown as AbortController),
    silenceIncident: vi.fn().mockResolvedValue(null),
    promoteIncident: vi.fn().mockResolvedValue(null),
  };
});

beforeEach(() => {
  useIncidentsMock.mockReturnValue({
    status: "live",
    active: null,
    history: [],
    latestEnvelope: null,
  });
});

describe("WarRoomPage", () => {
  it("renders the empty Theatre + four quadrant frames when no incident", async () => {
    render(
      <MemoryRouter initialEntries={["/warroom"]}>
        <Routes>
          <Route path="/warroom" element={<WarRoomPage />} />
        </Routes>
      </MemoryRouter>,
    );
    expect(await screen.findByText(/no active incident/)).toBeInTheDocument();
    expect(screen.getByText(/Timeline/)).toBeInTheDocument();
    expect(screen.getByText(/Munin · stream/)).toBeInTheDocument();
    expect(screen.getByText(/Raw · sources/)).toBeInTheDocument();
  });

  it("does not fall back to global active when route param is set but lookup returns null", async () => {
    useIncidentsMock.mockReturnValue({
      status: "live",
      active: fakeActive,
      history: [fakeActive],
      latestEnvelope: null,
    });

    render(
      <MemoryRouter initialEntries={["/warroom/inc-missing"]}>
        <Routes>
          <Route path="/warroom/:incidentId" element={<WarRoomPage />} />
        </Routes>
      </MemoryRouter>,
    );
    expect(await screen.findByText(/no active incident/)).toBeInTheDocument();
    // The global active should NOT have leaked through.
    expect(screen.queryByText(/Global Active Incident/)).toBeNull();
  });
});
