import { afterEach, describe, expect, it, vi } from "vitest";
import * as satellite from "satellite.js";
import { Cartesian3 } from "cesium";
import gp from "../../../../tests/fixtures/satellites/celestrak-100651.json";
import reference from "../../../../tests/fixtures/satellites/reference-vectors.json";
import { createSatelliteRecord, decodeOrbitSnapshot, propagateSatellite, SatelliteRecordCache } from "./satelliteOrbit";

vi.mock("satellite.js", { spy: true });

const row = {
  norad_id: gp.NORAD_CAT_ID, name: gp.OBJECT_NAME, category: "active",
  inclination_deg: Math.round(gp.INCLINATION * 100) / 100,
  period_min: 1440 / gp.MEAN_MOTION, operator_country: null, satellite_type: "unknown",
  orbit: { format: "omm", elements: { ...gp, EPOCH: gp.EPOCH + "Z",
    CENTER_NAME: "EARTH", REF_FRAME: "TEME", TIME_SYSTEM: "UTC", MEAN_ELEMENT_THEORY: "SGP4" } },
};
const snapshot = {
  schema_version: 1, fetched_at: "2026-10-09T23:06:11.823566Z", satellites: [row],
  coverage: { completeness: "complete", groups: [{ group: "active", status: "ok",
    accepted_records: 1, rejected_invalid: 0, rejected_unsupported: 0,
    rejections: [], failure_code: null }] },
};

describe("versioned satellite reader", () => {
  it("keeps six-digit ID, microsecond epoch and source fetch time", () => {
    const result = decodeOrbitSnapshot(snapshot);
    expect(result.fetched_at).toBe(snapshot.fetched_at);
    expect(result.satellites).toEqual([row]);
    expect(result.client_rejections).toEqual([]);
    const record = createSatelliteRecord(result.satellites[0]!);
    expect(record?.satnum).toBe("100651");
  });

  it.each([null, [], { ...snapshot, schema_version: 2 },
    { ...snapshot, fetched_at: "2026-10-09" },
    { ...snapshot, fetched_at: "2026-02-30T23:06:11Z" },
    { ...snapshot, coverage: { completeness: "complete", groups: [] } },
  ])("rejects malformed envelope %j", (value) => {
    expect(() => decodeOrbitSnapshot(value)).toThrow();
  });

  it("isolates a broken neighbor and makes client rejection visible", () => {
    const result = decodeOrbitSnapshot({ ...snapshot,
      coverage: { ...snapshot.coverage, groups: snapshot.coverage.groups.map(group => ({ ...group, accepted_records: 2 })) },
      satellites: [row, {
      ...row, orbit: { format: "omm", elements: { ...row.orbit.elements, MEAN_MOTION: 0 } },
    }] });
    expect(result.satellites).toEqual([row]);
    expect(result.client_rejections).toEqual([{ index: 1, reason: expect.any(String) }]);
  });

  it("rejects an entirely broken non-empty satellite set", () => {
    expect(() => decodeOrbitSnapshot({ ...snapshot, satellites: [{ ...row, norad_id: 1 }] })).toThrow();
  });

  it("accepts a legitimate empty snapshot without inventing an update time", () => {
    const value = structuredClone(snapshot);
    value.satellites = [];
    value.coverage.groups[0]!.accepted_records = 0;
    expect(decodeOrbitSnapshot(value).satellites).toEqual([]);
  });

  it("does not accept complete coverage with contradictory group failures", () => {
    const value = { ...snapshot, coverage: { ...snapshot.coverage,
      groups: snapshot.coverage.groups.map(group => ({ ...group, status: "failed", failure_code: "transport" })) } };
    expect(() => decodeOrbitSnapshot(value)).toThrow();
  });

  it("rejects source coverage claiming no accepted records for a nonempty set", () => {
    const value = { ...snapshot, coverage: { ...snapshot.coverage,
      groups: snapshot.coverage.groups.map(group => ({ ...group, accepted_records: 0 })) } };
    expect(() => decodeOrbitSnapshot(value)).toThrow();
  });

  it("preserves the valid legacy TLE variant without converting it to OMM", () => {
    const fixture = reference.cases[0]!;
    const value = { ...snapshot, satellites: [{ ...row, norad_id: fixture.norad_id,
      name: fixture.name, orbit: fixture.orbit }] };
    const result = decodeOrbitSnapshot(value);
    expect(result.satellites[0]!.orbit).toEqual(fixture.orbit);
    expect(createSatelliteRecord(result.satellites[0]!)?.satnum).toBe("25544");
  });

  it.each(["checksum", "id", "frame", "nan"])("rejects damaged orbit input: %s", (damage) => {
    const value = structuredClone(row);
    if (damage === "id") value.norad_id = 1;
    else if (damage === "frame") value.orbit.elements.REF_FRAME = "J2000";
    else if (damage === "nan") value.orbit.elements.BSTAR = NaN;
    if (damage === "checksum") {
      const fixture = reference.cases[0]!.orbit;
      expect(() => decodeOrbitSnapshot({ ...snapshot, satellites: [{ ...row, norad_id: 25544,
        orbit: { format: "tle", line1: fixture.line1!.slice(0, -1) + "0", line2: fixture.line2 } }] })).toThrow();
    } else {
      expect(() => decodeOrbitSnapshot({ ...snapshot, satellites: [value] })).toThrow();
    }
  });
});

