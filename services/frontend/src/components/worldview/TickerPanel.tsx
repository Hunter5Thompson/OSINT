import { OverlayPanel } from "../hlidskjalf/OverlayPanel";

export function TickerPanel() {
  return (
    <OverlayPanel paragraph="IV" label="Ticker" variant="expanded" width={320}>
      <div className="mono" style={{ color: "var(--stone)" }}>§ placeholder</div>
    </OverlayPanel>
  );
}
