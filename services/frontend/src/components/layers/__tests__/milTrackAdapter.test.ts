import { describe, it, expect } from "vitest";
import { fromLiveTrack, fromWindowTrack, positionAtTime } from "../milTrackAdapter";
import type { AircraftTrack, WindowTrackSample } from "../../../types";

const live: AircraftTrack = {
  icao24: "abc", callsign: "F1", type_code: "RQ4", military_branch: "USAF",
  registration: null,
  points: [
    { lat: 0, lon: 0, altitude_m: 100, speed_ms: 10, heading: 90, timestamp: 1000 },
    { lat: 10, lon: 0, altitude_m: 200, speed_ms: 10, heading: 90, timestamp: 2000 },
  ],
};

const win: WindowTrackSample = {
  kind: "track", id: "xyz", icao24: "xyz", callsign: null, type_code: null,
  military_branch: "RUAF", registration: null,
  points: [{ ts_ms: 5_000_000, lat: 1, lon: 1 }],
};

describe("milTrackAdapter", () => {
  it("live timestamp seconds -> ts_ms milliseconds", () => {
    const r = fromLiveTrack(live);
    expect(r.icao24).toBe("abc");
    expect(r.points[0]!.ts_ms).toBe(1_000_000);
  });

  it("window track maps id->icao24 and keeps ts_ms", () => {
    const r = fromWindowTrack(win);
    expect(r.icao24).toBe("xyz");
    expect(r.points[0]!.ts_ms).toBe(5_000_000);
  });

  it("before first point -> null (no marker)", () => {
    const r = fromLiveTrack(live);
    expect(positionAtTime(r.points, 500_000)).toBeNull();
  });

  it("between points -> linear interpolation", () => {
    const r = fromLiveTrack(live);
    const pos = positionAtTime(r.points, 1_500_000)!;
    expect(pos.lat).toBeCloseTo(5);
    expect(pos.alt).toBeCloseTo(150);
  });

  it("after last point -> clamp to last, no dead reckoning", () => {
    const r = fromLiveTrack(live);
    const pos = positionAtTime(r.points, 9_000_000)!;
    expect(pos.lat).toBe(10);
  });
});
