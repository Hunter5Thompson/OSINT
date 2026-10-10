import * as Cesium from "cesium";
import {
  type LayerVisibility,
  type FIRMSHotspot,
  type DatacenterGeoJSON,
  type RefineryGeoJSON,
  type EONETEvent,
  type GDACSEvent,
  type TimeWindowQuery,
  type WindowTrackSample,
  type IntelEvent,
  type Aircraft,
} from "../../types";
import { FlightLayer } from "../layers/FlightLayer";
import type { FlightDensity } from "../layers/flightDensity";
import type { EventDensity } from "../layers/eventDensity";
import {
  type Dispatch,
  type SetStateAction,
  useMemo,
} from "react";
import {
  type Selected,
} from "./InspectorPanel";
import {
  type SpatialQueryRef,
} from "../../spatial/contracts";
import {
  useSpotlight,
} from "../globe/spotlight/SpotlightContext";

export function FlightLayerBridge({ viewer, flights, visible, onDensity }: {
  viewer: Cesium.Viewer | null;
  flights: Aircraft[];
  visible: boolean;
  onDensity: (density: FlightDensity) => void;
}) {
  const { focusTarget } = useSpotlight();
  const pin = focusTarget?.kind === "circle" && focusTarget.sourcePin?.layer === "flights"
    ? focusTarget.sourcePin.entityId : undefined;
  return <FlightLayer viewer={viewer} flights={flights} visible={visible} pinnedId={pin} onDensity={onDensity} />;
}
import {
  Graticule,
} from "../globe/visual-layers/Graticule";
import {
  FIRMSLayer,
} from "../layers/FIRMSLayer";
import {
  DatacenterLayer,
} from "../layers/DatacenterLayer";
import {
  RefineryLayer,
} from "../layers/RefineryLayer";
import {
  EONETLayer,
} from "../layers/EONETLayer";
import {
  GDACSLayer,
} from "../layers/GDACSLayer";
import {
  useTime,
} from "../../state/TimeContext";
import {
  useAircraftTracks,
} from "../../hooks/useAircraftTracks";
import {
  useTimeWindow,
} from "../../hooks/useTimeWindow";
import {
  type MilTrackRender,
  fromLiveTrack,
  fromWindowTrack,
} from "../layers/milTrackAdapter";
import {
  MilAircraftLayer,
} from "../layers/MilAircraftLayer";
import {
  EventLayer,
} from "../layers/EventLayer";

// ── GlobeChildren ─────────────────────────────────────────────────────────────
// Inner component that lives inside <SpotlightProvider> so it can call
// useSpotlight(). Mounts the 6 onSelect-prop layers and EntityClickHandler.
// The other layers (tag-pick) dispatch Spotlight via EntityClickHandler already.

interface GlobeChildrenProps {
  viewer: Cesium.Viewer | null;
  layers: LayerVisibility;
  setSelected: Dispatch<SetStateAction<Selected | null>>;
  firmsHotspots: FIRMSHotspot[];
  selectedWindow: { tStart: string; tEnd: string };
  datacenterData: DatacenterGeoJSON | null;
  refineryData: RefineryGeoJSON | null;
  eonetEvents: EONETEvent[];
  gdacsEvents: GDACSEvent[];
  chronikSpatialScope: SpatialQueryRef | null | undefined;
  scopeGeneration: number;
}

export function GlobeChildren({
  viewer,
  layers,
  setSelected,
  firmsHotspots,
  selectedWindow,
  datacenterData,
  refineryData,
  eonetEvents,
  gdacsEvents,
  chronikSpatialScope,
  scopeGeneration,
}: GlobeChildrenProps) {
  const { dispatch: dispatchSpotlight } = useSpotlight();

  return (
    <>
      <Graticule viewer={viewer} />
      <FIRMSLayer
        viewer={viewer}
        hotspots={firmsHotspots}
        visible={layers.firmsHotspots}
        onSelect={(hotspot) => {
          setSelected({ type: "firms", data: hotspot });
          dispatchSpotlight({
            type: "set",
            target: {
              kind: "circle",
              trigger: "pin",
              center: { lon: hotspot.longitude, lat: hotspot.latitude },
              radius: 1,
              altitude: 0,
              label: `FIRMS hotspot ${hotspot.id}`.trim(),
              sourcePin: { layer: "firmsHotspots", entityId: String(hotspot.id) },
            },
          });
        }}
      />
      <MilTrackSource
        viewer={viewer}
        layers={layers}
        selectedWindow={selectedWindow}
        setSelected={setSelected}
        spatialScope={chronikSpatialScope}
        scopeGeneration={scopeGeneration}
      />
      <DatacenterLayer
        viewer={viewer}
        datacenters={datacenterData}
        visible={layers.datacenters}
        onSelect={(datacenter) => {
          setSelected({ type: "datacenter", data: datacenter });
          if (datacenter.latitude != null && datacenter.longitude != null) {
            dispatchSpotlight({
              type: "set",
              target: {
                kind: "circle",
                trigger: "pin",
                center: { lon: datacenter.longitude, lat: datacenter.latitude },
                radius: 1,
                altitude: 0,
                label: datacenter.name,
                sourcePin: { layer: "datacenters", entityId: datacenter.name },
              },
            });
          }
        }}
      />
      <RefineryLayer
        viewer={viewer}
        refineries={refineryData}
        visible={layers.refineries}
        onSelect={(refinery) => {
          setSelected({ type: "refinery", data: refinery });
          if (refinery.latitude != null && refinery.longitude != null) {
            dispatchSpotlight({
              type: "set",
              target: {
                kind: "circle",
                trigger: "pin",
                center: { lon: refinery.longitude, lat: refinery.latitude },
                radius: 1,
                altitude: 0,
                label: refinery.name,
                sourcePin: { layer: "refineries", entityId: refinery.name },
              },
            });
          }
        }}
      />
      <EONETLayer
        viewer={viewer}
        events={eonetEvents}
        visible={layers.eonet}
        onSelect={(event) => {
          setSelected({ type: "eonet", data: event });
          dispatchSpotlight({
            type: "set",
            target: {
              kind: "circle",
              trigger: "pin",
              center: { lon: event.longitude, lat: event.latitude },
              radius: 1,
              altitude: 0,
              label: event.title ?? event.id,
              sourcePin: { layer: "eonet", entityId: event.id },
            },
          });
        }}
      />
      <GDACSLayer
        viewer={viewer}
        events={gdacsEvents}
        visible={layers.gdacs}
        onSelect={(event) => {
          setSelected({ type: "gdacs", data: event });
          dispatchSpotlight({
            type: "set",
            target: {
              kind: "circle",
              trigger: "pin",
              center: { lon: event.longitude, lat: event.latitude },
              radius: 1,
              altitude: 0,
              label: event.event_name ?? event.id,
              sourcePin: { layer: "gdacs", entityId: event.id },
            },
          });
        }}
      />
    </>
  );
}

