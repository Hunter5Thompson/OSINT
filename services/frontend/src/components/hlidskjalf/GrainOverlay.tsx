/**
 * GrainOverlay — inline SVG feTurbulence grain layer.
 *
 * Drop-in over any panel root; applies `mix-blend-mode: screen` for a subtle
 * film-grain texture per spec §2.3. Stub for S1 Task 3.
 */
import type { CSSProperties } from "react";

export interface GrainOverlayProps {
  opacity?: number;
  seed?: number;
  className?: string;
  style?: CSSProperties;
}

export function GrainOverlay({
  opacity = 0.45,
  seed = 4,
  className,
  style,
}: GrainOverlayProps) {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      className={className}
      data-part="grain"
      aria-hidden="true"
      style={{
        position: "absolute",
        inset: 0,
        width: "100%",
        height: "100%",
        pointerEvents: "none",
        mixBlendMode: "screen",
        opacity,
        ...style,
      }}
    >
      <filter id={`grain-${seed}`}>
        <feTurbulence
          type="fractalNoise"
          baseFrequency="0.9"
          numOctaves={2}
          seed={seed}
          stitchTiles="stitch"
        />
        <feColorMatrix
          type="matrix"
          values="0 0 0 0 0.91  0 0 0 0 0.89  0 0 0 0 0.83  0 0 0 0.6 0"
        />
      </filter>
      <rect width="100%" height="100%" filter={`url(#grain-${seed})`} />
    </svg>
  );
}
