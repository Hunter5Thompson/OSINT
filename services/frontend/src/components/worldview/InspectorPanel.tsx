import type { CSSProperties } from "react";
import type * as Cesium from "cesium";
import type { FIRMSHotspot } from "../../types";
import { OverlayPanel } from "../hlidskjalf/OverlayPanel";

export type Selected =
  | { type: "firms"; data: FIRMSHotspot }
  | { type: "aircraft"; data: { icao24?: string; callsign?: string | null; latitude?: number; longitude?: number; altitude_m?: number } }
  | { type: "datacenter"; data: { name?: string; operator?: string; latitude?: number; longitude?: number } }
  | { type: "refinery"; data: { name?: string; capacity_bpd?: number; latitude?: number; longitude?: number } }
  | { type: "eonet"; data: { title?: string; category?: string; latitude?: number; longitude?: number } }
  | { type: "gdacs"; data: { title?: string; severity?: string | number; latitude?: number; longitude?: number } };

export interface InspectorPanelProps {
  selected: Selected | null;
  onClose: () => void;
  viewer: Cesium.Viewer | null;
}

const labelStyle: CSSProperties = {
  fontFamily: "'Hanken Grotesk', sans-serif",
  fontSize: 10,
  letterSpacing: "0.22em",
  textTransform: "uppercase",
  color: "var(--ash)",
};

const valueStyle: CSSProperties = {
  fontFamily: "'Martian Mono', monospace",
  fontSize: 11,
  color: "var(--bone)",
  marginTop: 2,
  marginBottom: 10,
};

const titleStyle: CSSProperties = {
  fontFamily: "'Instrument Serif', serif",
  fontStyle: "italic",
  fontSize: 18,
  color: "var(--parchment)",
  marginBottom: 12,
};

function coords(lat?: number, lon?: number): string {
  if (!Number.isFinite(lat) || !Number.isFinite(lon)) return "—";
  const ns = (lat as number) >= 0 ? "N" : "S";
  const ew = (lon as number) >= 0 ? "E" : "W";
  return `${Math.abs(lat as number).toFixed(3)}° ${ns} · ${Math.abs(lon as number).toFixed(3)}° ${ew}`;
}

function Body({ selected }: { selected: Selected }) {
  switch (selected.type) {
    case "firms": {
      const h = selected.data;
      return (
        <>
          <div style={titleStyle}>FIRMS hotspot · {h.satellite}</div>
          <div style={labelStyle}>§ coords</div>
          <div style={valueStyle}>{coords(h.latitude, h.longitude)}</div>
          <div style={labelStyle}>§ FRP / brightness</div>
          <div style={valueStyle}>{h.frp.toFixed(1)} MW · {h.brightness.toFixed(1)} K · {h.confidence}</div>
          <div style={labelStyle}>§ acquired</div>
          <div style={valueStyle}>{h.acq_date} {h.acq_time}Z</div>
          {h.possible_explosion ? (
            <>
              <div style={labelStyle}>§ flag</div>
              <div style={{ ...valueStyle, color: "var(--sentinel)" }}>possible explosion</div>
            </>
          ) : null}
        </>
      );
    }
    case "aircraft": {
      const a = selected.data;
      return (
        <>
          <div style={titleStyle}>{a.callsign ?? a.icao24 ?? "aircraft"}</div>
          <div style={labelStyle}>§ icao24</div>
          <div style={valueStyle}>{a.icao24 ?? "—"}</div>
          <div style={labelStyle}>§ coords</div>
          <div style={valueStyle}>{coords(a.latitude, a.longitude)}</div>
          <div style={labelStyle}>§ altitude</div>
          <div style={valueStyle}>{Number.isFinite(a.altitude_m) ? `${a.altitude_m} m` : "—"}</div>
        </>
      );
    }
    case "datacenter": {
      const d = selected.data;
      return (
        <>
          <div style={titleStyle}>{d.name ?? "datacenter"}</div>
          <div style={labelStyle}>§ operator</div>
          <div style={valueStyle}>{d.operator ?? "—"}</div>
          <div style={labelStyle}>§ coords</div>
          <div style={valueStyle}>{coords(d.latitude, d.longitude)}</div>
        </>
      );
    }
    case "refinery": {
      const r = selected.data;
      return (
        <>
          <div style={titleStyle}>{r.name ?? "refinery"}</div>
          <div style={labelStyle}>§ capacity</div>
          <div style={valueStyle}>{r.capacity_bpd ? `${r.capacity_bpd.toLocaleString()} bpd` : "—"}</div>
          <div style={labelStyle}>§ coords</div>
          <div style={valueStyle}>{coords(r.latitude, r.longitude)}</div>
        </>
      );
    }
    case "eonet": {
      const e = selected.data;
      return (
        <>
          <div style={titleStyle}>{e.title ?? "EONET event"}</div>
          <div style={labelStyle}>§ category</div>
          <div style={valueStyle}>{e.category ?? "—"}</div>
          <div style={labelStyle}>§ coords</div>
          <div style={valueStyle}>{coords(e.latitude, e.longitude)}</div>
        </>
      );
    }
    case "gdacs": {
      const g = selected.data;
      return (
        <>
          <div style={titleStyle}>{g.title ?? "GDACS event"}</div>
          <div style={labelStyle}>§ severity</div>
          <div style={valueStyle}>{g.severity ?? "—"}</div>
          <div style={labelStyle}>§ coords</div>
          <div style={valueStyle}>{coords(g.latitude, g.longitude)}</div>
        </>
      );
    }
  }
}

export function InspectorPanel({ selected, onClose }: InspectorPanelProps) {
  return (
    <OverlayPanel
      paragraph="III"
      label="Inspector"
      variant={selected ? "expanded" : "hidden"}
      onClose={onClose}
      width={360}
    >
      {selected ? <Body selected={selected} /> : null}
    </OverlayPanel>
  );
}
