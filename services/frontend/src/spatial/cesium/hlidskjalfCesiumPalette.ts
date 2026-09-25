import * as Cesium from "cesium";

/** Muted atlas tints distinguish neighboring provinces, not risk or allegiance. */
export function regionalFillColor(scopeKey: string): Cesium.Color {
  const colors = ["#b49b68", "#608d9e", "#81966d", "#91768e", "#ae7c63", "#658f8a"];
  let hash = 0;
  for (const character of scopeKey) hash = (hash * 31 + character.charCodeAt(0)) >>> 0;
  return Cesium.Color.fromCssColorString(colors[hash % colors.length] ?? colors[0]!).withAlpha(0.2);
}

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
