import * as Cesium from "cesium";

export type SpatialScopeColorRole =
  | "activeFill"
  | "scopeOutline"
  | "childPickSurface";

type SpatialScopeColorPalette = Readonly<
  Record<SpatialScopeColorRole, () => Cesium.Color>
>;

function tokenColor(
  token: "--steel" | "--stone",
  fallback: string,
  alpha: number,
): Cesium.Color {
  const cssValue = typeof document === "undefined"
    ? ""
    : getComputedStyle(document.documentElement).getPropertyValue(token).trim();
  return Cesium.Color.fromCssColorString(cssValue || fallback).withAlpha(alpha);
}

/** Cesium-ready roles backed by the canonical Hlíðskjalf CSS palette. */
export const spatialScopeColor = Object.freeze({
  activeFill: () => tokenColor("--steel", "#3a5a78", 0.09),
  scopeOutline: () => tokenColor("--stone", "#958a7a", 0.72),
  childPickSurface: () => tokenColor("--steel", "#3a5a78", 0.035),
}) satisfies SpatialScopeColorPalette;
