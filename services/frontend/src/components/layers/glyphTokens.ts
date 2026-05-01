import * as Cesium from "cesium";

function cssVar(name: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

export const glyphColor = {
  sentinel: () => Cesium.Color.fromCssColorString(cssVar("--sentinel") || "#b85a2a"),
  amber:    () => Cesium.Color.fromCssColorString(cssVar("--amber")    || "#c4813a"),
  stone:    () => Cesium.Color.fromCssColorString(cssVar("--stone")    || "#958a7a"),
  sage:     () => Cesium.Color.fromCssColorString(cssVar("--sage")     || "#7a8a68"),
} as const;
