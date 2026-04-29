import { useCallback, useEffect, useState, type CSSProperties } from "react";
import * as Cesium from "cesium";

import { GlobeViewer } from "../globe/GlobeViewer";
import { FIRMSLayer } from "../layers/FIRMSLayer";
import { EONETLayer } from "../layers/EONETLayer";
import { GDACSLayer } from "../layers/GDACSLayer";
import { LeaderCallout } from "../hlidskjalf/LeaderCallout";
import { SectionHeading } from "../hlidskjalf/SectionHeading";
import { formatCoords } from "../../lib/coords";
import { useFIRMSHotspots } from "../../hooks/useFIRMSHotspots";
import { useEONETEvents } from "../../hooks/useEONETEvents";
import { useGDACSEvents } from "../../hooks/useGDACSEvents";
import type { Incident } from "../../types/incident";

export interface TheatreQuadrantProps {
  incident: Incident | null;
  cesiumToken: string;
}

export function TheatreQuadrant({ incident, cesiumToken }: TheatreQuadrantProps) {
  const [viewer, setViewer] = useState<Cesium.Viewer | null>(null);
  const handleViewerReady = useCallback((created: Cesium.Viewer) => setViewer(created), []);

  const showFIRMS = Boolean(incident?.layer_hints.includes("firmsHotspots"));
  const showEONET = Boolean(incident?.layer_hints.includes("eonet"));
  const showGDACS = Boolean(incident?.layer_hints.includes("gdacs"));

  const { hotspots: firms } = useFIRMSHotspots(showFIRMS);
  const { events: eonet } = useEONETEvents(showEONET);
  const { events: gdacs } = useGDACSEvents(showGDACS);

  // Fly to incident.
  useEffect(() => {
    if (!viewer || !incident) return;
    const [lat, lon] = incident.coords;
    viewer.camera.flyTo({
      destination: Cesium.Cartesian3.fromDegrees(lon, lat, 850_000),
      duration: 1.4,
    });
  }, [viewer, incident]);

  if (!incident) {
    return (
      <section data-quadrant="theatre" style={emptyStyle}>
        <SectionHeading number="I" label="Theatre" hair />
        <div style={emptyMessageStyle}>
          <span>§ no active incident · standing watch</span>
        </div>
      </section>
    );
  }

  return (
    <section data-quadrant="theatre" style={{ position: "relative", overflow: "hidden", height: "100%" }}>
      <div style={{ position: "absolute", inset: 0 }}>
        <GlobeViewer
          onViewerReady={handleViewerReady}
          cesiumToken={cesiumToken}
          activeShader="none"
          showCountryBorders
          showCityBuildings={false}
        />
      </div>
      <FIRMSLayer viewer={viewer} hotspots={firms} visible={showFIRMS} onSelect={() => {}} />
      <EONETLayer viewer={viewer} events={eonet} visible={showEONET} onSelect={() => {}} />
      <GDACSLayer viewer={viewer} events={gdacs} visible={showGDACS} onSelect={() => {}} />

      {/* Heading floats in the top-left corner */}
      <div style={{ position: "absolute", top: 12, left: 12, zIndex: 5 }}>
        <SectionHeading number="I" label={`Theatre · ${incident.location || "—"}`} hair />
      </div>

      {/* Leader callouts (v1: fixed corner placement) */}
      <div style={{ position: "absolute", top: 60, right: 16, zIndex: 5 }}>
        <LeaderCallout
          eyebrow={incident.kind.replace(".", " · ")}
          value={incident.severity.toUpperCase()}
          sub={formatCoords(incident.coords, 2)}
          leader={{ from: "left", deltaPx: 90 }}
          tone="sentinel"
        />
      </div>
      <div style={{ position: "absolute", bottom: 16, left: 16, zIndex: 5 }}>
        <LeaderCallout
          eyebrow="Sources"
          value={String(incident.sources.length)}
          sub="raw feeds engaged"
          leader={{ from: "right", deltaPx: 90 }}
          tone="amber"
        />
      </div>
    </section>
  );
}

const emptyStyle: CSSProperties = {
  position: "relative",
  display: "flex",
  flexDirection: "column",
  padding: "1rem",
  height: "100%",
  background:
    "radial-gradient(circle at 50% 50%, rgba(196,129,58,0.06) 0%, rgba(11,10,8,0) 60%)",
};

const emptyMessageStyle: CSSProperties = {
  flex: 1,
  display: "flex",
  alignItems: "center",
  justifyContent: "center",
  fontFamily: '"Instrument Serif", serif',
  fontStyle: "italic",
  fontSize: "16px",
  color: "var(--ash)",
};
