type Ring = number[][];
type Polygon = Ring[];
type MultiPolygonCoords = Polygon[];

function ringContains(ring: Ring, lon: number, lat: number): boolean {
  let inside = false;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const curr = ring[i];
    const prev = ring[j];
    if (!curr || !prev || curr.length < 2 || prev.length < 2) continue;

    const xi = curr[0] as number;
    const yi = curr[1] as number;
    const xj = prev[0] as number;
    const yj = prev[1] as number;

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
  const polygons: MultiPolygonCoords =
    polygon.type === "Polygon" ? [polygon.coordinates] : polygon.coordinates;
  for (const poly of polygons) {
    const [outer, ...holes] = poly;
    if (!outer || !ringContains(outer, lon, lat)) continue;
    if (holes.some((h) => h && ringContains(h, lon, lat))) continue;
    return true;
  }
  return false;
}
