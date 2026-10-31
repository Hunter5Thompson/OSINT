import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { OrbitSnapshot } from "../../types/satelliteOrbit";
import { SatelliteSourceStatus } from "./SatelliteSourceStatus";

const snapshot: OrbitSnapshot = {
  schema_version: 1, fetched_at: "2026-10-09T23:06:11.823566Z", satellites: [],
  client_rejections: [], coverage: { completeness: "partial", groups: [
    { group: "active", status: "ok", accepted_records: 0, rejected_invalid: 0, rejected_unsupported: 0, rejections: [], failure_code: null },
    { group: "military", status: "failed", accepted_records: 0, rejected_invalid: 0, rejected_unsupported: 0, rejections: [], failure_code: "transport" },
  ] },
};

describe("Satellite source visibility", () => {
  it("shows configured coverage and UTC source fetch time", () => {
    render(<SatelliteSourceStatus snapshot={snapshot} loading={false} error={null} />);
    expect(screen.getByRole("status")).toHaveTextContent("Teilabdeckung");
    expect(screen.getByRole("status")).toHaveTextContent("1/2 Gruppen");
    expect(screen.getByText(/2026-10-09T23:06:11.823566Z/)).toBeInTheDocument();
  });

  it("shows a fetch failure while retaining the previous source time", () => {
    render(<SatelliteSourceStatus snapshot={snapshot} loading={false} error="Network unavailable" />);
    expect(screen.getByRole("status")).toHaveTextContent("Abruf fehlgeschlagen");
    expect(screen.getByRole("status")).toHaveTextContent("Vorheriger Quellstand");
  });

  it("distinguishes an empty valid snapshot from unavailable data", () => {
    const complete = { ...snapshot, coverage: { completeness: "complete" as const, groups: snapshot.coverage.groups.slice(0, 1) } };
    render(<SatelliteSourceStatus snapshot={complete} loading={false} error={null} />);
    expect(screen.getByRole("status")).toHaveTextContent("0 Satelliten");
    expect(screen.getByRole("status")).toHaveTextContent("1/1 Gruppen");
  });
});
