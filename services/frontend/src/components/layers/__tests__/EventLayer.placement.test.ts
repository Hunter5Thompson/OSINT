import { describe, expect, it } from "vitest";
import { buildPlacements } from "../EventLayer";
import type { IntelEvent } from "../../../types";

function mkEvent(id: string, lat: number | null, lon: number | null): IntelEvent {
  return {
    id,
    title: `Event ${id}`,
    codebook_type: "military.airstrike",
    severity: "medium",
    timestamp: null,
    location_name: null,
    country: null,
    lat,
    lon,
  };
}

describe("buildPlacements", () => {
  it("keeps single events at original coordinates", () => {
    const placements = buildPlacements([
      mkEvent("a", 52.5, 13.4),
      mkEvent("b", 40.7, -74.0),
    ]);

    expect(placements).toHaveLength(2);
    expect(placements[0]?.stackSize).toBe(1);
    expect(placements[0]?.stackIndex).toBe(0);
    expect(placements[0]?.renderLat).toBeCloseTo(52.5, 5);
    expect(placements[0]?.renderLon).toBeCloseTo(13.4, 5);
  });

  it("spreads events in the same bucket to avoid overlap", () => {
    const placements = buildPlacements([
      mkEvent("a", 10, 20),
      mkEvent("b", 10, 20),
      mkEvent("c", 10, 20),
    ]);

    expect(placements).toHaveLength(3);
    expect(placements.every((p) => p.stackSize === 3)).toBe(true);

    const uniqueCoords = new Set(
      placements.map((p) => `${p.renderLat.toFixed(5)}:${p.renderLon.toFixed(5)}`),
    );
    expect(uniqueCoords.size).toBe(3);
  });

  it("ignores events without valid coordinates", () => {
    const placements = buildPlacements([
      mkEvent("a", null, 20),
      mkEvent("b", 10, null),
      mkEvent("c", null, null),
      mkEvent("d", 51.5, -0.12),
    ]);

    expect(placements).toHaveLength(1);
    expect(placements[0]?.event.id).toBe("d");
  });
});
