import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import * as Cesium from "cesium";
import { describe, expect, it } from "vitest";

import {
  spatialScopeColor,
  type SpatialScopeColorRole,
} from "../cesium/hlidskjalfCesiumPalette";

const expectedRoles = [
  "activeFill",
  "scopeOutline",
  "childPickSurface",
] as const satisfies readonly SpatialScopeColorRole[];

describe("Hlíðskjalf Cesium scope palette", () => {
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
