/**
 * IncidentBar — spec §4.4.1.
 *
 * Visible only when an incident is active. Sentinel-tinted gradient
 * background, LIVE tag, title (Instrument Serif italic), coords (Mono Stone),
 * T+ clock (Mono Sentinel) — visually loud enough to never be confused with
 * the dim Ash UTC clock in the TopBar.
 */
import type { CSSProperties } from "react";

import type { Incident } from "../../types/incident";
import { useTPlus } from "../../hooks/useTPlus";
import { formatCoords } from "../../lib/coords";

export interface IncidentBarProps {
  incident: Incident;
  style?: CSSProperties;
}

const barStyle: CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: "1.5rem",
  height: "44px",
  padding: "0 1.25rem",
  borderBottom: "1px solid var(--granite)",
  background:
    "linear-gradient(90deg, rgba(184,90,42,0.16) 0%, rgba(184,90,42,0.04) 60%, rgba(11,10,8,0) 100%)",
};

const tagStyle: CSSProperties = {
  fontFamily: '"Martian Mono", ui-monospace, monospace',
  fontSize: "9px",
  letterSpacing: "0.22em",
  textTransform: "uppercase",
  color: "var(--sentinel)",
  border: "1px solid var(--sentinel)",
  padding: "2px 6px",
};

const titleStyle: CSSProperties = {
  fontFamily: '"Instrument Serif", "Times New Roman", serif',
  fontStyle: "italic",
  fontSize: "16px",
  color: "var(--parchment)",
  margin: 0,
};

const metaStyle: CSSProperties = {
  fontFamily: '"Martian Mono", ui-monospace, monospace',
  fontSize: "10px",
  letterSpacing: "0.04em",
  color: "var(--stone)",
};

const clockStyle: CSSProperties = {
  fontFamily: '"Martian Mono", ui-monospace, monospace',
  fontSize: "13px",
  letterSpacing: "0.06em",
  color: "var(--sentinel)",
  marginLeft: "auto",
};

function severityToConf(s: Incident["severity"]): number {
  switch (s) {
    case "low":
      return 0.55;
    case "elevated":
      return 0.7;
    case "high":
      return 0.85;
    case "critical":
      return 0.95;
  }
}

export function IncidentBar({ incident, style }: IncidentBarProps) {
  const tplus = useTPlus(incident.trigger_ts);
  return (
    <header
      role="status"
      aria-label="Active incident"
      data-part="incident-bar"
      data-severity={incident.severity}
      style={{ ...barStyle, ...style }}
    >
      <span style={tagStyle}>INCIDENT · LIVE</span>
      <h1 style={titleStyle}>{incident.title}</h1>
      <span style={metaStyle}>
        {formatCoords(incident.coords)}
        {"  "}· conf {(severityToConf(incident.severity)).toFixed(2)}
      </span>
      <span data-testid="incident-tplus" style={clockStyle}>
        {tplus}
      </span>
    </header>
  );
}
