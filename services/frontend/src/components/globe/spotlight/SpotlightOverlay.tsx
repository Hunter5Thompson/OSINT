import { useEffect } from "react";
import * as Cesium from "cesium";
import { useSpotlight, type CircleTarget, type CountryTarget } from "./SpotlightContext";

interface Props {
  viewer: Cesium.Viewer | null;
}

const CIRCLE_FRAGMENT = `
  uniform vec4 color;
  uniform float alpha;
  uniform float falloff;
  czm_material czm_getMaterial(czm_materialInput m) {
    czm_material material = czm_getDefaultMaterial(m);
    float d = distance(m.st, vec2(0.5));
    // Center (d=0) → w=1 (warm), edge (d≥0.5) → w=0.
    float w = 1.0 - smoothstep(falloff * 0.5, 0.5, d);
    material.diffuse = color.rgb;
    material.alpha = color.a * w * alpha;
    return material;
  }
`;

const COUNTRY_FRAGMENT = `
  uniform vec4 color;
  uniform float alpha;
  czm_material czm_getMaterial(czm_materialInput m) {
    czm_material material = czm_getDefaultMaterial(m);
    material.diffuse = color.rgb;
    material.alpha = color.a * alpha;
    return material;
  }
`;

// Tokens are read from CSS custom properties so the Spotlight palette stays
// in sync with hlidskjalf.css (no hardcoded hex / RGB tuples).
function tokenColor(name: string, fallback: string, alpha: number): Cesium.Color {
  const css =
    typeof window !== "undefined"
      ? getComputedStyle(document.documentElement).getPropertyValue(name).trim() || fallback
      : fallback;
  return Cesium.Color.fromCssColorString(css).withAlpha(alpha);
}

const REDUCED = typeof window !== "undefined" && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
const FADE_IN_MS = REDUCED ? 120 : 320;
const FADE_OUT_MS = REDUCED ? 120 : 200;

export function SpotlightOverlay({ viewer }: Props) {
  const { focusTarget } = useSpotlight();

  useEffect(() => {
    if (!viewer || viewer.isDestroyed() || !focusTarget) return;
    if (focusTarget.kind !== "circle") return;
    return mountCircle(viewer, focusTarget);
  }, [viewer, focusTarget]);

  useEffect(() => {
    if (!viewer || viewer.isDestroyed() || !focusTarget) return;
    if (focusTarget.kind !== "country") return;
    return mountCountry(viewer, focusTarget);
  }, [viewer, focusTarget]);

  return null;
}

function mountCircle(viewer: Cesium.Viewer, target: CircleTarget): () => void {
  const radiusMeters = degreesToMeters(target.radius);
  const center = Cesium.Cartesian3.fromDegrees(target.center.lon, target.center.lat);
  const amber = tokenColor("--amber", "#c4813a", 0.6);
  const material = new Cesium.Material({
    fabric: {
      type: "OdinSpotlightCircle",
      uniforms: { color: amber, alpha: 0.0, falloff: 0.85 },
      source: CIRCLE_FRAGMENT,
    },
    translucent: true,
  });
  const primitive = new Cesium.GroundPrimitive({
    geometryInstances: new Cesium.GeometryInstance({
      geometry: new Cesium.EllipseGeometry({ center, semiMajorAxis: radiusMeters, semiMinorAxis: radiusMeters }),
    }),
    appearance: new Cesium.MaterialAppearance({ material, flat: true }),
    classificationType: Cesium.ClassificationType.TERRAIN,
    asynchronous: true,
  });
  viewer.scene.primitives.add(primitive);

  const start = performance.now();
  const listener = () => {
    const t = performance.now() - start;
    material.uniforms.alpha = Math.min(1, t / FADE_IN_MS);
  };
  viewer.scene.preUpdate.addEventListener(listener);

  return () => {
    if (viewer.isDestroyed()) return;
    fadeOutAndRemove(viewer, material, primitive, listener);
  };
}

function mountCountry(viewer: Cesium.Viewer, target: CountryTarget): () => void {
  const polygons = target.polygon.type === "Polygon" ? [target.polygon.coordinates] : target.polygon.coordinates;
  const instances = polygons.map((rings) => {
    const ringsArr = rings as number[][][];
    const [outerRing, ...holeRings] = ringsArr;
    const outerPositions = outerRing!.map(([lon, lat]) => Cesium.Cartesian3.fromDegrees(lon!, lat!));
    const holes = holeRings.map(
      (hole) =>
        new Cesium.PolygonHierarchy(
          hole.map(([lon, lat]) => Cesium.Cartesian3.fromDegrees(lon!, lat!))
        )
    );
    return new Cesium.GeometryInstance({
      geometry: new Cesium.PolygonGeometry({
        // Cesium PolygonHierarchy(positions, holes[]) — interior rings are
        // carved out (lakes, enclaves), matching pointInPolygon's hole-aware
        // hit-test semantics from Task 4.
        polygonHierarchy: new Cesium.PolygonHierarchy(outerPositions, holes),
        granularity: Cesium.Math.RADIANS_PER_DEGREE * 2,
      }),
    });
  });
  const countryColor = tokenColor("--amber", "#c4813a", 0.35);
  const material = new Cesium.Material({
    fabric: {
      type: "OdinSpotlightCountry",
      uniforms: { color: countryColor, alpha: 0.0 },
      source: COUNTRY_FRAGMENT,
    },
    translucent: true,
  });
  const primitive = new Cesium.GroundPrimitive({
    geometryInstances: instances,
    appearance: new Cesium.MaterialAppearance({ material, flat: true }),
    classificationType: Cesium.ClassificationType.TERRAIN,
    asynchronous: true,
  });
  viewer.scene.primitives.add(primitive);

  const start = performance.now();
  const listener = () => {
    const t = performance.now() - start;
    material.uniforms.alpha = Math.min(1, t / FADE_IN_MS);
  };
  viewer.scene.preUpdate.addEventListener(listener);

  return () => {
    if (viewer.isDestroyed()) return;
    fadeOutAndRemove(viewer, material, primitive, listener);
  };
}

function fadeOutAndRemove(
  viewer: Cesium.Viewer,
  material: Cesium.Material,
  primitive: Cesium.GroundPrimitive,
  inListener: () => void
): void {
  viewer.scene.preUpdate.removeEventListener(inListener);
  const start = performance.now();
  const startAlpha = material.uniforms.alpha as number;
  const fade = () => {
    const t = performance.now() - start;
    const a = Math.max(0, startAlpha * (1 - t / FADE_OUT_MS));
    material.uniforms.alpha = a;
    if (a <= 0) {
      viewer.scene.preUpdate.removeEventListener(fade);
      viewer.scene.primitives.remove(primitive);
    }
  };
  viewer.scene.preUpdate.addEventListener(fade);
}

function degreesToMeters(deg: number): number {
  // 1° lat ≈ 111 km
  return deg * 111_000;
}
