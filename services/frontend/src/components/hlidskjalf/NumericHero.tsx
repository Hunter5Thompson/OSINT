/**
 * NumericHero — large Instrument Serif italic numeral with eyebrow + diff.
 *
 * Used for landing-page metrics and dashboard KPI cards. Stub for S1 Task 3.
 */
import type { CSSProperties } from "react";

export type NumericAccent = "amber" | "sage" | "sent" | "parchment";

export interface NumericHeroProps {
  value: string | number;
  label: string;
  accent?: NumericAccent;
  diff?: string;
  sub?: string;
  className?: string;
  style?: CSSProperties;
}

const ACCENT_VAR: Record<NumericAccent, string> = {
  amber: "var(--amber)",
  sage: "var(--sage)",
  sent: "var(--sentinel)",
  parchment: "var(--parchment)",
};

export function NumericHero({
  value,
  label,
  accent = "parchment",
  diff,
  sub,
  className,
  style,
}: NumericHeroProps) {
  return (
    <div
      className={className}
      data-part="numeric-hero"
      style={{ display: "flex", flexDirection: "column", gap: "0.25rem", ...style }}
    >
      <span className="eyebrow" data-part="label">
        {label}
      </span>
      <span
        className="serif"
        data-part="value"
        style={{
          fontSize: "3.75rem",
          lineHeight: 1,
          fontStyle: "italic",
          color: ACCENT_VAR[accent],
        }}
      >
        {value}
      </span>
      {diff ? (
        <span className="mono" data-part="diff" style={{ fontSize: "0.75rem", color: "var(--stone)" }}>
          {diff}
        </span>
      ) : null}
      {sub ? (
        <span className="mono" data-part="sub" style={{ fontSize: "0.7rem", color: "var(--ash)" }}>
          {sub}
        </span>
      ) : null}
    </div>
  );
}
