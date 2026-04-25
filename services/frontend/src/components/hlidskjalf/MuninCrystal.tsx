/**
 * MuninCrystal — inline SVG echo of the design-`i` "isometric stack" motif.
 *
 * Three stroked rhombi stacked vertically; the centre one is slightly
 * brighter (foreground). Pure SVG, no animation, no rounded corners.
 */
import type { CSSProperties } from "react";

export interface MuninCrystalProps {
  size?: number;
  className?: string;
  style?: CSSProperties;
}

export function MuninCrystal({ size = 64, className, style }: MuninCrystalProps) {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      width={size}
      height={size}
      viewBox="-50 -50 100 100"
      data-part="munin-crystal"
      aria-hidden="true"
      className={className}
      style={style}
    >
      {/* Top rhombus (background) */}
      <polygon
        data-rhombus="top"
        points="0,-32 24,-20 0,-8 -24,-20"
        fill="none"
        stroke="var(--amber)"
        strokeOpacity={0.45}
        strokeWidth={1}
      />
      {/* Middle rhombus (foreground / brightest) */}
      <polygon
        data-rhombus="mid"
        points="0,-12 30,4 0,20 -30,4"
        fill="rgba(196,129,58,0.10)"
        stroke="var(--amber)"
        strokeOpacity={0.95}
        strokeWidth={1.25}
      />
      {/* Bottom rhombus (background) */}
      <polygon
        data-rhombus="bot"
        points="0,18 24,30 0,42 -24,30"
        fill="none"
        stroke="var(--amber)"
        strokeOpacity={0.45}
        strokeWidth={1}
      />
    </svg>
  );
}
