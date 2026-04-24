import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import type { RefineryGeoJSON, RefineryProperties } from "../types";

const data = JSON.parse(
  readFileSync(resolve(process.cwd(), "public/data/refineries.geojson"), "utf8"),
) as RefineryGeoJSON;

function featureByName(name: string) {
  const feature = data.features.find((item) => item.properties.name === name);
  if (!feature) throw new Error(`Missing refinery feature: ${name}`);
  return feature;
}

function expectCoordinates(name: string, lon: number, lat: number) {
  const feature = featureByName(name);
  expect(feature.geometry.coordinates[0]).toBeCloseTo(lon, 4);
  expect(feature.geometry.coordinates[1]).toBeCloseTo(lat, 4);
}

function expectFacilityPhoto(name: string) {
  const props = featureByName(name).properties as RefineryProperties;
  expect(props.image_url).toMatch(/^https:\/\//);
  expect(props.image_url).not.toMatch(/logo|\.svg/i);
}

describe("refineries GeoJSON", () => {
  it("pins corrected WGS84 coordinates for refinery sites that were previously misplaced", () => {
    expectCoordinates("Jamnagar Refinery", 69.868889, 22.348056);
    expectCoordinates("Ras Tanura Refinery", 50.09207, 26.70243);
    expectCoordinates("Yanbu Refinery", 38.29769, 23.944);
    expectCoordinates("S-Oil Onsan Refinery", 129.36163, 35.47791);
    expectCoordinates("Hyundai Oilbank Daesan", 126.414958, 37.004491);
    expectCoordinates("JXTG Negishi Refinery", 139.639188, 35.41245);
    expectCoordinates("CNOOC Huizhou Refinery", 114.47072, 22.740397);
    expectCoordinates("Shell Stanlow Refinery", -2.84492, 53.27379);
    expectCoordinates("TotalEnergies Donges Refinery", -2.07209, 47.31425);
    expectCoordinates("BP Lingen Refinery", 7.30787, 52.5612);
    expectCoordinates("BP Gelsenkirchen Refinery", 7.023428, 51.606164);
    expectCoordinates("PCK Schwedt Refinery", 14.231504, 53.093356);
    expectCoordinates("TotalEnergies Leuna Refinery", 11.99325, 51.28805);
    expectCoordinates("Shell Hamburg Refinery", 9.97071, 53.4866);
    expectCoordinates("Preem Gothenburg Refinery", 11.88376, 57.70412);
    expectCoordinates("Preem Lysekil Refinery", 11.42427, 58.34458);
    expectCoordinates("Equinor Mongstad Refinery", 5.0314, 60.8102);
    expectCoordinates("Shell Rhineland Refinery (Wesseling)", 7.004722, 50.817855);
    expectCoordinates("Phillips 66 Humber Refinery", -0.24234, 53.63254);
    expectCoordinates("TotalEnergies Gonfreville Refinery", 0.24086, 49.4868);
    expectCoordinates("Saras Sarroch Refinery", 9.0184, 39.07734);
    expectCoordinates("Repsol A Coruna Refinery", -8.4453, 43.35264);
    expectCoordinates("Repsol Puertollano Refinery", -4.04945, 38.6731);
    expectCoordinates("TUPRAS Kirikkale Refinery", 33.46447, 39.74329);
    expectCoordinates("TUPRAS Batman Refinery", 41.14123, 37.87263);
  });

  it("includes LNG terminals and chemical plants with detail metadata for the inspector", () => {
    const expected = [
      "Sabine Pass LNG Terminal",
      "Golden Pass LNG Terminal",
      "Gate LNG Terminal",
      "BASF Ludwigshafen Verbund Site",
      "Dow Texas Operations",
      "CNOOC Huizhou Petrochemical Plant",
    ];

    for (const name of expected) {
      const props = featureByName(name).properties as RefineryProperties;
      expect(props.facility_type).toBeTruthy();
      expect(props.specs?.length).toBeGreaterThan(0);
      expect(props.source_url).toMatch(/^https:\/\//);
      expect(props.image_url).toMatch(/^https:\/\//);
    }
  });

  it("uses facility photos rather than logo placeholders for corrected energy anchors", () => {
    const expected = [
      "S-Oil Onsan Refinery",
      "Hyundai Oilbank Daesan",
      "JXTG Negishi Refinery",
      "CNOOC Huizhou Refinery",
      "Shell Stanlow Refinery",
      "TotalEnergies Donges Refinery",
      "BP Lingen Refinery",
      "BP Gelsenkirchen Refinery",
      "PCK Schwedt Refinery",
      "TotalEnergies Leuna Refinery",
      "Shell Hamburg Refinery",
      "Preem Gothenburg Refinery",
      "Preem Lysekil Refinery",
      "Equinor Mongstad Refinery",
      "Shell Rhineland Refinery (Wesseling)",
      "Phillips 66 Humber Refinery",
      "TotalEnergies Gonfreville Refinery",
      "Saras Sarroch Refinery",
      "Repsol A Coruna Refinery",
      "Repsol Puertollano Refinery",
      "TUPRAS Kirikkale Refinery",
      "TUPRAS Batman Refinery",
      "Gate LNG Terminal",
      "CNOOC Huizhou Petrochemical Plant",
    ];

    for (const name of expected) {
      expectFacilityPhoto(name);
    }
  });
});
