import { describe, expect, it } from "vitest";
import {
  LAYER_SPATIAL_CAPABILITIES,
  layerSpatialCapability,
} from "../layerScopePolicy";

describe("layer spatial capability matrix", () => {
  it("declares CHRONIK events as strict occurs-in with honest bbox precision", () => {
    expect(layerSpatialCapability("chronik-events")).toMatchObject({
      relation: "occurs-in",
      behavior: "strict",
      precision: "bbox-approximate",
      supportedKinds: ["world", "country", "admin1", "admin2"],
    });
  });

  it("keeps track intersection distinct from point containment", () => {
    expect(layerSpatialCapability("aircraft-vessel-tracks")).toMatchObject({
      relation: "intersects",
      behavior: "dim-outside",
      precision: "bbox-approximate",
    });
    expect(layerSpatialCapability("facilities")).toMatchObject({
      relation: "occurs-in",
      behavior: "strict",
      precision: "point-in-boundary",
    });
  });

  it("distinguishes global context and unsupported geometry from filtered layers", () => {
    expect(layerSpatialCapability("satellites")).toMatchObject({
      relation: "context",
      behavior: "global-context",
      precision: "global",
    });
    expect(layerSpatialCapability("terrain-imagery-3d").behavior).toBe("global-context");
    expect(layerSpatialCapability("cables-pipelines")).toMatchObject({
      relation: "intersects",
      behavior: "unsupported",
    });
  });

  it("registers every initial Spec-06 layer class exactly once", () => {
    expect(Object.keys(LAYER_SPATIAL_CAPABILITIES).sort()).toEqual([
      "aircraft-vessel-tracks",
      "cables-pipelines",
      "chronik-events",
      "country-admin-borders",
      "facilities",
      "geo-events-hotspots-earthquakes",
      "satellites",
      "terrain-imagery-3d",
    ]);
  });
});
