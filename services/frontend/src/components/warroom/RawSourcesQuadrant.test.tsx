import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { RawSourcesQuadrant } from "./RawSourcesQuadrant";
import type { Incident } from "../../types/incident";

const inc: Incident = {
  id: "inc-001",
  kind: "firms.cluster",
  title: "x",
  severity: "high",
  coords: [0, 0],
  location: "-",
  status: "open",
  trigger_ts: "2026-04-25T10:00:00Z",
  closed_ts: null,
  sources: ["firms·14 det.", "ucdp·#44821", "gdelt·4 art.", "ais·anomaly"],
  layer_hints: [],
  timeline: [],
};

describe("RawSourcesQuadrant", () => {
  it("renders one card per source up to 4", () => {
    render(<RawSourcesQuadrant incident={inc} onPromote={vi.fn()} onSilence={vi.fn()} onAsk={vi.fn()} />);
    expect(screen.getAllByTestId("source-card")).toHaveLength(4);
  });

  it("calls onPromote when the promote action is clicked", () => {
    const onPromote = vi.fn();
    render(<RawSourcesQuadrant incident={inc} onPromote={onPromote} onSilence={vi.fn()} onAsk={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: /promote to dossier/i }));
    expect(onPromote).toHaveBeenCalled();
  });
});
