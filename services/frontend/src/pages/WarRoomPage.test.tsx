import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";

import { WarRoomPage } from "./WarRoomPage";

vi.mock("../hooks/useIncidents", () => ({
  useIncidents: () => ({
    status: "live",
    active: null,
    history: [],
    latestEnvelope: null,
  }),
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
});
