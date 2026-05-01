import type { CSSProperties } from "react";
import * as Cesium from "cesium";
import type {
  AircraftTrack,
  DatacenterProperties,
  EONETEvent,
  FIRMSHotspot,
  GDACSEvent,
  RefineryProperties,
} from "../../types";
import { OverlayPanel } from "../hlidskjalf/OverlayPanel";
import type { CountryHit } from "../globe/hooks/useCountryHitTest";

export type Selected =
  | { type: "firms"; data: FIRMSHotspot }
  | { type: "aircraft"; data: AircraftTrack }
  | { type: "datacenter"; data: DatacenterProperties }
  | { type: "refinery"; data: RefineryProperties }
  | { type: "eonet"; data: EONETEvent }
  | { type: "gdacs"; data: GDACSEvent }
  | { type: "country"; data: CountryHit };

export interface InspectorPanelProps {
  selected: Selected | null;
  onClose: () => void;
  viewer: Cesium.Viewer | null;
}

const labelStyle: CSSProperties = {
  fontFamily: '"Martian Mono", ui-monospace, monospace',
  fontSize: "0.62rem",
  letterSpacing: "0.14em",
  textTransform: "uppercase",
  color: "var(--ash)",
};

const valueStyle: CSSProperties = {
  marginTop: "0.2rem",
  marginBottom: "0.65rem",
  color: "var(--bone)",
  fontSize: "0.8rem",
};

const titleStyle: CSSProperties = {
  marginBottom: "0.8rem",
  color: "var(--parchment)",
  fontFamily: '"Instrument Serif", "Times New Roman", serif',
  fontStyle: "italic",
  fontSize: "1.14rem",
};

const imageStyle: CSSProperties = {
  width: "100%",
  aspectRatio: "16 / 9",
  objectFit: "cover",
  border: "1px solid var(--granite)",
  marginBottom: "0.75rem",
  background: "rgba(255,255,255,0.04)",
};

const sourceLinkStyle: CSSProperties = {
  display: "inline-block",
  marginTop: "0.2rem",
  color: "var(--signal)",
  fontFamily: '"Martian Mono", ui-monospace, monospace',
  fontSize: "0.65rem",
  letterSpacing: "0.1em",
  textTransform: "uppercase",
  textDecoration: "none",
};

function formatCoord(lat: number, lon: number): string {
  const ns = lat >= 0 ? "N" : "S";
  const ew = lon >= 0 ? "E" : "W";
  return `${Math.abs(lat).toFixed(3)} ${ns}, ${Math.abs(lon).toFixed(3)} ${ew}`;
}

function Property({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div style={labelStyle}>{label}</div>
      <div style={valueStyle}>{value}</div>
    </div>
  );
}

function formatFacilityType(value: string | undefined): string {
  return (value || "refinery").replaceAll("_", " ");
}

function Specs({ specs }: { specs: string[] | undefined }) {
  if (!specs?.length) return null;
  return (
    <div>
      <div style={labelStyle}>§ Specs</div>
      <ul
        style={{
          margin: "0.2rem 0 0.65rem",
          paddingLeft: "1rem",
          color: "var(--bone)",
          fontSize: "0.78rem",
          lineHeight: 1.45,
        }}
      >
        {specs.map((spec) => (
          <li key={spec}>{spec}</li>
        ))}
      </ul>
    </div>
  );
}

function AircraftInspector({
  track,
  viewer,
}: {
  track: AircraftTrack;
  viewer: Cesium.Viewer | null;
}) {
  const lastPoint = track.points[track.points.length - 1];

  const handleCenter = () => {
    if (!viewer || viewer.isDestroyed() || !lastPoint) return;
    viewer.camera.flyTo({
      destination: Cesium.Cartesian3.fromDegrees(lastPoint.lon, lastPoint.lat, 500_000),
      duration: 1.2,
    });
  };

  return (
    <>
      <div style={titleStyle}>{track.callsign || track.icao24}</div>
      <Property label="§ ICAO24" value={track.icao24} />
      <Property label="§ Track Points" value={`${track.points.length}`} />
      <Property
        label="§ Last Position"
        value={lastPoint ? formatCoord(lastPoint.lat, lastPoint.lon) : "-"}
      />
      <Property
        label="§ Altitude"
        value={lastPoint?.altitude_m != null ? `${Math.round(lastPoint.altitude_m)} m` : "-"}
      />
      <button
        type="button"
        onClick={handleCenter}
        style={{
          marginTop: "0.45rem",
          width: "100%",
          border: "1px solid var(--granite)",
          background: "transparent",
          color: "var(--stone)",
          padding: "0.5rem 0.65rem",
          cursor: "pointer",
          fontFamily: '"Martian Mono", ui-monospace, monospace',
          fontSize: "0.65rem",
          letterSpacing: "0.1em",
          textTransform: "uppercase",
        }}
      >
        Center On Track
      </button>
    </>
  );
}

