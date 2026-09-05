import type { SignalFeedStatus } from "../../hooks/useSignalFeed";
const LABELS: Record<SignalFeedStatus, string> = {
  idle: "Connecting to signal feed",
  live: "Stream connected",
  reconnecting: "Reconnecting · updates paused",
  down: "Signal stream unavailable",
};
export function FeedConnection({ status }: { status: SignalFeedStatus }) {
  return (
    <span className="feed-connection" data-status={status} role="status">
      <span aria-hidden="true" />
      {LABELS[status]}
    </span>
  );
}
