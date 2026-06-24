import { describe, it, expect, vi, beforeEach } from "vitest";
import { act, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";

import { WarRoomPage } from "./WarRoomPage";
import { queryIntel } from "../services/api";
import type { IntelAnalysis } from "../types";

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

const secondActive = {
  ...fakeActive,
  id: "inc-second",
  title: "Second Incident",
};

const useIncidentsMock = vi.fn();
vi.mock("../hooks/useIncidents", () => ({ useIncidents: () => useIncidentsMock() }));
vi.mock("../components/warroom/TheatreQuadrant", () => ({
  TheatreQuadrant: ({ incident }: { incident: { title?: string } | null }) => (
    <div data-testid="theatre-quadrant">{incident?.title ?? "no active incident"}</div>
  ),
}));

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

  it("ignores stale Munin SSE callbacks after the active incident changes", async () => {
    const abort = vi.fn();
    const queryIntelMock = vi.mocked(queryIntel);
    let onResult: ((analysis: IntelAnalysis) => void) | null = null;
    queryIntelMock.mockImplementation((_query, _onStatus, result) => {
      onResult = result;
      return { abort } as unknown as AbortController;
    });

    useIncidentsMock.mockReturnValue({
      status: "live",
      active: fakeActive,
      history: [fakeActive],
      latestEnvelope: null,
    });

    const { rerender } = render(
      <MemoryRouter initialEntries={["/warroom"]}>
        <Routes>
          <Route path="/warroom" element={<WarRoomPage />} />
        </Routes>
      </MemoryRouter>,
    );

    const input = await screen.findByPlaceholderText(/ask Munin/i);
    fireEvent.change(input, { target: { value: "brief stale race" } });
    fireEvent.submit(input.closest("form")!);
    expect(queryIntelMock).toHaveBeenCalledTimes(1);

    useIncidentsMock.mockReturnValue({
      status: "live",
      active: secondActive,
      history: [secondActive],
      latestEnvelope: null,
    });
    rerender(
      <MemoryRouter initialEntries={["/warroom"]}>
        <Routes>
          <Route path="/warroom" element={<WarRoomPage />} />
        </Routes>
      </MemoryRouter>,
    );

    expect(abort).toHaveBeenCalled();

    await act(async () => {
      onResult?.({
        query: "q",
        agent_chain: [],
        sources_used: [],
        analysis: "stale synthesis",
        confidence: 0.5,
        threat_assessment: "STALE",
        timestamp: "2026-06-24T10:00:00Z",
      });
    });

    expect(screen.queryByText(/stale synthesis/)).toBeNull();
    expect(screen.getByText(/working hypothesis/)).toBeInTheDocument();
  });
});
