import { describe, it, expect } from "vitest";
import {
  bandForHeight,
  inViewBounds,
  selectVisible,
  bulkScaleByDistance,
  bulkTranslucencyByDistance,
  GLOBE_ALTITUDE_M,
  LOCAL_ALTITUDE_M,
  ORBIT_LOD_ALTITUDE_M,
} from "../lod";

describe("altitude constants", () => {
  it("expose stable altitude thresholds", () => {
    expect(GLOBE_ALTITUDE_M).toBe(8_000_000);
    expect(LOCAL_ALTITUDE_M).toBe(1_000_000);
    expect(ORBIT_LOD_ALTITUDE_M).toBe(45_000_000);
    expect(bandForHeight(ORBIT_LOD_ALTITUDE_M - 1)).toBe("GLOBE");
  });
});

describe("bandForHeight", () => {
  it("classifies GLOBE / REGIONAL / LOCAL by camera height", () => {
    expect(bandForHeight(GLOBE_ALTITUDE_M + 1)).toBe("GLOBE");
    expect(bandForHeight(GLOBE_ALTITUDE_M)).toBe("GLOBE");
    expect(bandForHeight(3_000_000)).toBe("REGIONAL");
    expect(bandForHeight(LOCAL_ALTITUDE_M)).toBe("REGIONAL");
    expect(bandForHeight(LOCAL_ALTITUDE_M - 1)).toBe("LOCAL");
  });
});

describe("inViewBounds", () => {
  const box = { south: 40, north: 50, west: 30, east: 50 };
  it("keeps points inside, rejects points outside", () => {
    expect(inViewBounds(37, 45, box)).toBe(true);
    expect(inViewBounds(60, 45, box)).toBe(false);
    expect(inViewBounds(37, 60, box)).toBe(false);
  });
  it("returns true when bounds is null (globe fills view)", () => {
    expect(inViewBounds(123, -80, null)).toBe(true);
  });
  it("handles anti-meridian wrap (west > east)", () => {
    const wrap = { south: -10, north: 10, west: 170, east: -170 };
    expect(inViewBounds(175, 0, wrap)).toBe(true);
    expect(inViewBounds(-175, 0, wrap)).toBe(true);
    expect(inViewBounds(0, 0, wrap)).toBe(false);
  });
  it("treats west === east as a zero-width strip", () => {
    const strip = { south: 0, north: 10, west: 5, east: 5 };
    expect(inViewBounds(5, 5, strip)).toBe(true);
    expect(inViewBounds(6, 5, strip)).toBe(false);
  });
});

describe("selectVisible", () => {
  const ll = (p: { lon: number; lat: number }) => [p.lon, p.lat] as const;
  const box = { south: 0, north: 10, west: 0, east: 10 };
  it("culls out-of-view items", () => {
    const items = [
      { lon: 5, lat: 5, id: "in" },
      { lon: 50, lat: 50, id: "out" },
    ];
    expect(selectVisible(items, ll, box, { cap: 100 }).map((i) => i.id)).toEqual(["in"]);
  });
  it("caps to N keeping the highest rank", () => {
    const items = [
      { lon: 1, lat: 1, r: 1 },
      { lon: 2, lat: 2, r: 9 },
      { lon: 3, lat: 3, r: 5 },
    ];
    const r = selectVisible(items, ll, box, { cap: 2, rank: (i) => i.r });
    expect(r.map((i) => i.r)).toEqual([9, 5]);
  });
  it("skips items whose accessor returns null", () => {
    const items = [{ lon: 5, lat: 5 }, { lon: null, lat: null }];
    const r = selectVisible(
      items,
      (i) => (i.lon == null ? null : ([i.lon, i.lat] as const)),
      box,
      { cap: 10 },
    );
    expect(r.length).toBe(1);
  });
  it("returns empty for a non-positive cap", () => {
    const items = [{ lon: 5, lat: 5 }];
    expect(selectVisible(items, ll, box, { cap: 0 })).toEqual([]);
    expect(selectVisible(items, ll, box, { cap: -3 })).toEqual([]);
  });
});

describe("bulk distance attenuation factories", () => {
  it("return the canonical NearFarScalar defaults", () => {
    const s = bulkScaleByDistance();
    expect([s.near, s.nearValue, s.far, s.farValue]).toEqual([100_000, 1.0, 12_000_000, 0.45]);
    const t = bulkTranslucencyByDistance();
    expect([t.near, t.nearValue, t.far, t.farValue]).toEqual([100_000, 1.0, 14_000_000, 0.35]);
  });
});
