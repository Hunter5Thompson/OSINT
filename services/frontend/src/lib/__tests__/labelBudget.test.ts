import { describe, it, expect } from "vitest";
import { GLOBE_ALTITUDE_M, LOCAL_ALTITUDE_M, bandForHeight } from "../lod";
import {
  DENSITY_STOPS,
  VIEW_SCALE_BUDGETS,
  labelViewScaleForAltitude,
  canonicalizeDensity,
  profileForDensity,
  defaultDensityForProfile,
  labelBudgetFor,
  type LabelViewScale,
  type DensityStop,
  type DensityProfile,
} from "../labelBudget";

describe("labelViewScaleForAltitude", () => {
  it("classifies five altitude scales", () => {
    expect(labelViewScaleForAltitude(10_000)).toBe("street");
    expect(labelViewScaleForAltitude(100_000)).toBe("city");
    expect(labelViewScaleForAltitude(500_000)).toBe("metro");
    expect(labelViewScaleForAltitude(3_000_000)).toBe("regional");
    expect(labelViewScaleForAltitude(15_000_000)).toBe("global");
  });

  it("maps non-finite altitude to global and negative to street", () => {
    expect(labelViewScaleForAltitude(Number.NaN)).toBe("global");
    expect(labelViewScaleForAltitude(Number.POSITIVE_INFINITY)).toBe("global");
    expect(labelViewScaleForAltitude(Number.NEGATIVE_INFINITY)).toBe("global");
    expect(labelViewScaleForAltitude(-1)).toBe("street");
  });

  it("aligns metro/regional/global boundaries with lod.ts bands", () => {
    expect(labelViewScaleForAltitude(LOCAL_ALTITUDE_M - 1)).toBe("metro");
    expect(bandForHeight(LOCAL_ALTITUDE_M - 1)).toBe("LOCAL");

    expect(labelViewScaleForAltitude(LOCAL_ALTITUDE_M)).toBe("regional");
    expect(bandForHeight(LOCAL_ALTITUDE_M)).toBe("REGIONAL");

    expect(labelViewScaleForAltitude(GLOBE_ALTITUDE_M - 1)).toBe("regional");
    expect(bandForHeight(GLOBE_ALTITUDE_M - 1)).toBe("REGIONAL");

    expect(labelViewScaleForAltitude(GLOBE_ALTITUDE_M)).toBe("global");
    expect(bandForHeight(GLOBE_ALTITUDE_M)).toBe("GLOBE");
  });
});

describe("canonicalizeDensity", () => {
  it("snaps continuous density to the nearest DensityStop", () => {
    expect(canonicalizeDensity(0)).toBe(0);
    expect(canonicalizeDensity(10)).toBe(0);
    expect(canonicalizeDensity(13)).toBe(25);
    expect(canonicalizeDensity(25)).toBe(25);
    expect(canonicalizeDensity(40)).toBe(50);
    expect(canonicalizeDensity(74)).toBe(50);
    expect(canonicalizeDensity(80)).toBe(75);
    expect(canonicalizeDensity(95)).toBe(100);
  });

  it("clamps out-of-range and falls back for non-finite", () => {
    expect(canonicalizeDensity(-50)).toBe(0);
    expect(canonicalizeDensity(500)).toBe(100);
    expect(canonicalizeDensity(Number.NaN)).toBe(50);
    expect(canonicalizeDensity(Number.NaN, 75)).toBe(75);
  });
});

describe("profileForDensity / defaultDensityForProfile", () => {
  it("maps density stops to SPARSE / BALANCED / DENSE profiles", () => {
    expect(profileForDensity(0)).toBe("SPARSE");
    expect(profileForDensity(25)).toBe("SPARSE");
    expect(profileForDensity(50)).toBe("BALANCED");
    expect(profileForDensity(75)).toBe("DENSE");
    expect(profileForDensity(100)).toBe("DENSE");
  });

  it("round-trips defaultDensityForProfile through profileForDensity", () => {
    const profiles: DensityProfile[] = ["SPARSE", "BALANCED", "DENSE"];
    for (const profile of profiles) {
      expect(profileForDensity(defaultDensityForProfile(profile))).toBe(profile);
    }
  });
});

describe("VIEW_SCALE_BUDGETS", () => {
  const scales: LabelViewScale[] = ["street", "city", "metro", "regional", "global"];

  it("exposes frozen density stops", () => {
    expect([...DENSITY_STOPS]).toEqual([0, 25, 50, 75, 100]);
  });

  it("has integer cells, increasing density within scale, non-increasing pullback, worst < 250", () => {
    for (const scale of scales) {
      const row = VIEW_SCALE_BUDGETS[scale];
      let prev = -Infinity;
      for (const stop of DENSITY_STOPS) {
        const value = row[stop];
        expect(Number.isInteger(value)).toBe(true);
        expect(value).toBeGreaterThan(prev);
        prev = value;
        expect(value).toBeLessThan(250);
      }
    }

    for (const stop of DENSITY_STOPS) {
      expect(VIEW_SCALE_BUDGETS.street[stop]).toBeGreaterThanOrEqual(VIEW_SCALE_BUDGETS.city[stop]);
      expect(VIEW_SCALE_BUDGETS.city[stop]).toBeGreaterThanOrEqual(VIEW_SCALE_BUDGETS.metro[stop]);
      expect(VIEW_SCALE_BUDGETS.metro[stop]).toBeGreaterThanOrEqual(VIEW_SCALE_BUDGETS.regional[stop]);
      expect(VIEW_SCALE_BUDGETS.regional[stop]).toBeGreaterThanOrEqual(VIEW_SCALE_BUDGETS.global[stop]);
    }
  });
});

describe("labelBudgetFor", () => {
  it("looks up VIEW_SCALE_BUDGETS by altitude scale and canonical density", () => {
    expect(labelBudgetFor(10_000, 50)).toBe(VIEW_SCALE_BUDGETS.street[50]);
    expect(labelBudgetFor(100_000, 50)).toBe(VIEW_SCALE_BUDGETS.city[50]);
    expect(labelBudgetFor(500_000, 50)).toBe(VIEW_SCALE_BUDGETS.metro[50]);
    expect(labelBudgetFor(3_000_000, 50)).toBe(VIEW_SCALE_BUDGETS.regional[50]);
    expect(labelBudgetFor(15_000_000, 50)).toBe(VIEW_SCALE_BUDGETS.global[50]);

    const stop: DensityStop = 25;
    expect(labelBudgetFor(10_000, 13)).toBe(VIEW_SCALE_BUDGETS.street[stop]);
  });
});
