import { describe, expect, it } from "vitest";
import {
  canProjectVesselMotion,
  formatVesselCourse,
  formatVesselSpeed,
} from "../vesselMeasurements";
import { getShipTypeIcon } from "../icons/shipIcons";

describe("vessel measurements (D01)", () => {
  it("shows unknown instead of a fake 0 for null values", () => {
    expect(formatVesselSpeed(null)).toBe("unknown");
    expect(formatVesselCourse(null)).toBe("unknown");
  });
  it("keeps real zeros", () => {
    expect(formatVesselSpeed(0)).toBe("0.0 kts");
    expect(formatVesselCourse(0)).toBe("0°");
  });
  it("formats measured values", () => {
    expect(formatVesselSpeed(12.34)).toBe("12.3 kts");
    expect(formatVesselCourse(359.9)).toBe("0°");
    expect(formatVesselCourse(90.4)).toBe("90°");
  });
  it("projects motion only with both a moving speed and a known course", () => {
    expect(canProjectVesselMotion(12, 90)).toBe(true);
    expect(canProjectVesselMotion(12, 0)).toBe(true);
    expect(canProjectVesselMotion(null, 90)).toBe(false);
    expect(canProjectVesselMotion(12, null)).toBe(false);
    expect(canProjectVesselMotion(0.2, 90)).toBe(false);
    expect(canProjectVesselMotion(0, 90)).toBe(false);
  });
  it("renders a neutral, direction-less icon for unknown course", () => {
    const unknown = getShipTypeIcon("cargo", null);
    expect(unknown).not.toBe(getShipTypeIcon("cargo", 0));
    expect(getShipTypeIcon("cargo", null)).toBe(unknown);
  });
});
