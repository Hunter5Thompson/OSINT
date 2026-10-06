import { afterEach, describe, expect, it, vi } from "vitest";
import { classifyAircraft, clearAircraftIconCache, getAircraftTypeIcon } from "../icons/aircraftIcons";
import type { AircraftIconType } from "../icons/aircraftIcons";

afterEach(() => { vi.restoreAllMocks(); clearAircraftIconCache(); });

describe("military aircraft classification (D10)", () => {
  it("prioritises known type codes", () => {
    expect(classifyAircraft("X1", true, "C17", 9000, 220)).toBe("transport_mil");
    expect(classifyAircraft("X1", true, "C30J", null, null)).toBe("transport_mil");
    expect(classifyAircraft("X1", true, "F16", 500, 80)).toBe("fighter");
    expect(classifyAircraft("X1", true, "EUFI", null, null)).toBe("fighter");
    expect(classifyAircraft("X1", true, "B52", null, null)).toBe("bomber");
    expect(classifyAircraft("X1", true, "H60", null, null)).toBe("helicopter");
  });
  it("lets a known type code beat a callsign heuristic", () => {
    expect(classifyAircraft("RCH123", true, "F16", 9000, 250)).toBe("fighter");
    expect(classifyAircraft("VIPER11", true, "C17", 9000, 220)).toBe("transport_mil");
  });
  it.each(["VIPER11", "RAPTOR1", "HAWK21", "COBRA3"])(
    "does not take %s alone as transport evidence",
    (callsign) => {
      expect(classifyAircraft(callsign, true, null, null, null)).toBe("military_unknown");
    },
  );
  it("keeps a neutral role for military aircraft without evidence", () => {
    expect(classifyAircraft("", true, null, null, null)).toBe("military_unknown");
    expect(classifyAircraft("UNK", true, null, 300, 60)).toBe("military_unknown"); // slow + low
    expect(classifyAircraft("UNK", true, "", 300, 60)).toBe("military_unknown");
  });
  it("still treats a fast and high unknown military contact as fighter-like", () => {
    expect(classifyAircraft("UNK", true, null, 9000, 250)).toBe("fighter");
  });
  it("never derives a military role for civilian traffic", () => {
    expect(classifyAircraft("RCH123", false, null, 9000, 250)).toBe("civilian");
    expect(classifyAircraft("DLH400", false, "A320", 10000, 230)).toBe("civilian");
  });
  it("renders military_unknown as a distinct, cached icon", () => {
    let n = 0;
    vi.spyOn(HTMLCanvasElement.prototype, "toDataURL").mockImplementation(() => `icon-${n++}`);
    const unknown = getAircraftTypeIcon("military_unknown" satisfies AircraftIconType, 90);
    expect(unknown).not.toBe(getAircraftTypeIcon("fighter", 90));
    expect(unknown).not.toBe(getAircraftTypeIcon("civilian", 90));
    expect(getAircraftTypeIcon("military_unknown", 90)).toBe(unknown);
  });
});
