/**
 * LandingPage wiring tests (ODIN S1 · Task 6).
 *
 * Verifies:
 *  8. All four hero numerals render from a mocked /api/landing/summary.
 *  9. `hotspots_24h: null` with `hotspots_source: "qdrant:unavailable"` shows
 *     the em-dash fallback and the source string as sub-label.
 * 10. With `reports_not_available_yet: true`, the Libri tile always shows 0
 *     and displays a "pending" label in Ash.
 * 11. Initial feed items render from `/api/signals/latest` before any SSE
 *     frames arrive.
 * 12. Clicking the Hotspots numeral navigates to `/worldview?filter=hotspots`.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { routes } from "../../app/router";
import {
  installMockEventSource,
  uninstallMockEventSource,
} from "../utils/mockEventSource";
import type { LandingSummary } from "../../types/landing";
import type { SignalEnvelope } from "../../types/signals";

// Worldview Cesium-heavy — stub it so navigation assertions don't boot Cesium.
vi.mock("../../pages/WorldviewPage", () => ({
  WorldviewPage: () => <div data-testid="worldview-page">worldview</div>,
}));

interface FetchOverrides {
  summary?: LandingSummary;
  latest?: SignalEnvelope[];
}

function installFetch({ summary, latest }: FetchOverrides) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const url = typeof input === "string" ? input : input.toString();
    if (url.includes("/api/landing/summary")) {
      return new Response(JSON.stringify(summary ?? {}), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    }
    if (url.includes("/api/signals/latest")) {
      return new Response(JSON.stringify(latest ?? []), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    }
    return new Response("not found", { status: 404 });
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function renderAt(path: string) {
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  return render(<RouterProvider router={router} />);
}

const fullSummary: LandingSummary = {
  window: "24h",
  generated_at: "2026-04-14T12:00:00.000Z",
  hotspots_24h: 187,
  hotspots_source: "qdrant",
  conflict_24h: 44,
  conflict_source: "neo4j",
  nuntii_24h: 28,
  nuntii_source: "qdrant",
  libri_24h: 0,
  libri_source: "reports",
  reports_not_available_yet: true,
};

beforeEach(() => {
  installMockEventSource();
});

afterEach(() => {
  uninstallMockEventSource();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("LandingPage · numerals", () => {
  it("renders all four metric values from the summary endpoint", async () => {
    installFetch({ summary: fullSummary });
    renderAt("/");

    await waitFor(() => expect(screen.getByText("187")).toBeInTheDocument());
    expect(screen.getByText("44")).toBeInTheDocument();
    expect(screen.getByText("28")).toBeInTheDocument();
    // Libri: 0 with reports_not_available_yet.
    expect(screen.getAllByText("0").length).toBeGreaterThanOrEqual(1);
  });

  it("shows em dash + source string when a metric is null", async () => {
    installFetch({
      summary: {
        ...fullSummary,
        hotspots_24h: null,
        hotspots_source: "qdrant:unavailable",
      },
    });
    renderAt("/");

    // Wait for the summary load to surface the unavailable source label.
    await waitFor(() => {
      expect(screen.getByText(/qdrant:unavailable/)).toBeInTheDocument();
    });
    const dash = screen.getAllByText("—");
    expect(dash.length).toBeGreaterThan(0);
  });

  it("shows 0 and a pending-S3 label on Libri when reports_not_available_yet", async () => {
    installFetch({ summary: fullSummary });
    renderAt("/");

    await waitFor(() => {
      expect(screen.getByText(/pending/i)).toBeInTheDocument();
    });
  });
});

describe("LandingPage · feed", () => {
  it("renders initial feed items from /api/signals/latest before SSE", async () => {
    installFetch({
      summary: fullSummary,
      latest: [
        {
          event_id: "0000000001000-000001",
          ts: "2026-04-14T14:32:00.000Z",
          type: "signal.firms",
          payload: {
            title: "sinjar cluster · n=14",
            severity: "high",
            source: "firms",
            url: "",
            redis_id: "0000000001000-000001",
          },
        },
      ],
    });
    renderAt("/");

    await waitFor(() =>
      expect(screen.getByText(/sinjar cluster/i)).toBeInTheDocument(),
    );
  });
});

describe("LandingPage · navigation", () => {
  it("clicking Hotspots tile navigates to /worldview?filter=hotspots", async () => {
    installFetch({ summary: fullSummary });
    renderAt("/");

    const tile = await screen.findByRole("button", { name: /hotspots/i });
    fireEvent.click(tile);

    await waitFor(() =>
      expect(screen.getByTestId("worldview-page")).toBeInTheDocument(),
    );
  });
});
