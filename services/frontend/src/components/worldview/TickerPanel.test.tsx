import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { TickerPanel } from "./TickerPanel";

vi.mock("../../hooks/useSignalFeed", () => ({
  useSignalFeed: () => ({
    status: "live",
    items: [
      {
        event_id: "01ABC",
        ts: "2026-04-21T14:32:00Z",
        type: "signal.firms",
        payload: { title: "sinjar cluster", severity: "high", source: "firms", url: "" },
      },
      {
        event_id: "01ABD",
        ts: "2026-04-21T13:58:00Z",
        type: "signal.gdelt",
        payload: { title: "tu-95 barents", severity: "medium", source: "gdelt", url: "" },
      },
    ],
    lastEventId: "01ABD",
  }),
}));

describe("TickerPanel", () => {
  it("renders live signal items using Landing's feed hook", () => {
    render(<TickerPanel />);
    expect(screen.getByRole("region", { name: /Ticker/i })).toBeInTheDocument();
    expect(screen.getByText(/sinjar cluster/i)).toBeInTheDocument();
    expect(screen.getByText(/tu-95 barents/i)).toBeInTheDocument();
  });
});
