import { useSignalFeed } from "../../hooks/useSignalFeed";
import { OverlayPanel, type OverlayPanelVariant } from "../hlidskjalf/OverlayPanel";
import { SignalFeedItem } from "../hlidskjalf/SignalFeedItem";

type Severity = "sent" | "amb" | "sage" | "dim";

interface TickerPanelProps {
  variant?: OverlayPanelVariant;
  onClose?: () => void;
  onExpand?: () => void;
}

function mapSeverity(severity: string | undefined): Severity {
  switch (severity) {
    case "critical":
      return "sent";
    case "high":
      return "amb";
    case "medium":
      return "sage";
    default:
      return "dim";
  }
}

function formatTime(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "--:--Z";
  const hh = String(d.getUTCHours()).padStart(2, "0");
  const mm = String(d.getUTCMinutes()).padStart(2, "0");
  return `${hh}:${mm}Z`;
}

export function TickerPanel({ variant = "expanded", onClose, onExpand }: TickerPanelProps = {}) {
  const { items, status } = useSignalFeed();

  if (variant === "collapsed") {
    return (
      <OverlayPanel paragraph="IV" label="Ticker" variant="collapsed" onExpand={onExpand}>
        {null}
      </OverlayPanel>
    );
  }

  return (
    <OverlayPanel
      paragraph="IV"
      label="Ticker"
      variant="expanded"
      width={340}
      onClose={onClose}
    >
      <div style={{ display: "grid", gap: "0.15rem", maxHeight: 228, overflowY: "auto" }}>
        {status === "reconnecting" ? (
          <span className="mono" style={{ color: "var(--ash)", fontSize: "0.65rem" }}>
            § reconnecting...
          </span>
        ) : null}

        {items.length === 0 && status !== "reconnecting" ? (
          <span className="mono" style={{ color: "var(--ash)", fontSize: "0.65rem" }}>
            - no signals yet -
          </span>
        ) : null}

        {items.map((entry) => (
          <SignalFeedItem
            key={entry.event_id}
            severity={mapSeverity(entry.payload.severity)}
            ts={formatTime(entry.ts)}
            text={entry.payload.title || entry.type}
          />
        ))}
      </div>
    </OverlayPanel>
  );
}
