import { describe, it, expect } from "vitest";
import { formatCoords } from "../coords";

describe("formatCoords", () => {
  it("renders N + E for positive coords", () => {
    expect(formatCoords([36.34, 41.87])).toBe("36.340N · 41.870E");
  });

  it("renders S + W for negative coords", () => {
    expect(formatCoords([-22.5, -47.6])).toBe("22.500S · 47.600W");
  });

  it("respects precision", () => {
    expect(formatCoords([10, 20], 1)).toBe("10.0N · 20.0E");
  });
});
