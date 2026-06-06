import type { WindowEventSample } from "../../types";

interface TwoTierScrubberProps {
  events: WindowEventSample[];
  mode: "live" | "replay";
  cursorMs: number;
  onSelectEvent: (e: WindowEventSample) => void;
  onSeek: (ms: number) => void;
  onToggleMode: () => void;
}

// Functional shell only — visual design goes through the Hlíðskjalf system later.
export function TwoTierScrubber({
  events, mode, cursorMs, onSelectEvent, onSeek, onToggleMode,
}: TwoTierScrubberProps) {
  return (
    <section
      aria-label="time scrubber"
      style={{
        position: "absolute", bottom: 12, left: "50%", transform: "translateX(-50%)",
        display: "flex", flexDirection: "column", gap: 6, padding: "8px 12px",
        background: "var(--hl-panel-bg, rgba(10,10,12,0.7))",
        backdropFilter: "blur(var(--hl-panel-blur, 12px))",
        border: "1px solid var(--granite, #333)", borderRadius: 6,
        fontFamily: "var(--hl-font-mono, monospace)", fontSize: 11, color: "#ddd",
      }}
    >
      <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
        <button type="button" onClick={onToggleMode} aria-label="toggle mode">
          {mode === "live" ? "● LIVE" : "▶ REPLAY"}
        </button>
        <span>{new Date(cursorMs).toISOString().replace("T", " ").slice(0, 19)}Z</span>
      </div>

      {/* Coarse tier: event ticks */}
      <div
        role="group"
        aria-label="event timeline"
        style={{ display: "flex", gap: 4, flexWrap: "wrap", maxWidth: 520 }}
      >
        {events.length === 0 ? (
          <span style={{ opacity: 0.6 }}>no events in window</span>
        ) : (
          events.map((e) => (
            <button
              key={e.id}
              type="button"
              title={`${e.time} · ${e.time_basis}`}
              onClick={() => {
                onSelectEvent(e);
                onSeek(Date.parse(e.time));
              }}
              style={{ padding: "1px 4px", fontSize: 10 }}
            >
              {e.title ?? e.codebook_type ?? e.id}
            </button>
          ))
        )}
      </div>
    </section>
  );
}
