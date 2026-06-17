import { useCallback, useEffect, useMemo, useState, type Dispatch, type SetStateAction } from "react";
import { useLocation } from "react-router-dom";
import * as Cesium from "cesium";
import { PerformanceGuard } from "../components/globe/PerformanceGuard";
import { GlobeViewer } from "../components/globe/GlobeViewer";
import { EntityClickHandler } from "../components/globe/EntityClickHandler";
import { FlightLayer } from "../components/layers/FlightLayer";
import { SatelliteLayer } from "../components/layers/SatelliteLayer";
import { EarthquakeLayer } from "../components/layers/EarthquakeLayer";
import { ShipLayer } from "../components/layers/ShipLayer";
import { CCTVLayer } from "../components/layers/CCTVLayer";
import { EventLayer } from "../components/layers/EventLayer";
import { EventCallout } from "../components/time/EventCallout";
import { CableLayer } from "../components/layers/CableLayer";
import { PipelineLayer } from "../components/layers/PipelineLayer";
import { FIRMSLayer } from "../components/layers/FIRMSLayer";
import { MilAircraftLayer } from "../components/layers/MilAircraftLayer";
import { DatacenterLayer } from "../components/layers/DatacenterLayer";
import { RefineryLayer } from "../components/layers/RefineryLayer";
import { EONETLayer } from "../components/layers/EONETLayer";
import { GDACSLayer } from "../components/layers/GDACSLayer";
import { ReconLayer } from "../components/layers/ReconLayer";
import { useReconManifest } from "../lib/recon/manifest";
import { useRecon } from "../state/ReconContext";
import { OverlayPanel } from "../components/hlidskjalf/OverlayPanel";
import { LayersPanel } from "../components/worldview/LayersPanel";
import { SearchPanel } from "../components/worldview/SearchPanel";
import { InspectorPanel, type Selected } from "../components/worldview/InspectorPanel";
import { TickerPanel } from "../components/worldview/TickerPanel";
import { WorldviewHudLoader } from "../components/worldview/WorldviewHudLoader";
import { SpotlightProvider, useSpotlight } from "../components/globe/spotlight/SpotlightContext";
import { SpotlightOverlay } from "../components/globe/spotlight/SpotlightOverlay";
import { HudFrame } from "../components/globe/spotlight/HudFrame";
import { SpotlightCartouche } from "../components/globe/spotlight/SpotlightCartouche";
import { CapitalPulse } from "../components/globe/spotlight/CapitalPulse";
import { useSpotlightTrigger } from "../components/globe/hooks/useSpotlightTrigger";
import { Graticule } from "../components/globe/visual-layers/Graticule";
import { CountryBorders } from "../components/globe/visual-layers/CountryBorders";
import { useFlights } from "../hooks/useFlights";
import { useSatellites } from "../hooks/useSatellites";
import { useEarthquakes } from "../hooks/useEarthquakes";
import { useCables } from "../hooks/useCables";
import { useVessels } from "../hooks/useVessels";
import { usePipelines } from "../hooks/usePipelines";
import { useFIRMSHotspots } from "../hooks/useFIRMSHotspots";
import { useAircraftTracks } from "../hooks/useAircraftTracks";
import { useTimeWindow } from "../hooks/useTimeWindow";
import { TimeProvider, useTime } from "../state/TimeContext";
import { ScrubberMount } from "../components/time/ScrubberMount";
import {
  fromLiveTrack,
  fromWindowTrack,
  type MilTrackRender,
} from "../components/layers/milTrackAdapter";
import { useDatacenters } from "../hooks/useDatacenters";
import { useRefineries } from "../hooks/useRefineries";
import { useEONETEvents } from "../hooks/useEONETEvents";
import { useGDACSEvents } from "../hooks/useGDACSEvents";
import { getConfig } from "../services/api";
import type {
  ClientConfig,
  LayerVisibility,
  ShaderType,
  FIRMSHotspot,
  DatacenterGeoJSON,
  RefineryGeoJSON,
  EONETEvent,
  GDACSEvent,
  IntelEvent,
  TimeWindowQuery,
  TimelineEventDetail,
  TimelineGeoEvent,
  WindowTrackSample,
} from "../types";

type PanelId = "layers" | "search" | "ticker";

type LandingFilter = "hotspots" | "conflict" | "nuntii" | "libri";

