import { describe, it, expect } from "vitest";
import { buildCountryIndex, hitTestCountry, type CountryFeature } from "../useCountryHitTest";

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
});
