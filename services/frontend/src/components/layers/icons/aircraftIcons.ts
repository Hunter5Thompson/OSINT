/**
 * Aircraft type-specific canvas icon factory with heading-bucketed caching.
 *
 * Classification: callsign prefix + ADS-B category heuristics.
 * Cache key: `{type}_{headingBucket}` — max 72 headings × 6 types = 432 entries.
 */

export type AircraftIconType =
  | "fighter"
  | "bomber"
  | "transport_mil"
  | "helicopter"
  | "uav"
  | "military_unknown"
  | "civilian";

// Callsigns are a weak hint, not identity. Only airlift-specific prefixes count as
// transport evidence; fighter/helicopter names (VIPER, RAPTOR, HAWK, COBRA) do not.
const TRANSPORT_CALLSIGN_PREFIXES = ["RCH", "REACH", "EVAC"];

// ICAO type designators with an unambiguous role.
const TRANSPORT_TYPES = /^(C17|C5M?|C130|C30J|C160|A400|KC10|KC135|K35R|KC46|A332|C2|IL76|AN12|AN124)$/;
const FIGHTER_TYPES = /^(F5|F15|F16|F18|FA18|F22|F35|EUFI|RFAL|GRIP|TORN|SU27|SU30|SU34|SU35|MG29|MG31|M346)$/;

const ICON_COLORS: Record<AircraftIconType, string> = {
  fighter: "#ef4444",
  bomber: "#ef4444",
  transport_mil: "#c4813a",
  helicopter: "#ef4444",
  uav: "#a855f7",
  military_unknown: "#b8a46a",
  civilian: "#d4cdc0",
};

export function classifyAircraft(
  callsign: string | null,
  isMilitary: boolean,
  aircraftType: string | null,
  altitudeM: number | null,
  velocityMs: number | null,
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

  // Explicit type evidence takes precedence over speed/callsign heuristics.
  if (isMilitary && /^(B52|B1|B2|TU95|TU160)$/.test(at)) return "bomber";

  // Known type codes outrank every heuristic below.
  if (isMilitary && TRANSPORT_TYPES.test(at)) return "transport_mil";
  if (isMilitary && FIGHTER_TYPES.test(at)) return "fighter";

  // Weak hint: airlift callsign prefixes.
  if (isMilitary && TRANSPORT_CALLSIGN_PREFIXES.some((p) => cs.startsWith(p))) return "transport_mil";

  // Fast and high without a type code still looks like a fighter profile.
  if (isMilitary && velocityMs !== null && altitudeM !== null && velocityMs > 200 && altitudeM > 5000) {
    return "fighter";
  }

  // Military upstream flag without any role evidence stays neutral.
  if (isMilitary) return "military_unknown";

  return "civilian";
}

const iconCache = new Map<string, string>();

export function getAircraftTypeIcon(
  type: AircraftIconType,
  headingDeg: number | null,
): string {
  const unknownHeading = headingDeg === null;
  const bucket = unknownHeading ? 0 : ((Math.round(headingDeg / 5) * 5) % 360 + 360) % 360;
  const key = unknownHeading ? `${type}_unknown` : `${type}_${bucket}`;

  const cached = iconCache.get(key);
  if (cached) return cached;

  const size = 24;
  const canvas = document.createElement("canvas");
  canvas.width = size * 2;
  canvas.height = size * 2;
  const ctx = canvas.getContext("2d");
  if (!ctx) return canvas.toDataURL();

  const color = ICON_COLORS[type];

  ctx.scale(2, 2);
  ctx.translate(size / 2, size / 2);
  ctx.rotate((bucket * Math.PI) / 180);

  if (unknownHeading) {
    // No heading known: direction-less ring instead of a nose that points north.
    ctx.beginPath();
    ctx.arc(0, 0, 6, 0, Math.PI * 2);
    ctx.strokeStyle = color;
    ctx.lineWidth = 2;
    ctx.stroke();
    const neutral = canvas.toDataURL();
    iconCache.set(key, neutral);
    return neutral;
  }

  switch (type) {
    case "military_unknown":
      // Neutral diamond: military flag known, role not.
      ctx.beginPath();
      ctx.moveTo(0, -7);
      ctx.lineTo(6, 0);
      ctx.lineTo(0, 7);
      ctx.lineTo(-6, 0);
      ctx.closePath();
      ctx.fillStyle = color;
      ctx.globalAlpha = 0.85;
      ctx.fill();
      break;

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
      // Swept-wing airliner: fuselage, wings and separate tailplane.
      ctx.beginPath();
      ctx.moveTo(0, -10);
      ctx.lineTo(-1.6, -7);
      ctx.lineTo(-1.6, -3);
      ctx.lineTo(-10, 2);
      ctx.lineTo(-10, 4);
      ctx.lineTo(-1.6, 1);
      ctx.lineTo(-1, 7);
      ctx.lineTo(-4, 9);
      ctx.lineTo(-4, 10);
      ctx.lineTo(0, 9);
      ctx.lineTo(4, 10);
      ctx.lineTo(4, 9);
      ctx.lineTo(1, 7);
      ctx.lineTo(1.6, 1);
      ctx.lineTo(10, 4);
      ctx.lineTo(10, 2);
      ctx.lineTo(1.6, -3);
      ctx.lineTo(1.6, -7);
      ctx.closePath();
      break;
  }

  ctx.fillStyle = color;
  ctx.strokeStyle = "#071016";
  ctx.lineWidth = 1.6;
  ctx.lineJoin = "round";
  ctx.stroke();
  ctx.fill();
  // A quiet dorsal highlight makes heading legible against land and ocean.
  ctx.strokeStyle = "#ffffff";
  ctx.globalAlpha = 0.65;
  ctx.lineWidth = 0.7;
  ctx.beginPath();
  ctx.moveTo(0, -7);
  ctx.lineTo(0, 5);
  ctx.stroke();

  const dataUrl = canvas.toDataURL();
  iconCache.set(key, dataUrl);
  return dataUrl;
}

export function clearAircraftIconCache(): void {
  iconCache.clear();
}
