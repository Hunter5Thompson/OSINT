/**
 * Ship type-specific canvas icon factory.
 *
 * Classification: AIS ship_type numeric codes (IMO standard).
 */

export type ShipIconType = "warship" | "carrier" | "submarine" | "tanker" | "cargo" | "civilian";

export const ICON_COLORS: Record<ShipIconType, string> = {
  warship: "#ef4444",
  carrier: "#ef4444",
  submarine: "#ef4444",
  tanker: "#eab308",
  cargo: "#4fc3f7",
  civilian: "#d4cdc0",
};

export function classifyShip(shipType: number, name: string | null): ShipIconType {
  // AIS ship_type 35 = military
  if (shipType === 35) {
    const n = (name ?? "").toUpperCase();
    if (n.includes("CVN") || n.includes("CARRIER") || n.includes("NIMITZ") || n.includes("FORD")) return "carrier";
    if (n.includes("SSN") || n.includes("SSBN") || n.includes("SUBMARINE")) return "submarine";
    return "warship";
  }

  // Tanker: 80-89
  if (shipType >= 80 && shipType <= 89) return "tanker";

  // Cargo: 70-79
  if (shipType >= 70 && shipType <= 79) return "cargo";

  return "civilian";
}

const iconCache = new Map<string, HTMLCanvasElement>();

export function getShipTypeIcon(
  type: ShipIconType,
  courseDeg: number,
): HTMLCanvasElement {
  const bucket = ((Math.round((courseDeg || 0) / 5) * 5) % 360 + 360) % 360;
  const key = `${type}_${bucket}`;

  const cached = iconCache.get(key);
  if (cached) return cached;

  const size = 20;
  const canvas = document.createElement("canvas");
  canvas.width = size;
  canvas.height = size;
  const ctx = canvas.getContext("2d");
  if (!ctx) return canvas;

  const color = ICON_COLORS[type];

  ctx.translate(size / 2, size / 2);
  ctx.rotate((bucket * Math.PI) / 180);

  switch (type) {
    case "warship":
      // Hull + superstructure + mast
      ctx.beginPath();
      ctx.moveTo(0, -8);
      ctx.lineTo(-4, 0);
      ctx.lineTo(-5, 6);
      ctx.lineTo(5, 6);
      ctx.lineTo(4, 0);
      ctx.closePath();
      ctx.fillStyle = color;
      ctx.globalAlpha = 0.9;
      ctx.fill();
      // Mast
      ctx.beginPath();
      ctx.moveTo(0, -8);
      ctx.lineTo(0, -4);
      ctx.strokeStyle = color;
      ctx.lineWidth = 1.5;
      ctx.stroke();
      break;

    case "carrier":
      // Flat deck + island
      ctx.beginPath();
      ctx.moveTo(0, -8);
      ctx.lineTo(-5, -2);
      ctx.lineTo(-5, 7);
      ctx.lineTo(5, 7);
      ctx.lineTo(5, -2);
      ctx.closePath();
      ctx.fillStyle = color;
      ctx.globalAlpha = 0.9;
      ctx.fill();
      // Island
      ctx.fillRect(3, -1, 2, 4);
      break;

    case "submarine":
      // Cigar hull + conning tower
      ctx.beginPath();
      ctx.ellipse(0, 1, 3, 8, 0, 0, Math.PI * 2);
      ctx.fillStyle = color;
      ctx.globalAlpha = 0.8;
      ctx.fill();
      // Conning tower
      ctx.fillRect(-1.5, -3, 3, 3);
      break;

    case "tanker":
      // Hull + round tanks
      ctx.beginPath();
      ctx.moveTo(0, -8);
      ctx.lineTo(-4, 0);
      ctx.lineTo(-4, 7);
      ctx.lineTo(4, 7);
      ctx.lineTo(4, 0);
      ctx.closePath();
      ctx.fillStyle = color;
      ctx.globalAlpha = 0.7;
      ctx.fill();
      // Tank circles
      ctx.globalAlpha = 0.5;
      ctx.beginPath();
      ctx.arc(0, 1, 2, 0, Math.PI * 2);
      ctx.fill();
      ctx.beginPath();
      ctx.arc(0, 5, 2, 0, Math.PI * 2);
      ctx.fill();
      break;

    case "cargo":
      // Hull + container stacks
      ctx.beginPath();
      ctx.moveTo(0, -8);
      ctx.lineTo(-5, 0);
      ctx.lineTo(-5, 7);
      ctx.lineTo(5, 7);
      ctx.lineTo(5, 0);
      ctx.closePath();
      ctx.fillStyle = color;
      ctx.globalAlpha = 0.8;
      ctx.fill();
      // Container rectangles
      ctx.globalAlpha = 0.5;
      ctx.fillRect(-3, 0, 6, 3);
      ctx.fillRect(-3, 4, 6, 2);
      break;

    case "civilian":
    default:
      // Small hull
      ctx.beginPath();
      ctx.moveTo(0, -6);
      ctx.lineTo(-3, 2);
      ctx.lineTo(-3, 5);
      ctx.lineTo(3, 5);
      ctx.lineTo(3, 2);
      ctx.closePath();
      ctx.fillStyle = color;
      ctx.globalAlpha = 0.8;
      ctx.fill();
      break;
  }

  ctx.globalAlpha = 1.0;
  ctx.strokeStyle = color;
  ctx.lineWidth = 0.5;
  ctx.stroke();

  iconCache.set(key, canvas);
  return canvas;
}
