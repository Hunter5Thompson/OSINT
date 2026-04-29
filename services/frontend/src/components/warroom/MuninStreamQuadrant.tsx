import { useState, type CSSProperties, type FormEvent, type KeyboardEvent } from "react";

import { SectionHeading } from "../hlidskjalf/SectionHeading";
import { AgentStreamLine, type AgentStreamLineProps } from "../hlidskjalf/AgentStreamLine";
import { MuninCrystal } from "../hlidskjalf/MuninCrystal";

export interface MuninToolCall {
  tplus: string;
  tool: string;
  detail: string;
  tone?: AgentStreamLineProps["tone"];
}

export interface MuninStreamQuadrantProps {
  toolCalls: MuninToolCall[];
  hypothesis: string;
  onAsk: (prompt: string) => void;
  busy?: boolean;
}

const layoutStyle: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "84px 1fr",
  gap: "0.75rem",
  padding: "1rem",
  height: "100%",
  minHeight: 0,
  overflow: "hidden",
};

const streamStyle: CSSProperties = {
  display: "flex",
  flexDirection: "column",
  minHeight: 0,
  height: "100%",
};

const callsStyle: CSSProperties = {
  flex: 1,
  overflowY: "auto",
  marginTop: "0.5rem",
  paddingRight: "4px",
};

const hypothesisStyle: CSSProperties = {
  fontFamily: '"Instrument Serif", serif',
  fontStyle: "italic",
  fontSize: "12px",
  color: "var(--bone)",
  borderTop: "1px solid var(--granite)",
  paddingTop: "0.5rem",
  marginTop: "0.5rem",
};

const inputStyle: CSSProperties = {
  marginTop: "0.5rem",
  width: "100%",
  background: "transparent",
  border: "1px solid var(--granite)",
  color: "var(--parchment)",
  fontFamily: '"Hanken Grotesk", sans-serif',
  fontSize: "12px",
  padding: "0.5rem 0.75rem",
  outline: "none",
};

export function MuninStreamQuadrant({
  toolCalls,
  hypothesis,
  onAsk,
  busy = false,
}: MuninStreamQuadrantProps) {
  const [draft, setDraft] = useState("");

  function handleSubmit(ev: FormEvent<HTMLFormElement>) {
    ev.preventDefault();
    const value = draft.trim();
    if (!value || busy) return;
    onAsk(value);
    setDraft("");
  }

  function handleKey(ev: KeyboardEvent<HTMLInputElement>) {
    if ((ev.metaKey || ev.ctrlKey) && ev.key === "Enter") {
      ev.preventDefault();
      const value = draft.trim();
      if (!value || busy) return;
      onAsk(value);
      setDraft("");
    }
  }

  return (
    <section data-quadrant="munin" style={layoutStyle}>
      <div style={{ display: "flex", flexDirection: "column", alignItems: "center", paddingTop: "1.5rem" }}>
        <MuninCrystal size={72} />
        <span
          style={{
            fontFamily: '"Hanken Grotesk", sans-serif',
            fontSize: "9px",
            letterSpacing: "0.22em",
            color: "var(--ash)",
            textTransform: "uppercase",
            marginTop: "0.5rem",
          }}
        >
          munin
        </span>
      </div>
      <div style={streamStyle}>
        <SectionHeading number="III" label="Munin · stream" hair />
        <div style={callsStyle}>
          {toolCalls.map((c, idx) => (
            <AgentStreamLine key={idx} tplus={c.tplus} tool={c.tool} detail={c.detail} tone={c.tone} />
          ))}
          {toolCalls.length === 0 ? (
            <div
              style={{
                fontFamily: '"Martian Mono", monospace',
                fontSize: "10px",
                color: "var(--ash)",
              }}
            >
              munin · idle
            </div>
          ) : null}
        </div>
        <div data-part="hypothesis" style={hypothesisStyle}>
          {hypothesis || "§ working hypothesis · pending first signal"}
        </div>
        <form onSubmit={handleSubmit}>
          <input
            type="text"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={handleKey}
            placeholder="▸ ask Munin about this incident…  ⌘↩"
            style={inputStyle}
            disabled={busy}
          />
        </form>
      </div>
    </section>
  );
}
