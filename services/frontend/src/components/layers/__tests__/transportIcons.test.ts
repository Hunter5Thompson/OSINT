import { afterEach, describe, expect, it, vi } from "vitest";
import { classifyAircraft, clearAircraftIconCache, getAircraftTypeIcon } from "../icons/aircraftIcons";
import { getShipTypeIcon } from "../icons/shipIcons";

afterEach(() => { vi.restoreAllMocks(); clearAircraftIconCache(); });

describe("transport glyphs", () => {
  it("renders aircraft at double resolution and shares heading buckets", () => {
    const encode = vi.spyOn(HTMLCanvasElement.prototype, "toDataURL").mockImplementation(function (this: HTMLCanvasElement) {
      return `${this.width}x${this.height}`;
    });
    expect(getAircraftTypeIcon("civilian", 0)).toBe("48x48");
    expect(getAircraftTypeIcon("civilian", 360)).toBe("48x48");
    expect(encode).toHaveBeenCalledTimes(1);
  });
  it("renders vessels at double resolution without multiplying heading textures", () => {
    const icon = getShipTypeIcon("cargo", -5);
    expect(icon.width).toBe(40);
    expect(icon.height).toBe(40);
    expect(getShipTypeIcon("cargo", 355)).toBe(icon);
  });
  it("uses an explicit bomber type before speed heuristics", () => {
    expect(classifyAircraft("TEST", true, "B52", 10000, 250)).toBe("bomber");
  });
});
