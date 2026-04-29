/**
 * Format a (lat, lon) pair as "DDD.dddH · DDD.dddH" using N/S and E/W
 * suffixes. Used by IncidentBar, IncidentToast, and the Theatre callout.
 *
 * @param coords [lat, lon] tuple in decimal degrees
 * @param precision number of fractional digits (default 3)
 */
export function formatCoords(
  coords: readonly [number, number],
  precision = 3,
): string {
  const [lat, lon] = coords;
  const latH = lat >= 0 ? "N" : "S";
  const lonH = lon >= 0 ? "E" : "W";
  return `${Math.abs(lat).toFixed(precision)}${latH} · ${Math.abs(lon).toFixed(precision)}${lonH}`;
}
