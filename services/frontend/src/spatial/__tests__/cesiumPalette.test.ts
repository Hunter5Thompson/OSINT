import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import * as Cesium from "cesium";
import { describe, expect, it } from "vitest";

import {
  spatialScopeColor,
  regionalFillColor,
  type SpatialScopeColorRole,
} from "../cesium/hlidskjalfCesiumPalette";

const expectedRoles = [
  "activeFill",
  "scopeOutline",
  "childPickSurface",
] as const satisfies readonly SpatialScopeColorRole[];

describe("Hlíðskjalf Cesium scope palette", () => {
  it("gives provinces stable differentiated fills without changing world pick surfaces", () => {
    expect(regionalFillColor("admin1:iso3166-2:DE-BY")).toEqual(regionalFillColor("admin1:iso3166-2:DE-BY"));
    expect(regionalFillColor("admin1:iso3166-2:DE-BY")).not.toEqual(regionalFillColor("admin1:iso3166-2:DE-BE"));
    expect(regionalFillColor("admin1:iso3166-2:DE-BY").alpha).toBeGreaterThan(0.1);
  });
  it("exposes exactly the three typed scope primitive color roles", () => {
    expect(Object.keys(spatialScopeColor)).toEqual(expectedRoles);
    expect(spatialScopeColor.activeFill()).toEqual(
      Cesium.Color.fromCssColorString("#3a5a78").withAlpha(0.09),
    );
    expect(spatialScopeColor.scopeOutline()).toEqual(
      Cesium.Color.fromCssColorString("#958a7a").withAlpha(0.72),
    );
    expect(spatialScopeColor.childPickSurface()).toEqual(
      Cesium.Color.fromCssColorString("#3a5a78").withAlpha(0.035),
    );
  });

  it("keeps canonical CSS tokens at the boundary and hard colors out of the builder", () => {
    const css = readFileSync(
      resolve(process.cwd(), "src/theme/hlidskjalf.css"),
      "utf8",
    );
    const builder = readFileSync(
      resolve(process.cwd(), "src/spatial/cesium/buildScopePrimitives.ts"),
      "utf8",
    );

    expect(css).toMatch(/--steel:\s*#3a5a78;/i);
    expect(css).toMatch(/--stone:\s*#958a7a;/i);
    expect(builder).toContain("spatialScopeColor");
    expect(builder).not.toMatch(/#[0-9a-f]{6}/i);
  });
});
