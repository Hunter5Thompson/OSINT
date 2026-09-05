import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { LandingPage } from "../../pages/LandingPage";
import { getLandingSummary } from "../../services/api";

vi.mock("../../services/api", () => ({ getLandingSummary: vi.fn() }));
vi.mock("../../components/landing/ReferenceGlobe", () => ({
  ReferenceGlobe: () => null,
}));
vi.mock("../../hooks/useSignalFeed", () => ({
  useSignalFeed: () => ({
    status: "reconnecting",
    items: [
      {
        event_id: "123-1",
        ts: "2026-09-05T12:00:00Z",
        type: "signal.gdelt",
        payload: {
          title: "Black Sea shipping disruption",
          source: "gdelt",
          redis_id: "123-1",
        },
      },
    ],
  }),
}));

function Location() {
  return <output data-testid="location">{useLocation().search}</output>;
}
function renderPage() {
  render(
    <MemoryRouter>
      <LandingPage />
      <Location />
    </MemoryRouter>,
  );
}

beforeEach(() => {
  vi.mocked(getLandingSummary).mockReset().mockResolvedValue({
    window: "24h",
    generated_at: "2026-09-05T12:00:00Z",
    hotspots_24h: 7,
    hotspots_source: "qdrant",
    conflict_24h: 3,
    conflict_source: "neo4j",
    nuntii_24h: 12,
    nuntii_source: "qdrant",
    libri_24h: 0,
    libri_source: "reports",
    reports_not_available_yet: true,
  });
});

describe("landing situation experience", () => {
  it("preserves the signal identity and human-readable title when opening Worldview", async () => {
    renderPage();
    fireEvent.click(
      await screen.findByRole("button", {
        name: /Black Sea shipping disruption/,
      }),
    );
    const params = new URLSearchParams(
      screen.getByTestId("location").textContent ?? "",
    );
    expect(params.get("entity")).toBe("gdelt:123-1");
    expect(params.get("q")).toBe("Black Sea shipping disruption");
  });

  it("distinguishes stream reconnection from a successfully loaded summary", async () => {
    renderPage();
    expect(await screen.findByText("7")).toBeInTheDocument();
    expect(screen.getByText(/reconnecting/i)).toBeInTheDocument();
    expect(screen.queryByText(/^live$/i)).not.toBeInTheDocument();
    expect(
      screen.getByText(/Snapshot · 05 Sept? 2026.*12:00.*UTC/i),
    ).toBeInTheDocument();
  });

  it("offers a retry when the summary fails, then recovers without remounting", async () => {
    vi.mocked(getLandingSummary).mockRejectedValueOnce(new Error("offline"));
    renderPage();
    fireEvent.click(
      await screen.findByRole("button", { name: /retry summary/i }),
    );
    expect(await screen.findByText("7")).toBeInTheDocument();
    await waitFor(() =>
      expect(
        screen.queryByRole("button", { name: /retry summary/i }),
      ).toBeNull(),
    );
  });
});