const DEFAULT_LAYERS: LayerVisibility = {
  flights: true,
  satellites: true,
  earthquakes: true,
  vessels: false,
  cctv: false,
  events: false,
  cables: false,
  pipelines: false,
  countryBorders: true,
  cityBuildings: true,
  firmsHotspots: true,
  milAircraft: true,
  datacenters: false,
  refineries: false,
  eonet: false,
  gdacs: false,
};

const FILTER_LAYER_PRESETS: Record<LandingFilter, Partial<LayerVisibility>> = {
  hotspots: {
    firmsHotspots: true,
    milAircraft: true,
  },
  conflict: {
    events: true,
    gdacs: true,
    eonet: true,
    earthquakes: true,
  },
  nuntii: {
    events: true,
    gdacs: true,
    eonet: true,
    satellites: true,
  },
  libri: {
    cables: true,
    pipelines: true,
    datacenters: true,
    refineries: true,
    countryBorders: true,
  },
};

function isLayerKey(value: string): value is keyof LayerVisibility {
  return value in DEFAULT_LAYERS;
}

// ── GlobeChildren ─────────────────────────────────────────────────────────────
// Inner component that lives inside <SpotlightProvider> so it can call
// useSpotlight(). Mounts the 6 onSelect-prop layers and EntityClickHandler.
// The other layers (tag-pick) dispatch Spotlight via EntityClickHandler already.

interface GlobeChildrenProps {
  viewer: Cesium.Viewer | null;
  photorealTileset: Cesium.Cesium3DTileset | null;
  layers: LayerVisibility;
  setSelected: Dispatch<SetStateAction<Selected | null>>;
  onSelectEvent: (id: string) => void;
  firmsHotspots: FIRMSHotspot[];
  selectedWindow: { tStart: string; tEnd: string };
  datacenterData: DatacenterGeoJSON | null;
  refineryData: RefineryGeoJSON | null;
  eonetEvents: EONETEvent[];
  gdacsEvents: GDACSEvent[];
}

