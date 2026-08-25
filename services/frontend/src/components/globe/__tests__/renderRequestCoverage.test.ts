import { describe, it, expect } from "vitest";
import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";

const SRC = join(process.cwd(), "src");
const LAYER_DIR = join(SRC, "components/layers");

/**
 * A file mutates the scene if it adds primitives (scene.primitives OR
 * scene.groundPrimitives), adds a post-process stage, flips show, empties a
 * collection, or drives preUpdate.
 *
 * `postProcessStages\.add` and `groundPrimitives` are listed explicitly: the
 * first takes a bare identifier so `\.add\(\{` never matches it, and the second
 * only matches `primitives\.add` by luck of substring — a reader tightening
 * that alternative to `scene\.primitives\.add` would silently drop
 * CountryBorders.tsx from the population. Do not tighten it.
 */
const MUTATES =
  /primitives\.add|postProcessStages\.add|\.show\s*=|\.add\(\{|removeAll\(\)|preUpdate/;

function sceneMutatingLayers(): string[] {
  return readdirSync(LAYER_DIR)
    .filter((f) => f.endsWith(".tsx") && !f.includes(".test."))
    .filter((f) => MUTATES.test(readFileSync(join(LAYER_DIR, f), "utf8")))
    .sort();
}

const NON_LAYER_SITES: readonly string[] = [
  "components/globe/GlobeViewer.tsx",
  "components/globe/spotlight/CapitalPulse.tsx",
  "components/globe/spotlight/SpotlightOverlay.tsx",
  "components/globe/visual-layers/CountryBorders.tsx",
  "components/globe/visual-layers/Graticule.tsx",
  "components/shaders/shaderUtils.ts",
  "spatial/cesium/CesiumSpatialScopeAdapter.ts",
  "spatial/cesium/buildScopePrimitives.ts",
];

const ANIMATOR_HOLDS: ReadonlyArray<readonly [string, string]> = [
  ["components/layers/FIRMSLayer.tsx", "firms-pulse"],
  ["components/layers/EarthquakeLayer.tsx", "earthquake-pulse"],
  ["components/layers/EventLayer.tsx", "event-pulse"],
  ["components/layers/FlightLayer.tsx", "flight-interpolation"],
  ["components/layers/MilAircraftLayer.tsx", "milair-tick"],
  ["components/globe/spotlight/SpotlightOverlay.tsx", "spotlight-fade-in"],
  ["components/globe/spotlight/SpotlightOverlay.tsx", "spotlight-fade-out"],
  ["components/globe/spotlight/CapitalPulse.tsx", "capital-pulse"],
];

describe("explicit-render coverage", () => {
  it("pins the scene-mutating layer population", () => {
    expect(sceneMutatingLayers()).toEqual([
      "CCTVLayer.tsx", "CableLayer.tsx", "DatacenterLayer.tsx", "EONETLayer.tsx",
      "EarthquakeLayer.tsx", "EventLayer.tsx", "FIRMSLayer.tsx", "FlightLayer.tsx",
      "GDACSLayer.tsx", "MilAircraftLayer.tsx", "PipelineLayer.tsx", "ReconLayer.tsx",
      "RefineryLayer.tsx", "SatelliteLayer.tsx", "ShipLayer.tsx",
    ]);
  });

  it.each(sceneMutatingLayers())("layers/%s requests a render frame", (file) => {
    expect(readFileSync(join(LAYER_DIR, file), "utf8")).toContain("governorRequestRender");
  });

  it.each(NON_LAYER_SITES)("%s requests a render frame", (rel) => {
    expect(readFileSync(join(SRC, rel), "utf8")).toContain("governorRequestRender");
  });

  it("finds no scene-mutating file outside the known set", () => {
    const walk = (dir: string, acc: string[] = []): string[] => {
      for (const entry of readdirSync(dir, { withFileTypes: true })) {
        const abs = join(dir, entry.name);
        if (entry.isDirectory()) {
          if (entry.name !== "__tests__") walk(abs, acc);
        } else if (/\.tsx?$/.test(entry.name) && !entry.name.includes(".test.")) {
          acc.push(abs);
        }
      }
      return acc;
    };
    const known = new Set([
      ...sceneMutatingLayers().map((f) => join(LAYER_DIR, f)),
      ...NON_LAYER_SITES.map((r) => join(SRC, r)),
      join(SRC, "components/globe/GoogleTiles.tsx"),
    ]);
    const unexpected = walk(SRC)
      .filter((abs) => MUTATES.test(readFileSync(abs, "utf8")))
      .filter((abs) => !known.has(abs))
      .map((abs) => abs.slice(SRC.length + 1));
    expect(unexpected).toEqual([]);
  });

  it.each(ANIMATOR_HOLDS)("%s balances its %s hold", (rel, ownerId) => {
    const src = readFileSync(join(SRC, rel), "utf8");
    const holds = src.split(`holdContinuousRender("${ownerId}")`).length - 1;
    const releases = src.split(`releaseContinuousRender("${ownerId}")`).length - 1;
    expect(holds).toBeGreaterThan(0);
    expect(releases).toBeGreaterThanOrEqual(holds);
  });

  it("gates the mil-air tick on visibility so idle is reachable at all", () => {
    const src = readFileSync(join(LAYER_DIR, "MilAircraftLayer.tsx"), "utf8");
    expect(src.slice(src.indexOf("viewer.clock.onTick") - 600)).toMatch(/if\s*\(!visible\)/);
  });
});