describe("orbit propagation and element cache", () => {
  afterEach(() => vi.resetAllMocks());

  it("propagates the independent reference and converts km to Cesium meters", () => {
    const record = createSatelliteRecord(decodeOrbitSnapshot(snapshot).satellites[0]!)!;
    const vector = reference.cases[1]!.vectors[0]!;
    const date = new Date(vector.utc);
    const result = propagateSatellite(record, date);
    expect(result).not.toBeNull();
    if (!result) throw new Error("No solution");
    expect(Math.hypot(
      result.position_teme_km.x - vector.position_teme_km[0]!,
      result.position_teme_km.y - vector.position_teme_km[1]!,
      result.position_teme_km.z - vector.position_teme_km[2]!,
    )).toBeLessThanOrEqual(reference.reference.position_tolerance_km);
    const rotated = satellite.eciToEcf(result.position_teme_km, satellite.gstime(date));
    const cesium = Cartesian3.fromDegrees(result.longitude_deg, result.latitude_deg, result.altitude_m);
    expect(Cartesian3.distance(cesium, new Cartesian3(rotated.x * 1000, rotated.y * 1000, rotated.z * 1000))).toBeLessThan(0.01);
  });

  it("isolates null propagation and permits the next valid evaluation", () => {
    const record = createSatelliteRecord(decodeOrbitSnapshot(snapshot).satellites[0]!)!;
    const date = new Date(reference.cases[1]!.vectors[0]!.utc);
    vi.mocked(satellite.propagate).mockReturnValueOnce(null);
    expect(propagateSatellite(record, date)).toBeNull();
    expect(propagateSatellite(record, date)).not.toBeNull();
  });

  it("rejects an invalid evaluation date before calling the propagator", () => {
    const record = createSatelliteRecord(decodeOrbitSnapshot(snapshot).satellites[0]!)!;
    const spy = vi.mocked(satellite.propagate);
    expect(propagateSatellite(record, new Date(NaN))).toBeNull();
    expect(spy).not.toHaveBeenCalled();
  });

  it("initializes once per element set and releases superseded datasets", () => {
    const value = decodeOrbitSnapshot(snapshot).satellites[0]!;
    const spy = vi.mocked(satellite.json2satrec);
    const cache = new SatelliteRecordCache();
    const record = cache.get(value);
    expect(record).not.toBeNull();
    expect(cache.get({ ...value, name: "New display metadata" })).toBe(record);
    expect(spy).toHaveBeenCalledTimes(1);
    cache.retain([]);
    expect(cache.get(value)).not.toBe(record);
    expect(spy).toHaveBeenCalledTimes(2);
  });

  it("preserves S classification in the domain while initializing the math", () => {
    const result = decodeOrbitSnapshot({ ...snapshot, satellites: [{ ...row,
      orbit: { format: "omm", elements: { ...row.orbit.elements, CLASSIFICATION_TYPE: "S" } } }] });
    expect(result.satellites[0]!.orbit).toMatchObject({ elements: { CLASSIFICATION_TYPE: "S" } });
    expect(createSatelliteRecord(result.satellites[0]!)?.satnum).toBe("100651");
  });
});
