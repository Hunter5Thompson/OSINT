// services/frontend/src/components/time/transport.ts

/** Playback direction: +1 forward in time, -1 backward. */
export type Direction = 1 | -1;

/** Effective signed clock multiplier from a UI magnitude + direction.
 *  Magnitude is taken as absolute so the UI never has to track a sign. */
export function signedSpeed(magnitude: number, direction: Direction): number {
  return Math.abs(magnitude) * direction;
}

/** Seek target one bucket away from currentMs, clamped to [start, end].
 *  No wraparound — at a bound the target is the bound. */
export function stepTargetMs(
  currentMs: number,
  rangeStartMs: number,
  rangeEndMs: number,
  bucketCount: number,
  direction: Direction,
): number {
  const span = Math.max(rangeEndMs - rangeStartMs, 1);
  const bucketMs = span / Math.max(bucketCount, 1);
  const next = currentMs + bucketMs * direction;
  return Math.min(rangeEndMs, Math.max(rangeStartMs, next));
}

/** The window a step should move within: the brushed replay window when one is
 *  active, otherwise the coarse rolling range. Keeps steps inside the selection. */
export function stepWindow(
  inReplay: boolean,
  brush: { startMs: number; endMs: number } | null,
  coarseStartMs: number,
  coarseEndMs: number,
): { startMs: number; endMs: number } {
  return inReplay && brush ? brush : { startMs: coarseStartMs, endMs: coarseEndMs };
}
