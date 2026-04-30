import { describe, it, expect } from "vitest";
import { polygonContains } from "../../components/globe/hooks/pointInPolygon";

const square: GeoJSON.Polygon = {
  type: "Polygon",
  coordinates: [[[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]]],
};

const squareWithHole: GeoJSON.Polygon = {
  type: "Polygon",
  coordinates: [
    [[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]],
    [[3, 3], [3, 7], [7, 7], [7, 3], [3, 3]],
  ],
};

const usaLike: GeoJSON.MultiPolygon = {
  type: "MultiPolygon",
  coordinates: [
    [[[-125, 25], [-66, 25], [-66, 49], [-125, 49], [-125, 25]]],   // contiguous
    [[[-160, 19], [-154, 19], [-154, 23], [-160, 23], [-160, 19]]], // hawaii-ish
    [[[-170, 60], [-140, 60], [-140, 72], [-170, 72], [-170, 60]]], // alaska-ish
  ],
};

describe("polygonContains", () => {
  it("inside simple polygon → true", () => {
    expect(polygonContains(square, 5, 5)).toBe(true);
  });
  it("outside simple polygon → false", () => {
    expect(polygonContains(square, 11, 5)).toBe(false);
  });
  it("inside hole → false", () => {
    expect(polygonContains(squareWithHole, 5, 5)).toBe(false);
  });
  it("inside ring but outside hole → true", () => {
    expect(polygonContains(squareWithHole, 1, 1)).toBe(true);
  });
  it("MultiPolygon contiguous USA point → true", () => {
    expect(polygonContains(usaLike, -100, 40)).toBe(true);
  });
  it("MultiPolygon Hawaii point → true", () => {
    expect(polygonContains(usaLike, -157, 21)).toBe(true);
  });
  it("MultiPolygon Alaska point → true", () => {
    expect(polygonContains(usaLike, -150, 65)).toBe(true);
  });
  it("MultiPolygon ocean point → false", () => {
    expect(polygonContains(usaLike, -130, 40)).toBe(false);
  });
});
