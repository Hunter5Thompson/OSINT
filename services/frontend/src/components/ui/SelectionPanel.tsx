import * as Cesium from "cesium";
import type { AircraftTrack, FIRMSHotspot, DatacenterProperties, RefineryProperties } from "../../types";

export type Selected =
  | { type: "firms"; data: FIRMSHotspot }
  | { type: "aircraft"; data: AircraftTrack }
  | { type: "datacenter"; data: DatacenterProperties }
  | { type: "refinery"; data: RefineryProperties };

interface SelectionPanelProps {
  selected: Selected | null;
  onClose: () => void;
  viewer: Cesium.Viewer | null;
}

export function SelectionPanel({ selected, onClose, viewer }: SelectionPanelProps) {
  if (!selected) return null;

  return (
    <div className="absolute left-3 bottom-16 w-80 max-h-[40vh] overflow-y-auto bg-black/85 border border-green-500/20 rounded font-mono text-xs z-40 backdrop-blur-sm">
      <div className="flex items-center justify-between px-3 py-2 border-b border-green-500/20 text-green-400 font-bold tracking-wider">
        <span>
          {selected.type === "firms"
            ? "THERMAL ANOMALY"
            : selected.type === "aircraft"
              ? "AIRCRAFT TRACK"
              : selected.type === "datacenter"
                ? "DATACENTER"
                : "OIL REFINERY"}
        </span>
        <button
          aria-label="close"
          onClick={onClose}
          className="text-green-400/60 hover:text-green-400"
        >
          ×
        </button>
      </div>
      <div className="p-3 text-green-300/80 leading-relaxed">
        {selected.type === "firms" ? (
          <FIRMSContent h={selected.data} />
        ) : selected.type === "aircraft" ? (
          <AircraftContent t={selected.data} viewer={viewer} />
        ) : selected.type === "datacenter" ? (
          <DatacenterContent d={selected.data} />
        ) : (
          <RefineryContent r={selected.data} />
        )}
      </div>
    </div>
  );
}

function Row({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex justify-between gap-2 py-0.5">
      <span className="text-green-500/50">{label}</span>
      <span className="text-right">{value}</span>
    </div>
  );
}

function FIRMSContent({ h }: { h: FIRMSHotspot }) {
  return (
    <>
      {h.possible_explosion && (
        <div className="mb-2 px-2 py-1 bg-red-900/40 border border-red-500/40 text-red-300 rounded text-center tracking-widest">
          POSSIBLE EXPLOSION
        </div>
      )}
      <Row label="FRP" value={`${h.frp.toFixed(1)} MW`} />
      <Row label="BRIGHTNESS" value={`${h.brightness.toFixed(1)} K`} />
      <Row label="CONFIDENCE" value={h.confidence || "-"} />
      <Row label="SATELLITE" value={h.satellite} />
      <Row label="ACQ" value={`${h.acq_date} ${h.acq_time}`} />
      <Row label="REGION" value={h.bbox_name} />
      <Row label="POSITION" value={`${h.latitude.toFixed(4)}, ${h.longitude.toFixed(4)}`} />
      <a
        href={h.firms_map_url}
        target="_blank"
        rel="noreferrer"
        className="block mt-2 text-center text-cyan-300 hover:text-cyan-200 underline"
      >
        View on FIRMS Map
      </a>
    </>
  );
}

function DatacenterContent({ d }: { d: DatacenterProperties }) {
  return (
    <>
      <div className="mb-1 text-cyan-300 font-bold">{d.name}</div>
      <Row label="OPERATOR" value={d.operator} />
      <Row label="TIER" value={d.tier.toUpperCase()} />
      <Row label="CAPACITY" value={d.capacity_mw != null ? `${d.capacity_mw} MW` : "—"} />
      <Row label="COUNTRY" value={d.country} />
      <Row label="CITY" value={d.city} />
    </>
  );
}

function RefineryContent({ r }: { r: RefineryProperties }) {
  const fmtCapacity = (bpd: number): string => {
    if (bpd >= 1_000_000) return `${(bpd / 1_000_000).toFixed(2)}M bbl/day`;
    return `${(bpd / 1_000).toFixed(0)}K bbl/day`;
  };

  return (
    <>
      <div className="mb-1 text-amber-300 font-bold">{r.name}</div>
      <Row label="OPERATOR" value={r.operator} />
      <Row label="CAPACITY" value={fmtCapacity(r.capacity_bpd)} />
      <Row label="COUNTRY" value={r.country} />
      <Row label="STATUS" value={r.status.toUpperCase()} />
    </>
  );
}

function AircraftContent({ t, viewer }: { t: AircraftTrack; viewer: Cesium.Viewer | null }) {
  const last = t.points[t.points.length - 1];

  const onCenter = () => {
    if (!viewer || viewer.isDestroyed() || t.points.length === 0) return;
    const cartesians = t.points.map((p) =>
      Cesium.Cartesian3.fromDegrees(p.lon, p.lat, p.altitude_m ?? 0),
    );
    const sphere = Cesium.BoundingSphere.fromPoints(cartesians);
    viewer.camera.flyToBoundingSphere(sphere, { duration: 1.2 });
  };

  return (
    <>
      <div className="mb-1 text-green-300 font-bold">
        {t.callsign || t.icao24}
      </div>
      <div className="mb-2 text-green-500/60">
        {[t.type_code, t.military_branch, t.registration].filter(Boolean).join(" • ") || "—"}
      </div>
      <Row label="ICAO24" value={t.icao24} />
      <Row label="POINTS" value={`${t.points.length} points`} />
      {last && (
        <>
          <Row label="POSITION" value={`${last.lat.toFixed(4)}, ${last.lon.toFixed(4)}`} />
          <Row label="ALTITUDE" value={last.altitude_m != null ? `${last.altitude_m.toFixed(0)} m` : "—"} />
          <Row label="SPEED" value={last.speed_ms != null ? `${last.speed_ms.toFixed(0)} m/s` : "—"} />
          <Row label="HEADING" value={last.heading != null ? `${last.heading.toFixed(0)}°` : "—"} />
        </>
      )}
      <button
        onClick={onCenter}
        className="block w-full mt-2 px-2 py-1 bg-cyan-900/30 border border-cyan-500/40 text-cyan-300 rounded hover:bg-cyan-900/50"
      >
        Center on track
      </button>
    </>
  );
}