function GlobeChildren({
  viewer,
  photorealTileset,
  layers,
  setSelected,
  onSelectEvent,
  firmsHotspots,
  selectedWindow,
  datacenterData,
  refineryData,
  eonetEvents,
  gdacsEvents,
}: GlobeChildrenProps) {
  const { dispatch: dispatchSpotlight } = useSpotlight();

  return (
    <>
      <Graticule viewer={viewer} />
      <CountryBorders viewer={viewer} visible={layers.countryBorders} />
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
      <EventClickBridge
        viewer={viewer}
        photorealTileset={photorealTileset}
        onCountrySelect={setSelected}
        onSelectEvent={onSelectEvent}
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
}: {
  viewer: Cesium.Viewer | null;
  layers: LayerVisibility;
  selectedWindow: { tStart: string; tEnd: string };
  setSelected: Dispatch<SetStateAction<Selected | null>>;
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
    }),
    [selectedWindow.tStart, selectedWindow.tEnd],
  );
  const { data: replayData } = useTimeWindow(
    layers.milAircraft && mode === "replay",
    replayQuery,
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
function EventLayerBridge({
  viewer,
  events,
  visible,
  window,
}: {
  viewer: Cesium.Viewer | null;
  events: IntelEvent[];
  visible: boolean;
  window: { startMs: number; endMs: number } | null;
}) {
  const { getTimeMs } = useTime();
  return (
    <EventLayer
      viewer={viewer}
      events={events}
      visible={visible}
      getTimeMs={getTimeMs}
      window={window}
    />
  );
}

// ── EventClickBridge ────────────────────────────────────────────────────────────
// useTime() consumer wrapping EntityClickHandler so an event-dot click opens the callout
// AND seeks to that event's time (pause+seek), per spec §5/§7.
function EventClickBridge({
  viewer,
  photorealTileset,
  onCountrySelect,
  onSelectEvent,
}: {
  viewer: Cesium.Viewer | null;
  photorealTileset: Cesium.Cesium3DTileset | null;
  onCountrySelect: Dispatch<SetStateAction<Selected | null>>;
  onSelectEvent: (id: string) => void;
}) {
  const { pause, seek } = useTime();
  const handleEventSelect = useCallback(
    (id: string, timeIso?: string) => {
      onSelectEvent(id);
      if (timeIso) {
        const t = Date.parse(timeIso);
        if (Number.isFinite(t)) {
          pause();
          seek(t);
        }
      }
    },
    [onSelectEvent, pause, seek],
  );
  return (
    <EntityClickHandler
      viewer={viewer}
      photorealTileset={photorealTileset}
      onCountrySelect={onCountrySelect}
      onEventSelect={handleEventSelect}
    />
  );
}

// ── SearchAcceptHook ───────────────────────────────────────────────────────────
// Inner component that lives inside <SpotlightProvider> so it can call
// useSpotlight(). Mounts SearchPanel and wires onAccept → camera flyTo + Spotlight.

function SearchAcceptHook({
  viewer,
  initialQuery,
}: {
  viewer: Cesium.Viewer | null;
  initialQuery: string;
}) {
  const { dispatch } = useSpotlight();
  return (
    <SearchPanel
      viewer={viewer}
      initialQuery={initialQuery}
      onAccept={(node) => {
        const lat = node.properties?.lat;
        const lon = node.properties?.lon;
        if (typeof lat !== "number" || typeof lon !== "number") return;
        viewer?.camera.flyTo({
          destination: Cesium.Cartesian3.fromDegrees(lon, lat, 400_000),
          duration: 1.6,
        });
        dispatch({
          type: "set",
          target: {
            kind: "circle",
            trigger: "search",
            center: { lon, lat },
            radius: 1,
            altitude: 400_000,
            label: node.name,
            ref: `§ ${node.type}`,
          },
        });
      }}
    />
  );
}

// ── ZoomTriggerHook ────────────────────────────────────────────────────────────
// Inner component that lives inside <SpotlightProvider> so it can call
// useSpotlightTrigger(). Handles camera zoom events and updates Spotlight state.

function ZoomTriggerHook({ viewer }: { viewer: Cesium.Viewer | null }) {
  useSpotlightTrigger(viewer);
  return null;
}

function decodeEntityQuery(value: string | null): string {
  if (!value) return "";
  const decoded = value.trim();
  // Landing deep-links currently use `source:id` payloads; search works best
  // on human-readable names, so only keep the left segment when present.
  return decoded.includes(":") ? (decoded.split(":")[0] ?? "").trim() : decoded.trim();
}

export function WorldviewPage() {
  const location = useLocation();

  const [viewer, setViewer] = useState<Cesium.Viewer | null>(null);
  const [photorealTileset, setPhotorealTileset] = useState<Cesium.Cesium3DTileset | null>(null);
  const [config, setConfig] = useState<ClientConfig | null>(null);
  const [layers, setLayers] = useState<LayerVisibility>(DEFAULT_LAYERS);
  const [activeShader, setActiveShader] = useState<ShaderType>("none");
  const [selected, setSelected] = useState<Selected | null>(null);
  const [searchSeed, setSearchSeed] = useState("");
  const [expandedPanels, setExpandedPanels] = useState<Record<PanelId, boolean>>({
    layers: false,
    search: false,
    ticker: true,
  });
  // Replay window for mil tracks — defaults to the last 6h; an event click on the
  // scrubber scopes it to that event ±3h. Kept as stable state (not derived from
  // the cursor) so replay does not refetch on every cursor tick.
  const [selectedWindow, setSelectedWindow] = useState<{ tStart: string; tEnd: string }>(() => {
    const now = Date.now();
    return {
      tStart: new Date(now - 6 * 3600_000).toISOString(),
      tEnd: new Date(now).toISOString(),
    };
  });

  // § CHRONIK timeline state (lifted from ScrubberMount; see EventClickBridge/EventLayerBridge).
  const [selectedEventId, setSelectedEventId] = useState<string | null>(null);
  const [timelineGeo, setTimelineGeo] = useState<TimelineGeoEvent[]>([]);
  const [timelineWindow, setTimelineWindow] = useState<{ startMs: number; endMs: number } | null>(
    null,
  );
  const handleTimelineData = useCallback(
    (d: { geoEvents: TimelineGeoEvent[]; window: { startMs: number; endMs: number } | null }) => {
      setTimelineGeo(d.geoEvents);
      setTimelineWindow(d.window);
      // Keep the mil-track replay fetch window in sync with the brush (ignored by live
      // mil tracks, which fetch live; consumed by the replay-windowed fetch).
      if (d.window) {
        setSelectedWindow({
          tStart: new Date(d.window.startMs).toISOString(),
          tEnd: new Date(d.window.endMs).toISOString(),
        });
      }
    },
    [],
  );
  // geo_events -> IntelEvent shape (EventLayer requires a non-empty title; title drives
  // _eventData + the label). title = codebook_type ?? id keeps it non-empty (review #2).
  const eventLayerEvents = useMemo<IntelEvent[]>(
    () =>
      timelineGeo.map((g) => ({
        id: g.id,
        title: g.codebook_type ?? g.id,
        codebook_type: g.codebook_type ?? "other",
        severity: g.severity,
        timestamp: g.time,
        location_name: null,
        country: null,
        lat: g.lat,
        lon: g.lon,
      })),
    [timelineGeo],
  );

  const { flights } = useFlights(layers.flights);
  const { satellites } = useSatellites(layers.satellites);
  const { earthquakes } = useEarthquakes(layers.earthquakes);
  const { cables, landingPoints } = useCables(layers.cables);
  const { vessels } = useVessels(layers.vessels);
  const { pipelines: pipelineData } = usePipelines(layers.pipelines);
  const { hotspots: firmsHotspots } = useFIRMSHotspots(layers.firmsHotspots);
  const { datacenters: datacenterData } = useDatacenters(layers.datacenters);
  const { refineries: refineryData } = useRefineries(layers.refineries);
  const { events: eonetEvents } = useEONETEvents(layers.eonet);
  const { events: gdacsEvents } = useGDACSEvents(layers.gdacs);
  const { scenes: reconScenes } = useReconManifest();
  const { openScene } = useRecon();

  const hasViewer = useMemo(() => viewer != null && !viewer.isDestroyed(), [viewer]);

  useEffect(() => {
    void getConfig()
      .then(setConfig)
      .catch(() => {
        setConfig({
          cesium_ion_token: "",
          default_layers: DEFAULT_LAYERS,
          api_version: "v1",
        });
      });
  }, []);

  useEffect(() => {
    if (!config?.default_layers) return;
    setLayers((prev) => ({ ...prev, ...config.default_layers }));
  }, [config]);

  useEffect(() => {
    if (!config) return;

    const params = new URLSearchParams(location.search);
    const layerParam = params.get("layer");
    const filterParam = params.get("filter");
    const entityParam = params.get("entity");

    if (layerParam && isLayerKey(layerParam)) {
      setLayers((prev) => ({ ...prev, [layerParam]: true }));
      setExpandedPanels((prev) => ({ ...prev, layers: true }));
    }

    if (filterParam && filterParam in FILTER_LAYER_PRESETS) {
      const preset = FILTER_LAYER_PRESETS[filterParam as LandingFilter];
      setLayers((prev) => ({ ...prev, ...preset }));
      setExpandedPanels((prev) => ({ ...prev, layers: true }));
    }

    const searchFromEntity = decodeEntityQuery(entityParam);
    if (searchFromEntity) {
      setSearchSeed(searchFromEntity);
      setExpandedPanels((prev) => ({ ...prev, search: true }));
    }
  }, [config, location.search]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "/") {
        const target = event.target as HTMLElement | null;
        if (target && ["INPUT", "TEXTAREA"].includes(target.tagName)) return;
        event.preventDefault();
        setExpandedPanels((prev) => ({ ...prev, search: true }));
      }

      if (event.key.toLowerCase() === "l" && !event.ctrlKey && !event.metaKey && !event.altKey) {
        const target = event.target as HTMLElement | null;
        if (target && ["INPUT", "TEXTAREA"].includes(target.tagName)) return;
        setExpandedPanels((prev) => ({ ...prev, layers: !prev.layers }));
      }
    };

    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const handleToggleLayer = useCallback((layer: keyof LayerVisibility) => {
    setLayers((prev) => ({ ...prev, [layer]: !prev[layer] }));
  }, []);

  const handleViewerReady = useCallback((createdViewer: Cesium.Viewer) => {
    setViewer(createdViewer);
  }, []);

  if (!config) {
    return (
      <div style={{ flex: 1, position: "relative", minHeight: 0 }}>
        <WorldviewHudLoader />
      </div>
    );
  }

  return (
    <SpotlightProvider>
    <PerformanceGuard>
    <TimeProvider viewer={viewer}>
      <div style={{ flex: 1, position: "relative", minHeight: 0 }} data-page="worldview">
        <div style={{ position: "absolute", inset: 0 }}>
          <GlobeViewer
            onViewerReady={handleViewerReady}
            cesiumToken={config.cesium_ion_token}
            activeShader={activeShader}
            showCountryBorders={layers.countryBorders}
            showCityBuildings={layers.cityBuildings}
            onPhotorealTilesetReady={setPhotorealTileset}
          />
        </div>

        <FlightLayer viewer={viewer} flights={flights} visible={layers.flights} />
        <SatelliteLayer viewer={viewer} satellites={satellites} visible={layers.satellites} />
        <EarthquakeLayer viewer={viewer} earthquakes={earthquakes} visible={layers.earthquakes} />
        <ShipLayer viewer={viewer} vessels={vessels} visible={layers.vessels} />
        <CCTVLayer viewer={viewer} visible={layers.cctv} />
        <EventLayerBridge
          viewer={viewer}
          events={eventLayerEvents}
          visible={layers.events}
          window={timelineWindow}
        />
        <CableLayer viewer={viewer} cables={cables} landingPoints={landingPoints} visible={layers.cables} />
        <PipelineLayer viewer={viewer} pipelines={pipelineData} visible={layers.pipelines} />
        <ReconLayer
          viewer={viewer}
          scenes={reconScenes}
          visible={true}
          onSelect={(s) => openScene(s.scene_id)}
        />
        <GlobeChildren
          viewer={viewer}
          photorealTileset={photorealTileset}
          layers={layers}
          setSelected={setSelected}
          onSelectEvent={setSelectedEventId}
          firmsHotspots={firmsHotspots}
          selectedWindow={selectedWindow}
          datacenterData={datacenterData}
          refineryData={refineryData}
          eonetEvents={eonetEvents}
          gdacsEvents={gdacsEvents}
        />
        <SpotlightOverlay viewer={viewer} />
        <HudFrame />
        <SpotlightCartouche />
        <CapitalPulse viewer={viewer} />
        <ZoomTriggerHook viewer={viewer} />

        {!hasViewer ? <WorldviewHudLoader /> : null}

        <div style={{ position: "absolute", top: 16, left: 16, zIndex: 10 }}>
          {expandedPanels.layers ? (
            <OverlayPanel
              paragraph="I"
              label="Layers"
              variant="expanded"
              onClose={() => setExpandedPanels((prev) => ({ ...prev, layers: false }))}
              width={322}
              style={{ maxHeight: "calc(100vh - 320px)" }}
            >
              <LayersPanel
                layers={layers}
                onToggle={handleToggleLayer}
                activeShader={activeShader}
                onShaderChange={setActiveShader}
              />
            </OverlayPanel>
          ) : (
            <OverlayPanel
              paragraph="I"
              label="Layers"
              variant="collapsed"
              onExpand={() => setExpandedPanels((prev) => ({ ...prev, layers: true }))}
            >
              {null}
            </OverlayPanel>
          )}
        </div>

        <div style={{ position: "absolute", top: 16, right: 16, zIndex: 10 }}>
          {expandedPanels.search ? (
            <OverlayPanel
              paragraph="II"
              label="Search"
              variant="expanded"
              onClose={() => setExpandedPanels((prev) => ({ ...prev, search: false }))}
              width={330}
            >
              <SearchAcceptHook viewer={viewer} initialQuery={searchSeed} />
            </OverlayPanel>
          ) : (
            <OverlayPanel
              paragraph="II"
              label="Search"
              variant="collapsed"
              onExpand={() => setExpandedPanels((prev) => ({ ...prev, search: true }))}
            >
              {null}
            </OverlayPanel>
          )}
        </div>

        <div style={{ position: "absolute", top: 86, right: 16, zIndex: 10 }}>
          <InspectorPanel selected={selected} onClose={() => setSelected(null)} viewer={viewer} />
        </div>

        {/* raised above the full-width § CHRONIK strip (height 90) docked at the bottom */}
        <div style={{ position: "absolute", left: 16, bottom: 106, zIndex: 10 }}>
          <TickerPanel
            variant={expandedPanels.ticker ? "expanded" : "collapsed"}
            onClose={() => setExpandedPanels((prev) => ({ ...prev, ticker: false }))}
            onExpand={() => setExpandedPanels((prev) => ({ ...prev, ticker: true }))}
          />
        </div>

        <EventCallout
          eventId={selectedEventId}
          onClose={() => setSelectedEventId(null)}
          onInspect={(d: TimelineEventDetail) => {
            if (viewer && !viewer.isDestroyed() && d.lat != null && d.lon != null) {
              viewer.camera.flyTo({
                destination: Cesium.Cartesian3.fromDegrees(d.lon, d.lat, 600_000),
                duration: 1.2,
              });
            }
          }}
        />

        <ScrubberMount
          onSelectEvent={setSelectedEventId}
          onTimelineData={handleTimelineData}
        />
      </div>
    </TimeProvider>
    </PerformanceGuard>
    </SpotlightProvider>
  );
}
