import type { CSSProperties } from "react";

import type { Incident } from "../../types/incident";
import { SectionHeading } from "../hlidskjalf/SectionHeading";

const SOURCE_TONE: Record<string, string> = {
  firms: "var(--sentinel)",
  ucdp: "var(--amber)",
  gdelt: "var(--sage)",
  ais: "var(--stone)",
  default: "var(--stone)",
};

function toneFor(label: string): string {
  const head = (label.split(/[·\s]/, 1)[0] ?? "").toLowerCase();
  return (SOURCE_TONE[head as keyof typeof SOURCE_TONE] ?? SOURCE_TONE.default) as string;
}

const gridStyle: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "1fr 1fr",
  gap: "0.5rem",
  marginTop: "0.5rem",
};

const cardStyle: CSSProperties = {
  background: "var(--basalt)",
  border: "1px solid var(--granite)",
  padding: "0.5rem 0.75rem",
  minHeight: "62px",
  display: "flex",
  flexDirection: "column",
  justifyContent: "space-between",
};

const tagStyle = (color: string): CSSProperties => ({
  fontFamily: '"Martian Mono", monospace',
  fontSize: "9px",
  letterSpacing: "0.22em",
  textTransform: "uppercase",
  color,
});

const titleStyle: CSSProperties = {
  fontFamily: '"Instrument Serif", serif',
  fontStyle: "italic",
  fontSize: "12px",
  color: "var(--bone)",
};

const actionRowStyle: CSSProperties = {
  display: "flex",
  gap: "1rem",
  marginTop: "0.75rem",
  paddingTop: "0.5rem",
  borderTop: "1px solid var(--granite)",
};

const actionButtonStyle = (color: string): CSSProperties => ({
  background: "transparent",
  border: "none",
  color,
  fontFamily: '"Hanken Grotesk", sans-serif',
  fontSize: "10px",
  letterSpacing: "0.22em",
  textTransform: "uppercase",
  cursor: "pointer",
  padding: 0,
});

export interface RawSourcesQuadrantProps {
  incident: Incident;
  onPromote: () => void;
  onSilence: () => void;
  onAsk: () => void;
}

export function RawSourcesQuadrant({
  incident,
  onPromote,
  onSilence,
  onAsk,
}: RawSourcesQuadrantProps) {
  const sources = incident.sources.slice(0, 4);
  return (
    <section data-quadrant="raw" style={{ padding: "1rem", display: "flex", flexDirection: "column", height: "100%", minHeight: 0 }}>
      <SectionHeading number="IV" label="Raw · sources" hair />
      <div style={gridStyle}>
        {sources.map((source) => {
          const tone = toneFor(source);
          const [head, ...rest] = source.split(/·\s*/);
          return (
            <article key={source} data-testid="source-card" style={cardStyle}>
              <div style={tagStyle(tone)}>{head}</div>
              <div style={titleStyle}>{rest.join(" · ") || "—"}</div>
            </article>
          );
        })}
      </div>
      <div style={actionRowStyle}>
        <button
          type="button"
          onClick={onPromote}
          style={{ ...actionButtonStyle("var(--sentinel)"), textDecoration: "underline", textUnderlineOffset: 4 }}
        >
          ▸ Promote to dossier
        </button>
        <button type="button" onClick={onSilence} style={actionButtonStyle("var(--stone)")}>
          Silence alert
        </button>
        <button type="button" onClick={onAsk} style={actionButtonStyle("var(--amber)")}>
          Ask Munin
        </button>
      </div>
    </section>
  );
}
