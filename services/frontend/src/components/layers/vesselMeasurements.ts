/** AIS speed/course are nullable: null means "not available", never 0. */

const MIN_MOVING_KNOTS = 0.5;

export function formatVesselSpeed(speedKnots: number | null): string {
  return speedKnots === null ? "unknown" : `${speedKnots.toFixed(1)} kts`;
}

export function formatVesselCourse(courseDeg: number | null): string {
  return courseDeg === null ? "unknown" : `${Math.round(courseDeg) % 360}°`;
}

/** Motion vectors need a measured moving speed AND a measured course. */
export function canProjectVesselMotion(
  speedKnots: number | null,
  courseDeg: number | null,
): boolean {
  return speedKnots !== null && courseDeg !== null && speedKnots > MIN_MOVING_KNOTS;
}
