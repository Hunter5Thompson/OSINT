import type { CSSProperties } from "react";

import type { Incident, IncidentTimelineEvent } from "../../types/incident";
import { SectionHeading } from "../hlidskjalf/SectionHeading";

const KIND_TONE: Record<string, string> = {
  trigger: "var(--sentinel)",
  signal: "var(--amber)",
  agent: "var(--sage)",
  source: "var(--stone)",
  note: "var(--ash)",
};

function formatOffset(s: number): string {
  const safe = Math.max(0, Math.floor(s));
  const mm = Math.floor(safe / 60);
  const ss = safe - mm * 60;
  return `T+${String(mm).padStart(2, "0")}:${String(ss).padStart(2, "0")}`;
}

const rowStyle: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "62px 12px 1fr",
  gap: "0.5rem",
  alignItems: "baseline",
  padding: "4px 0",
  borderBottom: "1px solid var(--granite)",
};

const tStyle: CSSProperties = {
  fontFamily: '"Martian Mono", monospace',
  fontSize: "10px",
  color: "var(--stone)",
};

const dotStyle = (color: string): CSSProperties => ({
  width: 6,
  height: 6,
  borderRadius: "50%",
  background: color,
  alignSelf: "center",
});

const textStyle: CSSProperties = {
  fontFamily: '"Instrument Serif", serif',
  fontStyle: "italic",
  fontSize: "13px",
  color: "var(--bone)",
};

export interface TimelineQuadrantProps {
  incident: Incident;
}

export function TimelineQuadrant({ incident }: TimelineQuadrantProps) {
  const sorted: IncidentTimelineEvent[] = [...incident.timeline].sort(
    (a, b) => b.t_offset_s - a.t_offset_s,
  );
  return (
    <section data-quadrant="timeline" style={{ padding: "1rem", overflow: "auto" }}>
      <SectionHeading number="II" label="Timeline" hair />
      <div role="list" style={{ marginTop: "0.5rem" }}>
        {sorted.map((event, idx) => {
          const isBaseline = event.kind === "trigger";
          return (
            <div
              key={`${event.t_offset_s}-${idx}`}
              role="listitem"
              data-testid="timeline-row"
              style={rowStyle}
            >
              <span style={tStyle}>{formatOffset(event.t_offset_s)}</span>
              <span style={dotStyle(KIND_TONE[event.kind] ?? (KIND_TONE.note || "var(--ash)"))} aria-hidden="true" />
              <span style={{ ...textStyle, color: isBaseline ? "var(--ash)" : "var(--bone)" }}>
                {isBaseline ? `Trigger · ${event.text}` : event.text}
              </span>
            </div>
          );
        })}
      </div>
    </section>
  );
}
