/**
 * LeaderCallout — floating Basalt card with a hair-line "leader" pointing to
 * an off-card anchor (e.g. an entity dot on the globe). Visual cue borrowed
 * from the design-`i` Pandemic Prediction System reference and re-coloured
 * for Hlíðskjalf (no cyan, no rounded corners, no glow).
 */
import type { CSSProperties, ReactNode } from "react";

export type LeaderDirection = "left" | "right" | "up" | "down";
export type LeaderTone = "amber" | "sentinel" | "sage" | "stone";

export interface LeaderCalloutProps {
  eyebrow: string;
  value: ReactNode;
  sub?: string;
  leader: { from: LeaderDirection; deltaPx: number };
  tone?: LeaderTone;
  style?: CSSProperties;
}

const cardStyle: CSSProperties = {
  position: "relative",
  background: "rgba(26,24,20,0.84)",
  border: "1px solid var(--granite)",
  padding: "0.5rem 0.75rem",
  minWidth: "120px",
  backdropFilter: "blur(6px)",
};

const eyebrowStyle: CSSProperties = {
  fontFamily: '"Hanken Grotesk", sans-serif',
  fontSize: "9px",
  letterSpacing: "0.22em",
  textTransform: "uppercase",
  color: "var(--ash)",
};

const valueStyle: CSSProperties = {
  fontFamily: '"Instrument Serif", serif',
  fontStyle: "italic",
  fontSize: "20px",
  color: "var(--parchment)",
  lineHeight: 1.1,
  marginTop: "2px",
};

const subStyle: CSSProperties = {
  fontFamily: '"Hanken Grotesk", sans-serif',
  fontSize: "10px",
  color: "var(--stone)",
  marginTop: "2px",
};

const TONE_VAR: Record<LeaderTone, string> = {
  amber: "var(--amber)",
  sentinel: "var(--sentinel)",
  sage: "var(--sage)",
  stone: "var(--stone)",
};

export function LeaderCallout({
  eyebrow,
  value,
  sub,
  leader,
  tone = "amber",
  style,
}: LeaderCalloutProps) {
  const { from, deltaPx } = leader;
  const isHorizontal = from === "left" || from === "right";
  const svgWidth = isHorizontal ? deltaPx : 12;
  const svgHeight = isHorizontal ? 12 : deltaPx;
  const x1 = from === "right" ? 0 : svgWidth;
  const y1 = isHorizontal ? svgHeight / 2 : from === "down" ? 0 : svgHeight;
  const x2 = from === "right" ? svgWidth : 0;
  const y2 = isHorizontal ? svgHeight / 2 : from === "down" ? svgHeight : 0;

  const positionStyle: CSSProperties =
    from === "right"
      ? { left: "100%", top: "50%", transform: "translateY(-50%)" }
      : from === "left"
        ? { right: "100%", top: "50%", transform: "translateY(-50%)" }
        : from === "down"
          ? { left: "50%", top: "100%", transform: "translateX(-50%)" }
          : { left: "50%", bottom: "100%", transform: "translateX(-50%)" };

  return (
    <div data-part="leader-callout" style={{ ...cardStyle, ...style }}>
      <div style={eyebrowStyle}>○ {eyebrow}</div>
      <div style={valueStyle}>{value}</div>
      {sub ? <div style={subStyle}>{sub}</div> : null}
      <svg
        data-part="leader"
        width={svgWidth}
        height={svgHeight}
        viewBox={`0 0 ${svgWidth} ${svgHeight}`}
        style={{ position: "absolute", pointerEvents: "none", ...positionStyle }}
        aria-hidden="true"
      >
        <line x1={x1} y1={y1} x2={x2} y2={y2} stroke="var(--granite)" strokeWidth={1} />
        <circle cx={x2} cy={y2} r={2.5} fill={TONE_VAR[tone]} />
      </svg>
    </div>
  );
}
