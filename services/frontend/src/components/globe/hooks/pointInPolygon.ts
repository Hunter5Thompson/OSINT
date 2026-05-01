type Ring = number[][];

function ringContains(ring: Ring, lon: number, lat: number): boolean {
  let inside = false;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const xi = ring[i]![0]!, yi = ring[i]![1]!;
    const xj = ring[j]![0]!, yj = ring[j]![1]!;
    const intersect =
      yi > lat !== yj > lat &&
      lon < ((xj - xi) * (lat - yi)) / (yj - yi) + xi;
    if (intersect) inside = !inside;
  }
  return inside;
}

export function polygonContains(
  polygon: GeoJSON.Polygon | GeoJSON.MultiPolygon,
  lon: number,
  lat: number
): boolean {
  const polygons =
    polygon.type === "Polygon" ? [polygon.coordinates] : polygon.coordinates;
  for (const poly of polygons) {
    const [outer, ...holes] = poly as Ring[];
    if (!ringContains(outer!, lon, lat)) continue;
    if (holes.some((h) => ringContains(h!, lon, lat))) continue;
    return true;
  }
  return false;
}