function InspectorBody({ selected, viewer }: { selected: Selected; viewer: Cesium.Viewer | null }) {
  switch (selected.type) {
    case "firms": {
      const h = selected.data;
      return (
        <>
          <div style={titleStyle}>{`FIRMS hotspot · ${h.satellite}`}</div>
          <Property label="§ Coordinates" value={formatCoord(h.latitude, h.longitude)} />
          <Property label="§ FRP" value={`${h.frp.toFixed(1)} MW`} />
          <Property label="§ Brightness" value={`${h.brightness.toFixed(1)} K`} />
          <Property label="§ Region" value={h.bbox_name || "-"} />
          <Property label="§ Confidence" value={h.confidence || "-"} />
          {h.possible_explosion ? (
            <Property label="§ Flag" value="possible explosion" />
          ) : null}
        </>
      );
    }
    case "aircraft":
      return <AircraftInspector track={selected.data} viewer={viewer} />;
    case "datacenter": {
      const d = selected.data;
      return (
        <>
          <div style={titleStyle}>{d.name}</div>
          <Property label="§ Operator" value={d.operator || "-"} />
          <Property label="§ Tier" value={d.tier || "-"} />
          <Property label="§ Capacity" value={d.capacity_mw != null ? `${d.capacity_mw} MW` : "-"} />
          <Property label="§ Location" value={`${d.city}, ${d.country}`} />
        </>
      );
    }
    case "refinery": {
      const r = selected.data;
      const capacity =
        r.capacity_bpd > 0
          ? `${r.capacity_bpd.toLocaleString()} bpd`
          : r.capacity_text || "-";
      return (
        <>
          {r.image_url ? <img src={r.image_url} alt={r.name} style={imageStyle} /> : null}
          <div style={titleStyle}>{r.name}</div>
          <Property label="§ Type" value={formatFacilityType(r.facility_type)} />
          <Property label="§ Operator" value={r.operator || "-"} />
          <Property label="§ Capacity" value={capacity} />
          {r.latitude != null && r.longitude != null ? (
            <Property label="§ Coordinates" value={formatCoord(r.latitude, r.longitude)} />
          ) : null}
          <Property label="§ Country" value={r.country || "-"} />
          <Property label="§ Status" value={r.status || "-"} />
          <Specs specs={r.specs} />
          {r.source_url ? (
            <a href={r.source_url} target="_blank" rel="noreferrer" style={sourceLinkStyle}>
              Source
            </a>
          ) : null}
        </>
      );
    }
    case "eonet": {
      const e = selected.data;
      return (
        <>
          <div style={titleStyle}>{e.title}</div>
          <Property label="§ Category" value={e.category || "-"} />
          <Property label="§ Status" value={e.status || "-"} />
          <Property label="§ Coordinates" value={formatCoord(e.latitude, e.longitude)} />
          <Property label="§ Date" value={e.event_date.slice(0, 10)} />
        </>
      );
    }
    case "gdacs": {
      const g = selected.data;
      return (
        <>
          <div style={titleStyle}>{g.event_name || g.id}</div>
          <Property label="§ Type" value={g.event_type || "-"} />
          <Property label="§ Alert" value={g.alert_level || "-"} />
          <Property label="§ Severity" value={Number.isFinite(g.severity) ? `${g.severity}` : "-"} />
          <Property label="§ Country" value={g.country || "-"} />
          <Property label="§ Coordinates" value={formatCoord(g.latitude, g.longitude)} />
        </>
      );
    }
    default:
      return null;
  }
}

export function InspectorPanel({ selected, onClose, viewer }: InspectorPanelProps) {
  return (
    <OverlayPanel
      paragraph="III"
      label="Inspector"
      variant={selected ? "expanded" : "hidden"}
      onClose={onClose}
      width={360}
    >
      {selected ? <InspectorBody selected={selected} viewer={viewer} /> : null}
    </OverlayPanel>
  );
}
