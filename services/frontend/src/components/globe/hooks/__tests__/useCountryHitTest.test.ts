import { describe, expect, it } from "vitest";

import {
  buildCountryIndex,
  COUNTRY_INDEX_REJECTION_DIAGNOSTIC_LIMIT,
  hitTestCountry,
  type CountryFeature,
  type CountryIndexDiagnostic,
} from "../useCountryHitTest";

const fakeFeatures: CountryFeature[] = [
  {
    m49: "300",
    name: "Greece",
    geometry: {
      type: "Polygon",
      coordinates: [[[20, 35], [28, 35], [28, 41], [20, 41], [20, 35]]],
    },
  },
  {
    m49: "732",
    name: "W. Sahara",
    geometry: {
      type: "Polygon",
      coordinates: [[[-17, 21], [-9, 21], [-9, 27], [-17, 27], [-17, 21]]],
    },
  },
];

const topoIndex = { "300": "GRC", "732": null };
const countriesData = {
  GRC: { iso3: "GRC", m49: "300", capital: { name: "Athens", lat: 37.98, lon: 23.73 } },
};

describe("useCountryHitTest", () => {
  it("builds an rbush index", () => {
    const idx = buildCountryIndex(fakeFeatures);
    expect(idx).toBeTruthy();
  });

  it("hit on Greece point → returns iso3 + capital", () => {
    const idx = buildCountryIndex(fakeFeatures);
    const r = hitTestCountry(idx, fakeFeatures, topoIndex, countriesData, 23, 38);
    expect(r?.m49).toBe("300");
    expect(r?.iso3).toBe("GRC");
    expect(r?.capital?.name).toBe("Athens");
  });

  it("hit on W. Sahara point → m49 + name only, iso3 null, capital null", () => {
    const idx = buildCountryIndex(fakeFeatures);
    const r = hitTestCountry(idx, fakeFeatures, topoIndex, countriesData, -13, 24);
    expect(r?.m49).toBe("732");
    expect(r?.iso3).toBeNull();
    expect(r?.capital).toBeNull();
    expect(r?.name).toBe("W. Sahara");
  });

  it("ocean point → null", () => {
    const idx = buildCountryIndex(fakeFeatures);
    const r = hitTestCountry(idx, fakeFeatures, topoIndex, countriesData, 0, 0);
    expect(r).toBeNull();
  });

  it("prepares coordinate rings once instead of traversing GeoJSON on every click", () => {
    let coordinateReads = 0;
    const position = (longitude: number, latitude: number): GeoJSON.Position => {
      const value = [longitude, latitude];
      Object.defineProperty(value, 0, {
        configurable: true,
        get: () => {
          coordinateReads += 1;
          return longitude;
        },
      });
      Object.defineProperty(value, 1, {
        configurable: true,
        get: () => {
          coordinateReads += 1;
          return latitude;
        },
      });
      return value;
    };
    const features: CountryFeature[] = [{
      m49: "999",
      name: "Prepared",
      geometry: {
        type: "Polygon",
        coordinates: [[
          position(0, 0),
          position(10, 0),
          position(10, 10),
          position(0, 10),
          position(0, 0),
        ]],
      },
    }];
    const index = buildCountryIndex(features);
    expect(coordinateReads).toBeGreaterThan(0);
    coordinateReads = 0;

    expect(hitTestCountry(index, features, {}, {}, 5, 5)?.name).toBe("Prepared");
    expect(coordinateReads).toBe(0);
  });

  it("indexes a dateline feature with minimal spans and prunes Greenwich", () => {
    const features: CountryFeature[] = [{
      m49: "998",
      name: "Dateline",
      geometry: {
        type: "Polygon",
        coordinates: [[
          [179, -2],
          [-179, -2],
          [-179, 2],
          [179, 2],
          [179, -2],
        ]],
      },
    }];
    const index = buildCountryIndex(features);
    const spans = index.all()
      .map((node) => [node.minX, node.maxX])
      .sort((left, right) => left[0]! - right[0]!);

    expect(spans).toEqual([[-180, -179], [179, 180]]);
    expect(index.search({ minX: 0, minY: 0, maxX: 0, maxY: 0 })).toEqual([]);
    expect(hitTestCountry(index, features, {}, {}, 179.5, 0)?.name).toBe("Dateline");
    expect(hitTestCountry(index, features, {}, {}, -179.5, 0)?.name).toBe("Dateline");
    expect(hitTestCountry(index, features, {}, {}, 0, 0)).toBeNull();
  });

  it("preserves MultiPolygon hits on separate parts", () => {
    const features: CountryFeature[] = [{
      m49: "995",
      name: "Multipart",
      geometry: {
        type: "MultiPolygon",
        coordinates: [
          [[[0, 0], [2, 0], [2, 2], [0, 2], [0, 0]]],
          [[[10, 10], [12, 10], [12, 12], [10, 12], [10, 10]]],
        ],
      },
    }];
    const index = buildCountryIndex(features);

    expect(hitTestCountry(index, features, {}, {}, 1, 1)?.name).toBe("Multipart");
    expect(hitTestCountry(index, features, {}, {}, 11, 11)?.name).toBe("Multipart");
    expect(hitTestCountry(index, features, {}, {}, 6, 6)).toBeNull();
  });

  it("preserves the legacy inclusive result on outer and hole boundaries", () => {
    const features: CountryFeature[] = [{
      m49: "996",
      name: "Holed",
      geometry: {
        type: "Polygon",
        coordinates: [
          [[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]],
          [[3, 3], [3, 7], [7, 7], [7, 3], [3, 3]],
        ],
      },
    }];
    const index = buildCountryIndex(features);

    expect(hitTestCountry(index, features, {}, {}, 0, 5)?.name).toBe("Holed");
    expect(hitTestCountry(index, features, {}, {}, 3, 5)?.name).toBe("Holed");
    expect(hitTestCountry(index, features, {}, {}, 5, 5)).toBeNull();
  });

  it("fails closed without throwing when legacy geometry or click coordinates are invalid", () => {
    const invalidFeatures: CountryFeature[] = [{
      m49: "997",
      name: "Invalid",
      geometry: {
        type: "Polygon",
        coordinates: [[[0, 0], [1, 0], [Number.NaN, 1], [0, 0]]],
      },
    }];
    let index: ReturnType<typeof buildCountryIndex> | null = null;

    expect(() => {
      index = buildCountryIndex(invalidFeatures);
    }).not.toThrow();
    expect(index).not.toBeNull();
    expect(() => hitTestCountry(index!, invalidFeatures, {}, {}, 0.5, 0.5)).not.toThrow();
    expect(hitTestCountry(index!, invalidFeatures, {}, {}, 0.5, 0.5)).toBeNull();
    expect(hitTestCountry(index!, invalidFeatures, {}, {}, Number.NaN, 0)).toBeNull();
  });

  it("reports rejected features once, bounds payloads, and summarizes overflow", () => {
    expect(COUNTRY_INDEX_REJECTION_DIAGNOSTIC_LIMIT).toBe(10);
    const coordinateMarker = 987.654321;
    const invalidFeatures: CountryFeature[] = Array.from(
      { length: COUNTRY_INDEX_REJECTION_DIAGNOSTIC_LIMIT + 3 },
      (_, index) => ({
        m49: `secret-m49-${index}`,
        name: `secret-name-${index}`,
        geometry: {
          type: "Polygon" as const,
          coordinates: [[
            [0, 0],
            [1, 0],
            [coordinateMarker, 1],
            [0, 0],
          ]],
        },
      }),
    );
    const events: CountryIndexDiagnostic[] = [];

    const index = buildCountryIndex(invalidFeatures, {
      report: (event) => events.push(event),
    });

    expect(index.all()).toEqual([]);
    expect(events).toEqual([
      ...Array.from(
        { length: COUNTRY_INDEX_REJECTION_DIAGNOSTIC_LIMIT },
        (_, featureIndex) => ({
          code: "legacy_country_geometry_rejected" as const,
          featureIndex,
        }),
      ),
      {
        code: "legacy_country_geometry_rejections_suppressed",
        suppressedCount: 3,
      },
    ]);
    const serialized = JSON.stringify(events);
    expect(serialized).not.toContain("secret-name");
    expect(serialized).not.toContain("secret-m49");
    expect(serialized).not.toContain(String(coordinateMarker));
    expect(serialized).not.toContain("coordinates");
  });
});
