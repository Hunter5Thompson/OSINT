import { afterEach, describe, expect, it, vi } from "vitest";
import {
  UNKNOWN_ALTITUDE_PLACEMENT_M,
  extrapolateAircraft,
  formatAircraftAltitude,
  formatAircraftHeading,
  formatAircraftSpeed,
  formatAircraftVerticalRate,
  placementAltitudeM,
} from "../aircraftMeasurements";
import { classifyAircraft, clearAircraftIconCache, getAircraftTypeIcon } from "../icons/aircraftIcons";

afterEach(() => { vi.restoreAllMocks(); clearAircraftIconCache(); });

describe("aircraft measurement formatting (D02)", () => {
  it("never shows unknown altitude as a measured 0 m", () => {
    expect(formatAircraftAltitude(null, false)).toBe("unknown");
    expect(formatAircraftAltitude(null, true)).toBe("on ground");
    expect(formatAircraftAltitude(0, false)).toBe("0 m (FL0)");
    expect(formatAircraftAltitude(10668, false)).toBe("10,668 m (FL350)");
  });
  it("shows unknown speed and heading, keeps real zeros", () => {
    expect(formatAircraftSpeed(null)).toBe("unknown");
    expect(formatAircraftSpeed(0)).toBe("0 kts (0 km/h)");
    expect(formatAircraftSpeed(100)).toBe("194 kts (360 km/h)");
    expect(formatAircraftHeading(null)).toBe("unknown");
    expect(formatAircraftHeading(0)).toBe("0°");
    expect(formatAircraftHeading(270.4)).toBe("270°");
  });
  it("omits unknown or zero vertical rate, shows real climb and descent", () => {
    expect(formatAircraftVerticalRate(null)).toBeNull();
    expect(formatAircraftVerticalRate(0)).toBeNull();
    expect(formatAircraftVerticalRate(5.4)).toBe("+5 m/s");
    expect(formatAircraftVerticalRate(-3)).toBe("-3 m/s");
  });
});

describe("aircraft rendering placement (D02)", () => {
  it("uses a defined technical placement for unknown altitude, real values otherwise", () => {
    expect(placementAltitudeM(null)).toBe(UNKNOWN_ALTITUDE_PLACEMENT_M);
    expect(placementAltitudeM(0)).toBe(0);
    expect(placementAltitudeM(9000)).toBe(9000);
  });
  const base = { latitude: 10, longitude: 20, altitudeM: 5000, velocityMs: 200, headingDeg: 90, verticalRate: 10 };
  it("extrapolates only with known speed and heading", () => {
    const moved = extrapolateAircraft(base, 10);
    expect(moved.longitude).toBeGreaterThan(20);
    expect(moved.altitudeM).toBe(5100);
    expect(extrapolateAircraft({ ...base, velocityMs: null }, 10)).toMatchObject({ latitude: 10, longitude: 20 });
    expect(extrapolateAircraft({ ...base, headingDeg: null }, 10)).toMatchObject({ latitude: 10, longitude: 20 });
  });
  it("does not climb without a known vertical rate or altitude", () => {
    expect(extrapolateAircraft({ ...base, verticalRate: null }, 10).altitudeM).toBe(5000);
    expect(extrapolateAircraft({ ...base, altitudeM: null }, 10).altitudeM).toBe(UNKNOWN_ALTITUDE_PLACEMENT_M);
  });
  it("treats a real heading of 0 as north, not as unknown", () => {
    const moved = extrapolateAircraft({ ...base, headingDeg: 0 }, 10);
    expect(moved.latitude).toBeGreaterThan(10);
  });
});

describe("aircraft icons with unknown values (D02)", () => {
  it("derives no role from missing speed or altitude", () => {
    expect(classifyAircraft("TEST", false, null, null, null)).toBe("civilian");
    expect(classifyAircraft("TEST", true, null, null, null)).toBe("fighter");
  });
  it("renders a neutral icon for unknown heading, distinct from heading 0", () => {
    let n = 0;
    vi.spyOn(HTMLCanvasElement.prototype, "toDataURL").mockImplementation(() => `icon-${n++}`);
    const unknown = getAircraftTypeIcon("civilian", null);
    expect(unknown).not.toBe(getAircraftTypeIcon("civilian", 0));
    expect(getAircraftTypeIcon("civilian", null)).toBe(unknown);
  });
});
