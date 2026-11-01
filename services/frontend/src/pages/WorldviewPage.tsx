import {
  type LayerVisibility,
  type Earthquake,
  type ClientConfig,
  type ShaderType,
  type TimelineGeoEvent,
  type IntelEvent,
  type TimelineEventDetail,
} from "../types";
import {
  CesiumSpatialPresentationBridge,
} from "../spatial/cesium/SpatialPresentationBridge";
import {
  type SpatialBoundaryProvenanceLoader,
  BoundaryAssetStore,
  HttpSpatialCatalog,
} from "../spatial/catalog";
import {
  type SpatialContainmentPort,
  type ContainmentSnapshot,
  WORLD_SCOPE_KEY,
} from "../spatial/contracts";
import {
  type StrictPointLayerAdapter,
  createStrictPointLayerAdapter,
} from "../spatial/pointLayerSpatialAdapter";
import {
  useCallback,
  useSyncExternalStore,
  useState,
  useMemo,
  type Dispatch,
  type SetStateAction,
  useEffect,
  useRef,
} from "react";
import {
  useLocation,
} from "react-router-dom";
import {
  useOptionalSpatialScope,
  useSpatialScope,
  SPATIAL_SCOPE_ENABLED,
  SpatialScopeProvider,
} from "../spatial/react";
import * as Cesium from "cesium";
import {
  layerSpatialStatuses,
  applyLayerSpatialPolicy,
} from "../spatial/layerScopePolicy";
import {
  type SelectionEnvelope,
  selectionForScopeRevision,
  createSelectionEnvelope,
} from "../spatial/selection";
import {
  type Selected,
  InspectorPanel,
} from "../components/worldview/InspectorPanel";
import {
  useSpatialBoundaryProvenance,
} from "../hooks/useSpatialBoundaryProvenance";
import {
  toTimelineLayerEvents,
} from "../components/time/timelineEvents";
import {
  useFlights,
} from "../hooks/useFlights";
import {
  useSatellites,
} from "../hooks/useSatellites";
import {
  useEarthquakes,
} from "../hooks/useEarthquakes";
import {
  useCables,
} from "../hooks/useCables";
import {
  useVessels,
} from "../hooks/useVessels";
import {
  usePipelines,
} from "../hooks/usePipelines";
import {
  useFIRMSHotspots,
} from "../hooks/useFIRMSHotspots";
import {
  useDatacenters,
} from "../hooks/useDatacenters";
import {
  useRefineries,
} from "../hooks/useRefineries";
import {
  useEONETEvents,
} from "../hooks/useEONETEvents";
import {
  useGDACSEvents,
} from "../hooks/useGDACSEvents";
import {
  useReconManifest,
} from "../lib/recon/manifest";
import {
  useRecon,
} from "../state/ReconContext";
import {
  getConfig,
} from "../services/api";
import {
  WORKSPACE_MODES,
  layersForMode,
} from "../components/worldview/workspaceModes";
import {
  WorldviewHudLoader,
} from "../components/worldview/WorldviewHudLoader";
import {
  SpotlightProvider,
} from "../components/globe/spotlight/SpotlightContext";
import {
  PerformanceGuard,
} from "../components/globe/PerformanceGuard";
import {
  TimeProvider,
} from "../state/TimeContext";
import {
  GlobeViewer,
} from "../components/globe/GlobeViewer";
import type { FlightDensity } from "../components/layers/flightDensity";
import type { EventDensity } from "../components/layers/eventDensity";
import {
  SatelliteLayerBridge,
} from "../components/layers/SatelliteLayer";
import {
  SatelliteSourceStatus,
} from "../components/layers/SatelliteSourceStatus";
import {
  EarthquakeLayer,
} from "../components/layers/EarthquakeLayer";
import {
  ShipLayer,
} from "../components/layers/ShipLayer";
import {
  StrategicReferenceLayer,
} from "../components/layers/StrategicReferenceLayer";
import {
  CCTVLayer,
} from "../components/layers/CCTVLayer";
import {
  CableLayer,
} from "../components/layers/CableLayer";
import {
  PipelineLayer,
} from "../components/layers/PipelineLayer";
import {
  ReconLayer,
} from "../components/layers/ReconLayer";
import {
  MutuallyExclusiveCountryPath,
} from "../spatial/WorldviewCountryPath";
import {
  CountryBorders,
} from "../components/globe/visual-layers/CountryBorders";
import {
  LegacyCountrySpotlightOverlay,
  CircleSpotlightOverlay,
} from "../components/globe/spotlight/SpotlightOverlay";
import {
  CapitalPulse,
} from "../components/globe/spotlight/CapitalPulse";
import {
  SpatialScopeViewerBridge,
} from "../spatial/cesium/SpatialScopeViewerBridge";
import {
  RegionalAtlas,
} from "../spatial/RegionalAtlas";
import {
  SpatialScopeBreadcrumb,
} from "../spatial/SpatialScopeBreadcrumb";
import {
  WorldviewKeyboardCoordinator,
} from "../spatial/WorldviewKeyboardCoordinator";
import {
  HudFrame,
} from "../components/globe/spotlight/HudFrame";
import {
  SpotlightCartouche,
} from "../components/globe/spotlight/SpotlightCartouche";
import {
  WorkspaceBar,
} from "../components/worldview/WorkspaceBar";
import {
  OverlayPanel,
} from "../components/hlidskjalf/OverlayPanel";
import {
  LayersPanel,
} from "../components/worldview/LayersPanel";
import {
  TickerPanel,
} from "../components/worldview/TickerPanel";
import {
  EventCallout,
} from "../components/time/EventCallout";
import {
  ScrubberMount,
} from "../components/time/ScrubberMount";
import {
  type OwnedSpatialContainmentPort,
  createSpatialContainmentController,
} from "../spatial/containment";
import { EventLayerBridge, FlightLayerBridge, GlobeChildren } from "../components/worldview/WorldviewLayers";
import { LegacyEventClickBridge, SpatialEventClickBridge, ZoomTriggerHook, SearchAcceptHook } from "../components/worldview/WorldviewInteractions";

