/**
 * IncidentToast — spec §4.4.3 notification pattern.
 *
 * Top-right sentinel-tinted toast with title, coords, and `▸ Open War Room`.
 * No automatic navigation — user opts in. TTL 12 s by default.
 */
import { useEffect, type CSSProperties } from "react";
import { Link } from "react-router-dom";

import type { Incident } from "../../types/incident";
import { formatCoords } from "../../lib/coords";

export interface IncidentToastProps {
  incident: Incident | null;
  onDismiss: () => void;
  ttlMs?: number;
}

const containerStyle: CSSProperties = {
  position: "fixed",
  top: "60px",
  right: "16px",
  zIndex: 1000,
  width: "320px",
  background: "rgba(18,17,14,0.92)",
  border: "1px solid var(--sentinel)",
  borderTop: "2px solid var(--sentinel)",
  padding: "0.75rem 1rem",
  backdropFilter: "blur(10px)",
};

const eyebrowStyle: CSSProperties = {
  fontFamily: '"Martian Mono", monospace',
  fontSize: "9px",
  letterSpacing: "0.22em",
  color: "var(--sentinel)",
  textTransform: "uppercase",
};

const titleStyle: CSSProperties = {
  fontFamily: '"Instrument Serif", serif',
  fontStyle: "italic",
  fontSize: "15px",
  color: "var(--parchment)",
  margin: "0.25rem 0",
  lineHeight: 1.2,
};

const metaStyle: CSSProperties = {
  fontFamily: '"Martian Mono", monospace',
  fontSize: "10px",
  color: "var(--stone)",
  marginBottom: "0.5rem",
};

const linkStyle: CSSProperties = {
  fontFamily: '"Hanken Grotesk", sans-serif',
  fontSize: "11px",
  textTransform: "uppercase",
  letterSpacing: "0.2em",
  color: "var(--sentinel)",
  textDecoration: "none",
};

export function IncidentToast({ incident, onDismiss, ttlMs = 12_000 }: IncidentToastProps) {
  useEffect(() => {
    if (!incident) return;
    const id = window.setTimeout(onDismiss, ttlMs);
    return () => window.clearTimeout(id);
  }, [incident, onDismiss, ttlMs]);

  if (!incident) return null;

  return (
    <aside role="status" aria-live="polite" data-part="incident-toast" style={containerStyle}>
      <div style={eyebrowStyle}>incident · live</div>
      <h2 style={titleStyle}>{incident.title}</h2>
      <div style={metaStyle}>
        {formatCoords(incident.coords, 2)}
      </div>
      <Link
        to={`/warroom/${incident.id}`}
        style={linkStyle}
        onClick={onDismiss}
      >
        ▸ Open War Room
      </Link>
    </aside>
  );
}
