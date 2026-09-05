import { describe, expect, it } from "vitest";
import { layersForMode, selectedWorkspaceMode } from "./workspaceModes";

describe("Worldview workspace modes", () => {
  it("keeps context visible while separating movement from the situation overview", () => {
    const overview = layersForMode("overview");
    expect(overview.events).toBe(true);
    expect(overview.countryBorders).toBe(true);
    expect(overview.flights).toBe(false);
    expect(overview.satellites).toBe(false);
    expect(overview.firmsHotspots).toBe(false);
    const movement = layersForMode("movement");
    expect(movement.flights).toBe(true);
    expect(movement.vessels).toBe(true);
    expect(movement.milAircraft).toBe(true);
    expect(movement.events).toBe(false);
    expect(selectedWorkspaceMode(movement)).toBe("movement");
  });
  it("marks manual layer changes as custom and returns fresh, independent presets", () => {
    const infrastructure = layersForMode("infrastructure");
    expect(infrastructure.cables).toBe(true);
    expect(infrastructure.refineries).toBe(true);
    infrastructure.flights = true;
    expect(selectedWorkspaceMode(infrastructure)).toBeNull();
    expect(layersForMode("infrastructure").flights).toBe(false);
  });
});
