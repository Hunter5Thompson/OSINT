import { useSignalFeed } from "../../hooks/useSignalFeed";
import { SignalFeedItem } from "../hlidskjalf/SignalFeedItem";
import { OverlayPanel } from "../hlidskjalf/OverlayPanel";

type Severity = "sent" | "amb" | "sage" | "dim";

function mapSeverity(s: string | undefined): Severity {
  switch (s) {
    case "critical": return "sent";
    case "high": return "amb";
    case "medium": return "sage";
    default: return "dim";
  }
}

function formatTime(ts: string): string {
  const d = new Date(ts);
  if (Number.isNaN(d.getTime())) return "—";
  const hh = d.getUTCHours().toString().padStart(2, "0");
  const mm = d.getUTCMinutes().toString().padStart(2, "0");
  return `${hh}:${mm}Z`;
}

export function TickerPanel() {
  const { items, status } = useSignalFeed();
  return (
    <OverlayPanel paragraph="IV" label="Ticker" variant="expanded" width={320}>
      <div style={{ display: "flex", flexDirection: "column", gap: 4, maxHeight: 220, overflowY: "auto" }}>
        {status === "reconnecting" && (
          <span className="mono" style={{ color: "var(--ash)", fontSize: 10 }}>§ reconnecting…</span>
        )}
        {items.length === 0 && status !== "reconnecting" && (
          <span className="mono" style={{ color: "var(--ash)", fontSize: 10 }}>— no signals yet —</span>
        )}
        {items.map((env) => (
          <SignalFeedItem
            key={env.event_id}
            severity={mapSeverity(env.payload.severity)}
            ts={formatTime(env.ts)}
            text={env.payload.title || env.type}
          />
        ))}
      </div>
    </OverlayPanel>
  );
}
