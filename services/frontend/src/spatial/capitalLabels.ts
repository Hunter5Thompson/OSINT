interface Anchor { x: number; y: number; width: number }
interface Box extends Anchor { height: number }
/** Bounded, stable screen-space placement, rerun only when the camera settles. */
export function layoutCapitalLabels(anchors: readonly Anchor[], width: number, height: number): { x: number; y: number }[] {
  const occupied: Box[] = [];
  return anchors.map((anchor) => {
    const candidates = [
      [14, -36], [-anchor.width - 14, -36], [14, 12], [-anchor.width - 14, 12],
      [14, -80], [-anchor.width - 14, -80], [14, 56], [-anchor.width - 14, 56],
    ].map(([dx, dy]) => ({
      x: Math.max(10, Math.min(width - anchor.width - 10, anchor.x + dx!)),
      y: Math.max(185, Math.min(height - 140 - 36, anchor.y + dy!)),
      width: anchor.width, height: 36,
    }));
    const overlaps = (box: Box) => occupied.filter((other) => box.x < other.x + other.width + 8
      && box.x + box.width + 8 > other.x && box.y < other.y + other.height + 4
      && box.y + box.height + 4 > other.y).length;
    const best = candidates.reduce((a, b) => overlaps(a) <= overlaps(b) ? a : b);
    occupied.push(best);
    return { x: best.x - anchor.x, y: best.y - anchor.y };
  });
}
