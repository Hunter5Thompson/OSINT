import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { decodeRegions, decodeSites, regionsInScope } from "../referenceData";

const read = (file: string): unknown => JSON.parse(readFileSync(`public/data/${file}.json`, "utf8"));
describe("reference atlas", () => {
  it("validates the shipped nuclear and curated military datasets", () => {
    expect(decodeSites(read("nuclear-sites"))).toHaveLength(195);
    const military = decodeSites(read("military-sites"));
    expect(military.filter((s) => s.kind === "icbmBases")).toHaveLength(3);
    expect(military.every((s) => s.coordinateSource && s.note.includes("reference"))).toBe(true);
  });
  it("rejects invalid coordinates and unsafe source links", () => {
    const site = decodeSites(read("nuclear-sites"))[0];
    expect(() => decodeSites([{ ...site, latitude: 91 }])).toThrow();
    expect(() => decodeSites([{ ...site, source: "javascript:alert(1)" }])).toThrow();
  });
  it("shows only capitals belonging to the selected country or region", () => {
    const regions = decodeRegions(read("region-profiles"));
    const germany = regionsInScope(regions, "country:DEU");
    expect(germany).toHaveLength(16);
    expect(germany.filter((r) => r.capital)).toHaveLength(16);
    const bavaria = regionsInScope(regions, "admin1:iso3166-2:DE-BY");
    expect(bavaria).toHaveLength(1);
    expect(bavaria[0]?.capital?.name).toBe("München");
    expect(regionsInScope(regions, "world")).toEqual([]);
  });
});
