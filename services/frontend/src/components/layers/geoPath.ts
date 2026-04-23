import * as Cesium from "cesium";

function isValidLonLat(coord: number[] | undefined): coord is [number, number] {
  if (!coord || coord.length < 2) return false;
  const [lon, lat] = coord;
  return Number.isFinite(lon) && Number.isFinite(lat);
}

/**
 * Densify a lon/lat path along the ellipsoid geodesic.
 *
 * PolylineCollection connects Cartesian points as straight 3D segments (chords).
 * Sparse points can dip below terrain/globe and appear broken. This helper inserts
 * intermediate geodesic points so rendered lines stay visually continuous.
 */
export function densifyLonLatSegment(segment: number[][], maxStepKm = 80): number[][] {
  if (segment.length < 2) {
    return segment.filter(isValidLonLat).map(([lon, lat]) => [lon, lat]);
  }

  const densified: number[][] = [];

  for (let i = 0; i < segment.length - 1; i += 1) {
    const start = segment[i];
    const end = segment[i + 1];
    if (!isValidLonLat(start) || !isValidLonLat(end)) continue;

    const startCarto = Cesium.Cartographic.fromDegrees(start[0], start[1]);
    const endCarto = Cesium.Cartographic.fromDegrees(end[0], end[1]);

    const geodesic = new Cesium.EllipsoidGeodesic(startCarto, endCarto);
    const distance = geodesic.surfaceDistance;
    const stepMeters = Math.max(1, maxStepKm) * 1000;
    const steps = Number.isFinite(distance)
      ? Math.max(1, Math.ceil(distance / stepMeters))
      : 1;

    if (densified.length === 0) {
      densified.push([start[0], start[1]]);
    }

    for (let j = 1; j <= steps; j += 1) {
      const fraction = j / steps;
      const carto = geodesic.interpolateUsingFraction(fraction);
      densified.push([
        Cesium.Math.toDegrees(carto.longitude),
        Cesium.Math.toDegrees(carto.latitude),
      ]);
    }
  }

  if (densified.length === 0) {
    return segment.filter(isValidLonLat).map(([lon, lat]) => [lon, lat]);
  }

  return densified;
}