type PanelId = "layers" | "search" | "ticker";

type LandingFilter = "hotspots" | "conflict" | "nuntii" | "libri";

const DEFAULT_LAYERS: LayerVisibility = {
  nuclearPlants: false,
  icbmBases: false,
  militaryBases: false,
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
  recon: true,
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

function decodeEntityQuery(value: string | null): string {
  if (!value) return "";
  const decoded = value.trim();
  // Landing deep-links currently use `source:id` payloads; search works best
  // on human-readable names, so only keep the left segment when present.
  return decoded.includes(":") ? (decoded.split(":")[0] ?? "").trim() : decoded.trim();
}

interface WorldviewContentProps {
  readonly spatialEnabled: boolean;
  readonly presentationBridge: CesiumSpatialPresentationBridge | null;
  readonly provenanceLoader: SpatialBoundaryProvenanceLoader | null;
  readonly containment: SpatialContainmentPort | null;
  readonly earthquakeSpatialAdapter: StrictPointLayerAdapter<Earthquake> | null;
}

const DISABLED_CONTAINMENT_SNAPSHOT: ContainmentSnapshot = Object.freeze({
  phase: "unavailable",
  stateRevision: 0,
});

function useContainmentSnapshot(
  containment: SpatialContainmentPort | null,
): ContainmentSnapshot {
  const subscribe = useCallback(
    (listener: () => void) => containment?.subscribe(listener) ?? (() => undefined),
    [containment],
  );
  const getSnapshot = useCallback(
    () => containment?.getSnapshot() ?? DISABLED_CONTAINMENT_SNAPSHOT,
    [containment],
  );
  return useSyncExternalStore(subscribe, getSnapshot, getSnapshot);
}

function WorldviewContent({
  spatialEnabled,
  presentationBridge,
  provenanceLoader,
  containment,
  earthquakeSpatialAdapter,
}: WorldviewContentProps) {
  const location = useLocation();
  const spatialScope = useOptionalSpatialScope();
  const scopeStateRevision = spatialEnabled ? spatialScope?.stateRevision ?? 0 : 0;
  const currentScopeKey = spatialEnabled
    && spatialScope !== null
    && spatialScope.phase !== "hydrating"
    ? spatialScope.current.key
    : WORLD_SCOPE_KEY;
  const currentScopeKind = spatialEnabled
    ? spatialScope !== null && spatialScope.phase !== "hydrating"
      ? spatialScope.current.kind
      : null
    : "world";
  const containmentSnapshot = useContainmentSnapshot(
    spatialEnabled ? containment : null,
  );
  const committedSpatialQuery = spatialEnabled
    && spatialScope !== null
    && spatialScope.phase !== "hydrating"
    ? spatialScope.query
    : null;
  const chronikSpatialScope = spatialEnabled ? committedSpatialQuery : undefined;

  const [viewer, setViewer] = useState<Cesium.Viewer | null>(null);
  const [photorealTileset, setPhotorealTileset] = useState<Cesium.Cesium3DTileset | null>(null);
  const [config, setConfig] = useState<ClientConfig | null>(null);
  const [configError, setConfigError] = useState(false);
  const [configAttempt, setConfigAttempt] = useState(0);
  const [layers, setLayers] = useState<LayerVisibility>(DEFAULT_LAYERS);
  const runtimeSpatialStatuses = useMemo(
    () => layerSpatialStatuses(currentScopeKind, containmentSnapshot),
    [containmentSnapshot, currentScopeKind],
  );
  const effectiveLayers = useMemo(
    () => spatialEnabled
      ? applyLayerSpatialPolicy(layers, currentScopeKind, containmentSnapshot)
      : layers,
    [containmentSnapshot, currentScopeKind, layers, spatialEnabled],
  );
  const [activeShader, setActiveShader] = useState<ShaderType>("none");
  const [selectionEnvelope, setSelectionEnvelope] =
    useState<SelectionEnvelope<Selected> | null>(null);
  const selected = selectionForScopeRevision(
    selectionEnvelope,
    scopeStateRevision,
    currentScopeKey,
  );
  const setSelected = useCallback<Dispatch<SetStateAction<Selected | null>>>(
    (action) => {
      setSelectionEnvelope((previousEnvelope) => {
        const previous = selectionForScopeRevision(
          previousEnvelope,
          scopeStateRevision,
          currentScopeKey,
        );
        const next = typeof action === "function" ? action(previous) : action;
        if (next === null) return null;
        const verifiedScopeKey = next.type === "spatial-country"
          ? next.data.scopeKey
          : null;
        return createSelectionEnvelope(next, scopeStateRevision, verifiedScopeKey);
      });
    },
    [currentScopeKey, scopeStateRevision],
  );
  const [searchSeed, setSearchSeed] = useState("");
  const [focusMode, setFocusMode] = useState(false);
  const [expandedPanels, setExpandedPanels] = useState<Record<PanelId, boolean>>({
    layers: false,
    search: false,
    ticker: true,
  });
  const spatialProvenance = useSpatialBoundaryProvenance(
    spatialEnabled ? provenanceLoader : null,
    spatialEnabled && expandedPanels.layers ? committedSpatialQuery : null,
  );
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
  const [selectedEventEnvelope, setSelectedEventEnvelope] =
    useState<SelectionEnvelope<string> | null>(null);
  const selectedEventId = selectionForScopeRevision(
    selectedEventEnvelope,
    scopeStateRevision,
    currentScopeKey,
  );
  const setSelectedEventId = useCallback(
    (id: string | null) => setSelectedEventEnvelope(
      id === null ? null : createSelectionEnvelope(id, scopeStateRevision),
    ),
    [scopeStateRevision],
  );
  const [timelineGeo, setTimelineGeo] = useState<TimelineGeoEvent[]>([]);
  const [timelineWindow, setTimelineWindow] = useState<{ startMs: number; endMs: number } | null>(
    null,
  );
  useEffect(() => {
    if (!spatialEnabled) return;
    setSelectionEnvelope((previous) => (
      previous !== null
      && previous.verifiedScopeKey === null
      && previous.selectedAtScopeStateRevision !== scopeStateRevision
        ? null
        : previous
    ));
    setSelectedEventEnvelope((previous) => (
      previous !== null
      && previous.selectedAtScopeStateRevision !== scopeStateRevision
        ? null
        : previous
    ));
  }, [scopeStateRevision, spatialEnabled]);
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
  const eventLayerEvents = useMemo<IntelEvent[]>(
    () => toTimelineLayerEvents(timelineGeo),
    [timelineGeo],
  );

  const { flights, loading: flightsLoading, lastUpdate: flightsUpdated, error: flightsError } = useFlights(effectiveLayers.flights);
  const [flightDensity, setFlightDensity] = useState<FlightDensity | null>(null);
  const [eventDensity, setEventDensity] = useState<EventDensity | null>(null);
  const satelliteSource = useSatellites(effectiveLayers.satellites);
  const { satellites } = satelliteSource;
  const { earthquakes } = useEarthquakes(layers.earthquakes);
  const { cables, landingPoints } = useCables(effectiveLayers.cables);
  const { vessels } = useVessels(effectiveLayers.vessels);
  const { pipelines: pipelineData } = usePipelines(effectiveLayers.pipelines);
  const { hotspots: firmsHotspots } = useFIRMSHotspots(effectiveLayers.firmsHotspots);
  const { datacenters: datacenterData } = useDatacenters(effectiveLayers.datacenters);
  const { refineries: refineryData } = useRefineries(effectiveLayers.refineries);
  const { events: eonetEvents } = useEONETEvents(effectiveLayers.eonet);
  const { events: gdacsEvents } = useGDACSEvents(effectiveLayers.gdacs);
  const reconManifest = useReconManifest();
  const reconScenes = reconManifest.scenes;
  const { openScene } = useRecon();

  const hasViewer = useMemo(() => viewer != null && !viewer.isDestroyed(), [viewer]);

  useEffect(() => {
    let active = true;
    void getConfig()
      .then(value => {
        if (!active) return;
        setConfig(value);
        setConfigError(false);
      })
      .catch(() => {
        if (!active) return;
        setConfigError(true);
        setConfig({
          cesium_ion_token: "",
          default_layers: DEFAULT_LAYERS,
          api_version: "v1",
        });
      });
    return () => { active = false; };
  }, [configAttempt]);

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
    const mode = WORKSPACE_MODES.find(item => item.id === params.get("mode"));
    if (mode) setLayers(layersForMode(mode.id));

    if (layerParam && isLayerKey(layerParam)) {
      setLayers((prev) => ({ ...prev, [layerParam]: true }));
      setExpandedPanels((prev) => ({ ...prev, layers: true }));
    }

    if (filterParam && filterParam in FILTER_LAYER_PRESETS) {
      const preset = FILTER_LAYER_PRESETS[filterParam as LandingFilter];
      setLayers((prev) => ({ ...prev, ...preset }));
      setExpandedPanels((prev) => ({ ...prev, layers: true }));
    }

    const searchFromEntity = params.get("q")?.trim() || decodeEntityQuery(entityParam);
    if (searchFromEntity) {
      setSearchSeed(searchFromEntity);
      setExpandedPanels((prev) => ({ ...prev, search: true }));
    }
  }, [config, location.search]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const target = event.target instanceof Element ? event.target : null;
      if (event.ctrlKey || event.metaKey || event.altKey || event.repeat
        || target?.closest('input, textarea, select, [contenteditable]:not([contenteditable="false"]), [role="textbox"]')) return;
      if (event.key.toLowerCase() === "f") {
        event.preventDefault();
        setFocusMode(previous => !previous);
      }
      if (event.key === "/") {
        const target = event.target as HTMLElement | null;
        if (target && ["INPUT", "TEXTAREA"].includes(target.tagName)) return;
        event.preventDefault();
        setFocusMode(false);
        setExpandedPanels((prev) => ({ ...prev, search: true }));
      }

      if (event.key.toLowerCase() === "l" && !event.ctrlKey && !event.metaKey && !event.altKey) {
        const target = event.target as HTMLElement | null;
        if (target && ["INPUT", "TEXTAREA"].includes(target.tagName)) return;
        setFocusMode(false);
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
  const clearSelectedEvent = useCallback(
    () => setSelectedEventId(null),
    [setSelectedEventId],
  );
  const clearTransientSelection = useCallback(() => {
    setSelected(null);
    setSelectedEventId(null);
  }, [setSelected, setSelectedEventId]);

  if (!config) {
    return (
      <div className="worldview-workspace" style={{ flex: 1, position: "relative", minHeight: 0 }}>
        <WorldviewHudLoader />
      </div>
    );
  }

  return (
    <SpotlightProvider>
    <PerformanceGuard viewer={viewer}>
    <TimeProvider viewer={viewer}>
      <div className="worldview-workspace" data-degraded={configError || !config.cesium_ion_token} style={{ flex: 1, position: "relative", minHeight: 0 }} data-page="worldview">
        <div style={{ position: "absolute", inset: 0 }}>
          <GlobeViewer
            onViewerReady={handleViewerReady}
            cesiumToken={config.cesium_ion_token}
            activeShader={activeShader}
            showCountryBorders={!spatialEnabled && effectiveLayers.countryBorders}
            showCityBuildings={effectiveLayers.cityBuildings}
            onPhotorealTilesetReady={setPhotorealTileset}
          />
        </div>

        <FlightLayerBridge viewer={viewer} flights={flights} visible={effectiveLayers.flights} onDensity={setFlightDensity} />
        <SatelliteLayerBridge viewer={viewer} satellites={satellites} visible={effectiveLayers.satellites} />
        {effectiveLayers.satellites && <SatelliteSourceStatus snapshot={satelliteSource.snapshot} loading={satelliteSource.loading} error={satelliteSource.error} />}
        <EarthquakeLayer
          viewer={viewer}
          earthquakes={earthquakes}
          visible={effectiveLayers.earthquakes}
          spatialAdapter={earthquakeSpatialAdapter ?? undefined}
        />
        <ShipLayer viewer={viewer} vessels={vessels} visible={effectiveLayers.vessels} />
        <StrategicReferenceLayer viewer={viewer} layers={effectiveLayers} onSelect={(site) => setSelected({ type: "strategic", data: site })} />
        <CCTVLayer viewer={viewer} visible={effectiveLayers.cctv} />
        <EventLayerBridge
          viewer={viewer}
          events={eventLayerEvents}
          visible={effectiveLayers.events}
          window={timelineWindow}
          onDensity={setEventDensity}
        />
        <CableLayer viewer={viewer} cables={cables} landingPoints={landingPoints} visible={effectiveLayers.cables} />
        <PipelineLayer viewer={viewer} pipelines={pipelineData} visible={effectiveLayers.pipelines} />
        <ReconLayer
          viewer={viewer}
          scenes={reconScenes}
          visible={effectiveLayers.recon && reconManifest.status === "available"}
          onSelect={(s) => openScene(s.scene_id)}
        />
        <GlobeChildren
          viewer={viewer}
          layers={effectiveLayers}
          setSelected={setSelected}
          firmsHotspots={firmsHotspots}
          selectedWindow={selectedWindow}
          datacenterData={datacenterData}
          refineryData={refineryData}
          eonetEvents={eonetEvents}
          gdacsEvents={gdacsEvents}
          chronikSpatialScope={chronikSpatialScope}
          scopeGeneration={scopeStateRevision}
        />
        <MutuallyExclusiveCountryPath
          spatialEnabled={spatialEnabled}
          legacyRenderer={(
            <>
              <CountryBorders viewer={viewer} visible={effectiveLayers.countryBorders} />
              <LegacyCountrySpotlightOverlay viewer={viewer} />
              <CapitalPulse viewer={viewer} />
            </>
          )}
          legacyClickHandler={(
            <LegacyEventClickBridge
              viewer={viewer}
              photorealTileset={photorealTileset}
              onCountrySelect={setSelected}
              onSelectEvent={setSelectedEventId}
              onClearEvent={clearSelectedEvent}
            />
          )}
          spatialRenderer={presentationBridge === null ? null : (
            <>
              <SpatialScopeViewerBridge viewer={viewer} bridge={presentationBridge} />
              <RegionalAtlas viewer={viewer} hidden={focusMode || expandedPanels.layers} />
              <div
                className="worldview-scope-navigation"
                data-availability-warning={configError || !config.cesium_ion_token}
              >
                <SpatialScopeBreadcrumb />
              </div>
            </>
          )}
          spatialClickHandler={(
            <SpatialEventClickBridge
              viewer={viewer}
              photorealTileset={photorealTileset}
              onCountrySelect={setSelected}
              onSelectEvent={setSelectedEventId}
              onClearEvent={clearSelectedEvent}
            />
          )}
        />
        <CircleSpotlightOverlay viewer={viewer} />
        <WorldviewKeyboardCoordinator
          hasTransientSelection={selected !== null || selectedEventId !== null}
          clearTransientSelection={clearTransientSelection}
        />
        <HudFrame allowCountry={!spatialEnabled} />
        <SpotlightCartouche allowCountry={!spatialEnabled} />
        <ZoomTriggerHook viewer={viewer} />

        {!hasViewer ? <WorldviewHudLoader /> : null}

        <WorkspaceBar layers={layers} focusMode={focusMode}
          onMode={mode => setLayers(layersForMode(mode))}
          onFocus={() => setFocusMode(previous => !previous)} />

        {configError || !config.cesium_ion_token ? <div className="worldview-availability" role={configError ? "alert" : "status"}>
          <span>{configError ? "Backend unavailable. Reference map only; live data, search and regional scopes cannot load." : "Reference map · Detailed imagery unavailable."}</span>
          {configError && <button type="button" onClick={() => setConfigAttempt(previous => previous + 1)}>Retry connection</button>}
        </div> : null}

        <div className="worldview-left-rail" hidden={focusMode}>
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
                spatialProvenance={spatialEnabled ? spatialProvenance : undefined}
                spatialStatuses={spatialEnabled ? runtimeSpatialStatuses : undefined}
                recon={reconManifest}
                flightStatus={{ density: flightDensity, loading: flightsLoading, lastUpdate: flightsUpdated, error: flightsError }}
                eventDensity={eventDensity}
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

        <div className="worldview-right-rail" hidden={focusMode}>
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
          <InspectorPanel
            selected={selected}
            onClose={() => setSelected(null)}
            viewer={viewer}
            spatialQuery={committedSpatialQuery}
          />
        </div>

        {/* The ticker is globally sourced; hide it below world until it has a scoped lane. */}
        {!spatialEnabled || currentScopeKind === "world" ? (
          <div className="worldview-ticker-rail" hidden={focusMode}>
            <TickerPanel
              variant={expandedPanels.ticker ? "expanded" : "collapsed"}
              onClose={() => setExpandedPanels((prev) => ({ ...prev, ticker: false }))}
              onExpand={() => setExpandedPanels((prev) => ({ ...prev, ticker: true }))}
              onSelect={signal => {
                setSearchSeed(signal.payload.title || signal.payload.source || signal.type);
                setExpandedPanels(previous => ({ ...previous, search: true }));
              }}
            />
          </div>
        ) : null}

        <div className="worldview-navigation-hint" aria-hidden="true">Drag to explore <span>·</span> Scroll to zoom <span>·</span> <kbd>/</kbd> Search <span>·</span> <kbd>L</kbd> Layers</div>

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
          spatialScope={chronikSpatialScope}
          scopeGeneration={scopeStateRevision}
        />
      </div>
    </TimeProvider>
    </PerformanceGuard>
    </SpotlightProvider>
  );
}

interface SpatialWorldviewResources {
  readonly assets: BoundaryAssetStore;
  readonly catalog: HttpSpatialCatalog;
  readonly presentation: CesiumSpatialPresentationBridge;
  readonly containment: OwnedSpatialContainmentPort;
  readonly earthquakeSpatialAdapter: StrictPointLayerAdapter<Earthquake>;
  lifecycleGeneration: number;
  disposed: boolean;
}

interface SpatialCanaryWindow extends Window {
  __ODIN_SPATIAL_CANARY__?: () => Readonly<{
    assets: ReturnType<BoundaryAssetStore["diagnostics"]>;
    catalog: ReturnType<HttpSpatialCatalog["diagnostics"]>;
    presentation: ReturnType<CesiumSpatialPresentationBridge["diagnostics"]>;
    containment: Readonly<{
      phase: ContainmentSnapshot["phase"];
      stateRevision: number;
    }>;
    scope: Readonly<{
      current: ReturnType<typeof useSpatialScope>["current"] | null;
      pending: ReturnType<typeof useSpatialScope>["pending"];
      phase: ReturnType<typeof useSpatialScope>["phase"];
      problem: ReturnType<typeof useSpatialScope>["problem"];
      stateRevision: number;
      visual: ReturnType<typeof useSpatialScope>["visual"];
    }>;
  }>;
}

function createSpatialWorldviewResources(): SpatialWorldviewResources {
  const assets = new BoundaryAssetStore();
  const containment = createSpatialContainmentController({ assets });
  return {
    assets,
    catalog: new HttpSpatialCatalog({ assetStore: assets }),
    presentation: new CesiumSpatialPresentationBridge({ assets }),
    containment,
    earthquakeSpatialAdapter: createStrictPointLayerAdapter<Earthquake>({
      containment,
      coordinates: (earthquake) => [earthquake.longitude, earthquake.latitude],
    }),
    lifecycleGeneration: 0,
    disposed: false,
  };
}

function SpatialCanaryProbe({ resources }: { readonly resources: SpatialWorldviewResources }) {
  const scope = useSpatialScope();
  useEffect(() => {
    if (
      !import.meta.env.DEV
      || new URLSearchParams(window.location.search).get("spatial_canary") !== "1"
    ) {
      return;
    }
    const canaryWindow = window as SpatialCanaryWindow;
    const readDiagnostics = () => {
      const containment = resources.containment.getSnapshot();
      return Object.freeze({
        assets: resources.assets.diagnostics(),
        catalog: resources.catalog.diagnostics(),
        presentation: resources.presentation.diagnostics(),
        containment: Object.freeze({
          phase: containment.phase,
          stateRevision: containment.stateRevision,
        }),
        scope: Object.freeze({
          current: scope.phase === "hydrating" ? null : scope.current,
          pending: scope.pending,
          phase: scope.phase,
          problem: scope.problem,
          stateRevision: scope.stateRevision,
          visual: scope.visual,
        }),
      });
    };
    canaryWindow.__ODIN_SPATIAL_CANARY__ = readDiagnostics;
    return () => {
      if (canaryWindow.__ODIN_SPATIAL_CANARY__ === readDiagnostics) {
        delete canaryWindow.__ODIN_SPATIAL_CANARY__;
      }
    };
  }, [resources, scope]);
  return null;
}

export function WorldviewPage() {
  const resourcesRef = useRef<SpatialWorldviewResources | null>(null);
  if (SPATIAL_SCOPE_ENABLED && resourcesRef.current === null) {
    resourcesRef.current = createSpatialWorldviewResources();
  }
  const resources = resourcesRef.current;

  useEffect(() => {
    if (resources === null) return;
    const lifecycleGeneration = ++resources.lifecycleGeneration;
    return () => {
      queueMicrotask(() => {
        if (
          resources.lifecycleGeneration === lifecycleGeneration
          && !resources.disposed
        ) {
          resources.disposed = true;
          resources.containment.dispose();
          resources.presentation.dispose();
          resources.catalog.dispose();
        }
      });
    };
  }, [resources]);

  return (
    <SpatialScopeProvider
      enabled={SPATIAL_SCOPE_ENABLED}
      catalog={resources?.catalog}
      presentation={resources?.presentation}
      containment={resources?.containment}
    >
      {resources === null ? null : <SpatialCanaryProbe resources={resources} />}
      <WorldviewContent
        spatialEnabled={SPATIAL_SCOPE_ENABLED}
        presentationBridge={resources?.presentation ?? null}
        provenanceLoader={resources?.catalog ?? null}
        containment={resources?.containment ?? null}
        earthquakeSpatialAdapter={resources?.earthquakeSpatialAdapter ?? null}
      />
    </SpatialScopeProvider>
  );
}