// ── MilTrackSource ─────────────────────────────────────────────────────────────
// Isolated useTime() consumer so only this tiny node re-renders at the throttled
// (~4 Hz) cursor cadence — not the whole GlobeChildren subtree. Selects the mil
// track source by mode (live = useAircraftTracks; replay = windowed contract) and
// normalizes both shapes through the canonical adapter before the layer/inspector.

function MilTrackSource({
  viewer,
  layers,
  selectedWindow,
  setSelected,
  spatialScope,
  scopeGeneration,
}: {
  viewer: Cesium.Viewer | null;
  layers: LayerVisibility;
  selectedWindow: { tStart: string; tEnd: string };
  setSelected: Dispatch<SetStateAction<Selected | null>>;
  spatialScope: SpatialQueryRef | null | undefined;
  scopeGeneration: number;
}) {
  const { dispatch: dispatchSpotlight } = useSpotlight();
  const { mode, getTimeMs, discontinuityEpoch } = useTime();

  const { tracks: liveTracks } = useAircraftTracks(layers.milAircraft && mode === "live");

  const replayQuery = useMemo<TimeWindowQuery>(
    () => ({
      tStart: selectedWindow.tStart,
      tEnd: selectedWindow.tEnd,
      domain: "movements",
      tier: "fine",
      movementKind: "mil_aircraft",
      ...(spatialScope === undefined || spatialScope === null ? {} : { spatialScope }),
    }),
    [selectedWindow.tStart, selectedWindow.tEnd, spatialScope],
  );
  const { data: replayData } = useTimeWindow(
    layers.milAircraft && mode === "replay" && spatialScope !== null,
    replayQuery,
    0,
    scopeGeneration,
  );

  const milRender = useMemo<MilTrackRender[]>(
    () =>
      mode === "live"
        ? liveTracks.map(fromLiveTrack)
        : (replayData?.samples ?? [])
            .filter((s): s is WindowTrackSample => s.kind === "track")
            .map(fromWindowTrack),
    [mode, liveTracks, replayData],
  );

  return (
    <MilAircraftLayer
      viewer={viewer}
      tracks={milRender}
      visible={layers.milAircraft}
      getTimeMs={getTimeMs}
      discontinuityEpoch={discontinuityEpoch}
      onSelect={(track) => {
        setSelected({ type: "aircraft", data: track });
        const lastPoint = track.points[track.points.length - 1];
        if (lastPoint) {
          dispatchSpotlight({
            type: "set",
            target: {
              kind: "circle",
              trigger: "pin",
              center: { lon: lastPoint.lon, lat: lastPoint.lat },
              radius: 1,
              altitude: 0,
              label: track.callsign ?? track.icao24,
              sourcePin: { layer: "milAircraft", entityId: track.icao24 },
            },
          });
        }
      }}
    />
  );
}

// ── EventLayerBridge ────────────────────────────────────────────────────────────
// Tiny useTime() consumer so EventLayer gets the live clock (getTimeMs) for the §7
// temporal fade without making WorldviewPage a 4Hz consumer.
export function EventLayerBridge({
  viewer,
  events,
  visible,
  window,
  onDensity,
}: {
  viewer: Cesium.Viewer | null;
  events: IntelEvent[];
  visible: boolean;
  window: { startMs: number; endMs: number } | null;
  onDensity?: (density: EventDensity) => void;
}) {
  const { getTimeMs } = useTime();
  const { focusTarget } = useSpotlight();
  const pin = focusTarget?.kind === "circle" && focusTarget.sourcePin?.layer === "events"
    ? focusTarget.sourcePin.entityId : undefined;
  return (
    <EventLayer
      viewer={viewer}
      events={events}
      visible={visible}
      getTimeMs={getTimeMs}
      window={window}
      pinnedId={pin}
      onDensity={onDensity}
    />
  );
}
