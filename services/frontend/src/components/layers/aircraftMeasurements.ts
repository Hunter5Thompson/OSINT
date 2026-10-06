/** Aircraft measurements are nullable: null means "unknown", never 0 or "now". */

export const UNKNOWN_ALTITUDE_PLACEMENT_M = 0;

const MS_TO_KNOTS = 1.944;
const MS_TO_KMH = 3.6;
const EARTH_RADIUS_M = 6_378_137;

/** Renderer-only placement. Details must still show "unknown", never this value. */
export function placementAltitudeM(altitudeM: number | null): number {
  return altitudeM ?? UNKNOWN_ALTITUDE_PLACEMENT_M;
}

export function formatAircraftAltitude(altitudeM: number | null, onGround: boolean): string {
  if (altitudeM === null) return onGround ? "on ground" : "unknown";
  return `${Math.round(altitudeM).toLocaleString("en-US")} m (FL${Math.round(altitudeM / 30.48)})`;
}

export function formatAircraftSpeed(velocityMs: number | null): string {
  if (velocityMs === null) return "unknown";
  return `${Math.round(velocityMs * MS_TO_KNOTS)} kts (${Math.round(velocityMs * MS_TO_KMH)} km/h)`;
}

export function formatAircraftHeading(headingDeg: number | null): string {
  return headingDeg === null ? "unknown" : `${Math.round(headingDeg) % 360}°`;
}

export function formatAircraftVerticalRate(verticalRate: number | null): string | null {
  if (verticalRate === null || Math.round(verticalRate) === 0) return null;
  return `${verticalRate > 0 ? "+" : ""}${Math.round(verticalRate)} m/s`;
}

function wrapLongitude(deg: number): number {
  return ((((deg + 180) % 360) + 360) % 360) - 180;
}

export interface AircraftKinematics {
  latitude: number;
  longitude: number;
  altitudeM: number | null;
  velocityMs: number | null;
  headingDeg: number | null;
  verticalRate: number | null;
}

export interface AircraftPlacement {
  latitude: number;
  longitude: number;
  altitudeM: number;
}

/** Dead reckoning that only moves along measured values. */
export function extrapolateAircraft(state: AircraftKinematics, elapsedSeconds: number): AircraftPlacement {
  const baseAltitude = placementAltitudeM(state.altitudeM);
  const canMove = state.velocityMs !== null && state.headingDeg !== null;
  const canClimb = state.altitudeM !== null && state.verticalRate !== null;
  const altitudeM = canClimb
    ? Math.max(0, baseAltitude + (state.verticalRate ?? 0) * elapsedSeconds)
    : baseAltitude;
  if (!canMove) return { latitude: state.latitude, longitude: state.longitude, altitudeM };

  const distanceM = Math.max(0, state.velocityMs ?? 0) * elapsedSeconds;
  const headingRad = ((state.headingDeg ?? 0) * Math.PI) / 180;
  const latRad = (state.latitude * Math.PI) / 180;
  const lonRad = (state.longitude * Math.PI) / 180;
  const angularDistance = distanceM / EARTH_RADIUS_M;
  const sinAD = Math.sin(angularDistance);
  const cosAD = Math.cos(angularDistance);
  const projectedLat = Math.asin(
    Math.sin(latRad) * cosAD + Math.cos(latRad) * sinAD * Math.cos(headingRad),
  );
  const projectedLon =
    lonRad +
    Math.atan2(
      Math.sin(headingRad) * sinAD * Math.cos(latRad),
      cosAD - Math.sin(latRad) * Math.sin(projectedLat),
    );
  return {
    latitude: (projectedLat * 180) / Math.PI,
    longitude: wrapLongitude((projectedLon * 180) / Math.PI),
    altitudeM,
  };
}
