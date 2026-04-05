/**
 * Aircraft type-specific canvas icon factory with heading-bucketed caching.
 *
 * Classification: callsign prefix + ADS-B category heuristics.
 * Cache key: `{type}_{headingBucket}` — max 72 headings × 6 types = 432 entries.
 */

export type AircraftIconType = "fighter" | "bomber" | "transport_mil" | "helicopter" | "uav" | "civilian";

const MILITARY_CALLSIGN_PREFIXES = [
  "RCH", "EVAC", "DUKE", "VALOR", "REACH", "FORGE", "COBRA", "HAWK",
  "VIPER", "RAPTOR", "REAPER", "SIGINT", "FORTE", "NCHO", "TOPCAT",
];

const ICON_COLORS: Record<AircraftIconType, string> = {
  fighter: "#ef4444",
  bomber: "#ef4444",
  transport_mil: "#c4813a",
  helicopter: "#ef4444",
  uav: "#a855f7",
  civilian: "#d4cdc0",
};

export function classifyAircraft(
  callsign: string | null,
  isMilitary: boolean,
  aircraftType: string | null,
  altitudeM: number,
  velocityMs: number,
): AircraftIconType {
  const cs = (callsign ?? "").toUpperCase().trim();
  const at = (aircraftType ?? "").toUpperCase();

  // Helicopter: aircraft_type contains H (e.g., H60, H47, EC35)
  if (/^H\d|^EC\d|^AS\d|^AW\d|^R22|^R44|^R66|^B06|^B47/.test(at)) return "helicopter";

  // UAV/drone heuristic: slow + low + specific names
  if (
    (cs.includes("REAPER") || cs.includes("FORTE") || cs.includes("SIGINT") || at.includes("RQ") || at.includes("MQ")) &&
    isMilitary
  ) return "uav";

  // Military transport: known callsign prefixes
  if (isMilitary && MILITARY_CALLSIGN_PREFIXES.some((p) => cs.startsWith(p))) return "transport_mil";

  // Fighter: military + fast + high
  if (isMilitary && velocityMs > 200 && altitudeM > 5000) return "fighter";

  // Bomber/heavy mil: military + large type codes
  if (isMilitary && (at.includes("B52") || at.includes("B1") || at.includes("B2") || at.includes("TU"))) return "bomber";

  // Generic military
  if (isMilitary) return "fighter";

  return "civilian";
}

const iconCache = new Map<string, string>();

export function getAircraftTypeIcon(
  type: AircraftIconType,
  headingDeg: number,
): string {
  const bucket = ((Math.round((headingDeg || 0) / 5) * 5) % 360 + 360) % 360;
  const key = `${type}_${bucket}`;

  const cached = iconCache.get(key);
  if (cached) return cached;

  const size = 24;
  const canvas = document.createElement("canvas");
  canvas.width = size;
  canvas.height = size;
  const ctx = canvas.getContext("2d");
  if (!ctx) return canvas.toDataURL();

  const color = ICON_COLORS[type];

  ctx.translate(size / 2, size / 2);
  ctx.rotate((bucket * Math.PI) / 180);

  switch (type) {
    case "fighter":
      // Delta wings, narrow body
      ctx.beginPath();
      ctx.moveTo(0, -10);
      ctx.lineTo(-8, 6);
      ctx.lineTo(-3, 4);
      ctx.lineTo(-2, 8);
      ctx.lineTo(2, 8);
      ctx.lineTo(3, 4);
      ctx.lineTo(8, 6);
      ctx.closePath();
      break;

    case "bomber":
      // Swept wings, wide body
      ctx.beginPath();
      ctx.moveTo(0, -10);
      ctx.lineTo(-10, 4);
      ctx.lineTo(-4, 3);
      ctx.lineTo(-3, 8);
      ctx.lineTo(3, 8);
      ctx.lineTo(4, 3);
      ctx.lineTo(10, 4);
      ctx.closePath();
      break;

    case "transport_mil":
      // Wide body, straight wings
      ctx.beginPath();
      ctx.moveTo(0, -10);
      ctx.lineTo(-3, -2);
      ctx.lineTo(-10, -1);
      ctx.lineTo(-10, 2);
      ctx.lineTo(-3, 1);
      ctx.lineTo(-2, 8);
      ctx.lineTo(-5, 9);
      ctx.lineTo(-5, 10);
      ctx.lineTo(5, 10);
      ctx.lineTo(5, 9);
      ctx.lineTo(2, 8);
      ctx.lineTo(3, 1);
      ctx.lineTo(10, 2);
      ctx.lineTo(10, -1);
      ctx.lineTo(3, -2);
      ctx.closePath();
      break;

    case "helicopter":
      // Rotor disc + tail boom
      ctx.beginPath();
      ctx.arc(0, -1, 6, 0, Math.PI * 2); // rotor disc
      ctx.moveTo(-1, 5);
      ctx.lineTo(-1, 10);
      ctx.lineTo(1, 10);
      ctx.lineTo(1, 5); // tail boom
      ctx.moveTo(-3, 10);
      ctx.lineTo(3, 10); // tail rotor
      break;

    case "uav":
      // Narrow profile, small
      ctx.beginPath();
      ctx.moveTo(0, -8);
      ctx.lineTo(-6, 2);
      ctx.lineTo(-2, 1);
      ctx.lineTo(-1, 6);
      ctx.lineTo(1, 6);
      ctx.lineTo(2, 1);
      ctx.lineTo(6, 2);
      ctx.closePath();
      break;

    case "civilian":
    default:
      // Standard airliner
      ctx.beginPath();
      ctx.moveTo(0, -10);
      ctx.lineTo(-8, 4);
      ctx.lineTo(0, 2);
      ctx.lineTo(8, 4);
      ctx.closePath();
      break;
  }

  ctx.fillStyle = color;
  ctx.globalAlpha = 0.9;
  ctx.fill();
  ctx.globalAlpha = 1.0;
  ctx.strokeStyle = color;
  ctx.lineWidth = 0.5;
  ctx.stroke();

  const dataUrl = canvas.toDataURL();
  iconCache.set(key, dataUrl);
  return dataUrl;
}

export function clearAircraftIconCache(): void {
  iconCache.clear();
}
