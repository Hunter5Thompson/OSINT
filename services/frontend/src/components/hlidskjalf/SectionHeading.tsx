/**
 * SectionHeading — Hlíðskjalf §-paragraph-style heading.
 *
 * Renders "§ <number> · <label>" in Instrument Serif italic with an optional
 * hair-line below. Stub for S1 Task 3; consumed by Tasks 6 + 7.
 */
import type { CSSProperties } from "react";

export interface SectionHeadingProps {
  number?: string;
  label: string;
  hair?: boolean;
  className?: string;
  style?: CSSProperties;
}

export function SectionHeading({
  number,
  label,
  hair = false,
  className,
  style,
}: SectionHeadingProps) {
  return (
    <div className={className} style={style}>
      <h2
        className="serif"
        style={{
          margin: 0,
          fontSize: "1.25rem",
          fontStyle: "italic",
          color: "var(--parchment)",
          letterSpacing: "0.01em",
        }}
      >
        {number ? <span data-part="number">§ {number} · </span> : null}
        <span data-part="label">{label}</span>
      </h2>
      {hair ? <hr className="hair" style={{ marginTop: "0.5rem" }} /> : null}
    </div>
  );
}
