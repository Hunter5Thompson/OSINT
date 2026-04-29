import type { CSSProperties } from "react";

export type AgentStreamTone = "amber" | "sage" | "sentinel" | "stone";

export interface AgentStreamLineProps {
  tplus: string;
  tool: string;
  detail: string;
  tone?: AgentStreamTone;
}

const TONE_VAR: Record<AgentStreamTone, string> = {
  amber: "var(--amber)",
  sage: "var(--sage)",
  sentinel: "var(--sentinel)",
  stone: "var(--stone)",
};

const baseStyle: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "78px 1fr",
  gap: "0.75rem",
  alignItems: "baseline",
  padding: "2px 0",
  fontFamily: '"Martian Mono", monospace',
  fontSize: "10px",
  letterSpacing: "0.04em",
  color: "var(--stone)",
  whiteSpace: "nowrap",
  overflow: "hidden",
  textOverflow: "ellipsis",
};

export function AgentStreamLine({
  tplus,
  tool,
  detail,
  tone = "stone",
}: AgentStreamLineProps) {
  return (
    <div data-part="agent-stream-line" data-tone={tone} style={baseStyle}>
      <span style={{ color: "var(--ash)" }}>{tplus}</span>
      <span>
        <span style={{ color: TONE_VAR[tone] }}>{tool}</span>
        <span style={{ color: "var(--ash)" }}> /→ </span>
        <span>{detail}</span>
      </span>
    </div>
  );
}
