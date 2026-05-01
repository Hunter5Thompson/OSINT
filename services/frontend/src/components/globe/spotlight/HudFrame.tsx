import { useEffect, useState } from "react";
import { useSpotlight } from "./SpotlightContext";

function utcLabel(d: Date): string {
  return `${d.toISOString().slice(11, 19)} UTC`;
}

export function HudFrame() {
  const { focusTarget } = useSpotlight();
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(id);
  }, []);

  const stateLabel =
    focusTarget == null
      ? "idle"
      : focusTarget.kind === "country"
        ? `country · ${focusTarget.iso3 ?? focusTarget.m49}`
        : `focus · ${focusTarget.label}`;

  return (
    <div className="hud-frame" aria-hidden="true">
      <div className="hud-corners" />
      <div className="hud-crosshair" />
      <div className="hud-eyebrow">§ worldview · {stateLabel} · {now.toISOString().slice(0, 10)}</div>
      <div className="hud-time">{utcLabel(now)}</div>
      <div className="hud-scale">
        <span>500 km</span>
        <span className="hud-scale-bar" />
        <span>1000 km</span>
      </div>
      <div className="hud-coord">— · —</div>
    </div>
  );
}
