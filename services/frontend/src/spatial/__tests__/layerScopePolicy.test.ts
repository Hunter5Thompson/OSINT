import { describe, expect, it } from "vitest";

import type { LayerVisibility } from "../../types";
import type { ContainmentSnapshot } from "../contracts";
import {
  LAYER_SPATIAL_CAPABILITIES,
  applyLayerSpatialPolicy,
  layerSpatialCapability,
  layerSpatialStatus,
} from "../layerScopePolicy";

const ALL_LAYER_KEYS = [
  "flights",
  "satellites",
  "earthquakes",
  "vessels",
  "cctv",
  "events",
  "cables",
  "pipelines",
  "countryBorders",
  "cityBuildings",
  "firmsHotspots",
  "milAircraft",
  "datacenters",
  "refineries",
  "eonet",
  "gdacs",
] as const satisfies readonly (keyof LayerVisibility)[];

const allEnabled = Object.fromEntries(
  ALL_LAYER_KEYS.map((layerId) => [layerId, true]),
) as unknown as LayerVisibility;

const readyContainment: ContainmentSnapshot = {
  phase: "ready",
  stateRevision: 2,
  contains: () => "inside",
};

describe("closed layer spatial capability matrix", () => {
  it("registers every runtime LayerVisibility key exactly once", () => {
    expect(Object.keys(LAYER_SPATIAL_CAPABILITIES).sort()).toEqual(
      [...ALL_LAYER_KEYS].sort(),
    );
  });

  it("keeps each behavior coupled to its support, precision, and stale claims", () => {
    for (const layerId of ALL_LAYER_KEYS) {
      const capability = layerSpatialCapability(layerId);
      expect(capability.layerId).toBe(layerId);

      switch (capability.behavior) {
        case "unsupported":
          expect(capability).toMatchObject({
            supportedKinds: ["world"],
            precision: "global",
            stalePolicy: "not-applicable",
            unsupportedBehavior: "hide",
          });
          break;
        case "global-context":
          expect(capability).toMatchObject({
            relation: "context",
            supportedKinds: ["world", "country", "admin1", "admin2"],
            precision: "global",
            stalePolicy: "not-applicable",
            unsupportedBehavior: "label-global-context",
          });
          break;
        case "scope-presentation":
          expect(capability).toMatchObject({
            relation: "context",
            supportedKinds: ["world", "country", "admin1", "admin2"],
            precision: "global",
            stalePolicy: "scope-presentation-generation",
            unsupportedBehavior: "label-scope-presentation",
          });
          break;
        case "strict":
          expect(capability).toMatchObject({
            relation: "occurs-in",
            supportedKinds: ["world", "country", "admin1", "admin2"],
            unsupportedBehavior: "hide",
          });
          if (capability.precision === "point-in-boundary") {
            expect(capability.stalePolicy).toBe("invalidate-on-semantic-commit");
          } else {
            expect(capability.precision).toBe("bbox-approximate");
            expect(capability.stalePolicy).toBe("response-scope-token");
          }
          break;
        case "dim-outside":
          expect.unreachable(`${layerId} has no accepted dim-outside contract`);
      }
    }
  });

  it("surfaces the declared relation in every runtime claim", () => {
    for (const layerId of ALL_LAYER_KEYS) {
      const capability = layerSpatialCapability(layerId);
      const status = layerSpatialStatus(layerId, "world", readyContainment);

      expect(status.title).toContain(capability.relation);
    }
  });

  it("selects only earthquakes for new strict client point containment", () => {
    expect(layerSpatialCapability("earthquakes")).toEqual({
      layerId: "earthquakes",
      relation: "occurs-in",
      behavior: "strict",
      supportedKinds: ["world", "country", "admin1", "admin2"],
      precision: "point-in-boundary",
      stalePolicy: "invalidate-on-semantic-commit",
      unsupportedBehavior: "hide",
    });
    expect(
      Object.values(LAYER_SPATIAL_CAPABILITIES)
        .filter((capability) => capability.precision === "point-in-boundary")
        .map((capability) => capability.layerId),
    ).toEqual(["earthquakes"]);
  });

  it("preserves the CHRONIK response-token path without claiming exact precision", () => {
    expect(layerSpatialCapability("events")).toEqual({
      layerId: "events",
      relation: "occurs-in",
      behavior: "strict",
      supportedKinds: ["world", "country", "admin1", "admin2"],
      precision: "bbox-approximate",
      stalePolicy: "response-scope-token",
      unsupportedBehavior: "hide",
    });
  });

  it("labels global context and scope presentation distinctly", () => {
    expect(layerSpatialCapability("satellites")).toMatchObject({
      relation: "context",
      behavior: "global-context",
      precision: "global",
      stalePolicy: "not-applicable",
      unsupportedBehavior: "label-global-context",
    });
    expect(layerSpatialCapability("cityBuildings")).toMatchObject({
      behavior: "global-context",
      unsupportedBehavior: "label-global-context",
    });
    expect(layerSpatialCapability("countryBorders")).toMatchObject({
      behavior: "scope-presentation",
      stalePolicy: "scope-presentation-generation",
      unsupportedBehavior: "label-scope-presentation",
    });
  });

  it.each([
    "flights",
    "vessels",
    "cctv",
    "cables",
    "pipelines",
    "firmsHotspots",
    "milAircraft",
    "datacenters",
    "refineries",
    "eonet",
    "gdacs",
  ] as const)("fails closed for unsupported non-global layer %s", (layerId) => {
    expect(layerSpatialCapability(layerId)).toMatchObject({
      behavior: "unsupported",
      supportedKinds: ["world"],
      unsupportedBehavior: "hide",
    });
    expect(layerSpatialStatus(layerId, "country", readyContainment)).toMatchObject({
      render: false,
      label: "unavailable in scope",
      tone: "unsupported",
    });
  });

  it("exposes containment lifecycle and context claims as compact UI status", () => {
    expect(layerSpatialStatus(
      "earthquakes",
      "country",
      { phase: "building", stateRevision: 3 },
    )).toMatchObject({ render: false, label: "scope building", tone: "loading" });
    expect(layerSpatialStatus(
      "earthquakes",
      "country",
      { phase: "unavailable", stateRevision: 3 },
    )).toMatchObject({ render: false, label: "scope unavailable", tone: "unavailable" });
    expect(layerSpatialStatus("earthquakes", "country", readyContainment)).toMatchObject({
      render: true,
      label: "strict · point boundary",
      tone: "strict",
    });
    expect(layerSpatialStatus("satellites", "admin1", readyContainment)).toMatchObject({
      render: true,
      label: "global context",
      tone: "global",
    });
    expect(layerSpatialStatus("countryBorders", "admin1", readyContainment)).toMatchObject({
      render: true,
      label: "scope presentation",
      tone: "presentation",
    });
  });

  it("applies the closed matrix without mutating the requested layer state", () => {
    const scoped = applyLayerSpatialPolicy(
      allEnabled,
      "country",
      readyContainment,
    );

    expect(scoped).not.toBe(allEnabled);
    expect(allEnabled.flights).toBe(true);
    expect(scoped).toMatchObject({
      flights: false,
      vessels: false,
      cables: false,
      earthquakes: true,
      events: true,
      satellites: true,
      countryBorders: true,
      cityBuildings: true,
    });
  });

  it("does not flash world-only data during initial deep-link hydration", () => {
    const hydrating = applyLayerSpatialPolicy(
      allEnabled,
      null,
      { phase: "unavailable", stateRevision: 0 },
    );

    expect(hydrating).toMatchObject({
      flights: false,
      earthquakes: false,
      events: false,
      countryBorders: false,
      satellites: true,
      cityBuildings: true,
    });
  });
});
