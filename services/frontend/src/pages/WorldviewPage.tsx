import { useCallback, useEffect, useMemo, useState } from "react";
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
import { CableLayer } from "../components/layers/CableLayer";
import { PipelineLayer } from "../components/layers/PipelineLayer";
import { FIRMSLayer } from "../components/layers/FIRMSLayer";
import { MilAircraftLayer } from "../components/layers/MilAircraftLayer";
import { DatacenterLayer } from "../components/layers/DatacenterLayer";
import { RefineryLayer } from "../components/layers/RefineryLayer";
import { EONETLayer } from "../components/layers/EONETLayer";
import { GDACSLayer } from "../components/layers/GDACSLayer";
import { OverlayPanel } from "../components/hlidskjalf/OverlayPanel";
import { LayersPanel } from "../components/worldview/LayersPanel";
import { SearchPanel } from "../components/worldview/SearchPanel";
import { InspectorPanel, type Selected } from "../components/worldview/InspectorPanel";
import { TickerPanel } from "../components/worldview/TickerPanel";
import { WorldviewHudLoader } from "../components/worldview/WorldviewHudLoader";
import { SpotlightProvider } from "../components/globe/spotlight/SpotlightContext";
import { useFlights } from "../hooks/useFlights";
import { useSatellites } from "../hooks/useSatellites";
import { useEarthquakes } from "../hooks/useEarthquakes";
import { useEvents } from "../hooks/useEvents";
import { useCables } from "../hooks/useCables";
import { useVessels } from "../hooks/useVessels";
import { usePipelines } from "../hooks/usePipelines";
import { useFIRMSHotspots } from "../hooks/useFIRMSHotspots";
import { useAircraftTracks } from "../hooks/useAircraftTracks";
import { useDatacenters } from "../hooks/useDatacenters";
import { useRefineries } from "../hooks/useRefineries";
import { useEONETEvents } from "../hooks/useEONETEvents";
import { useGDACSEvents } from "../hooks/useGDACSEvents";
import { getConfig } from "../services/api";
import type { ClientConfig, LayerVisibility, ShaderType } from "../types";

type PanelId = "layers" | "search";

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
  const [config, setConfig] = useState<ClientConfig | null>(null);
  const [layers, setLayers] = useState<LayerVisibility>(DEFAULT_LAYERS);
  const [activeShader, setActiveShader] = useState<ShaderType>("none");
  const [selected, setSelected] = useState<Selected | null>(null);
  const [searchSeed, setSearchSeed] = useState("");
  const [expandedPanels, setExpandedPanels] = useState<Record<PanelId, boolean>>({
    layers: false,
    search: false,
  });

  const { flights } = useFlights(layers.flights);
  const { satellites } = useSatellites(layers.satellites);
  const { earthquakes } = useEarthquakes(layers.earthquakes);
  const { events } = useEvents(layers.events);
  const { cables, landingPoints } = useCables(layers.cables);
  const { vessels } = useVessels(layers.vessels);
  const { pipelines: pipelineData } = usePipelines(layers.pipelines);
  const { hotspots: firmsHotspots } = useFIRMSHotspots(layers.firmsHotspots);
  const { tracks: milTracks } = useAircraftTracks(layers.milAircraft);
  const { datacenters: datacenterData } = useDatacenters(layers.datacenters);
  const { refineries: refineryData } = useRefineries(layers.refineries);
  const { events: eonetEvents } = useEONETEvents(layers.eonet);
  const { events: gdacsEvents } = useGDACSEvents(layers.gdacs);

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
      <div style={{ flex: 1, position: "relative", minHeight: 0 }} data-page="worldview">
        <div style={{ position: "absolute", inset: 0 }}>
          <GlobeViewer
            onViewerReady={handleViewerReady}
            cesiumToken={config.cesium_ion_token}
            activeShader={activeShader}
            showCountryBorders={layers.countryBorders}
            showCityBuildings={layers.cityBuildings}
          />
        </div>

        <FlightLayer viewer={viewer} flights={flights} visible={layers.flights} />
        <SatelliteLayer viewer={viewer} satellites={satellites} visible={layers.satellites} />
        <EarthquakeLayer viewer={viewer} earthquakes={earthquakes} visible={layers.earthquakes} />
        <ShipLayer viewer={viewer} vessels={vessels} visible={layers.vessels} />
        <CCTVLayer viewer={viewer} visible={layers.cctv} />
        <EventLayer viewer={viewer} events={events} visible={layers.events} />
        <CableLayer viewer={viewer} cables={cables} landingPoints={landingPoints} visible={layers.cables} />
        <PipelineLayer viewer={viewer} pipelines={pipelineData} visible={layers.pipelines} />
        <FIRMSLayer
          viewer={viewer}
          hotspots={firmsHotspots}
          visible={layers.firmsHotspots}
          onSelect={(hotspot) => setSelected({ type: "firms", data: hotspot })}
        />
        <MilAircraftLayer
          viewer={viewer}
          tracks={milTracks}
          visible={layers.milAircraft}
          onSelect={(track) => setSelected({ type: "aircraft", data: track })}
        />
        <DatacenterLayer
          viewer={viewer}
          datacenters={datacenterData}
          visible={layers.datacenters}
          onSelect={(datacenter) => setSelected({ type: "datacenter", data: datacenter })}
        />
        <RefineryLayer
          viewer={viewer}
          refineries={refineryData}
          visible={layers.refineries}
          onSelect={(refinery) => setSelected({ type: "refinery", data: refinery })}
        />
        <EONETLayer
          viewer={viewer}
          events={eonetEvents}
          visible={layers.eonet}
          onSelect={(event) => setSelected({ type: "eonet", data: event })}
        />
        <GDACSLayer
          viewer={viewer}
          events={gdacsEvents}
          visible={layers.gdacs}
          onSelect={(event) => setSelected({ type: "gdacs", data: event })}
        />

        <EntityClickHandler viewer={viewer} onCountrySelect={setSelected} />

        {!hasViewer ? <WorldviewHudLoader /> : null}

        <div style={{ position: "absolute", top: 16, left: 16, zIndex: 10 }}>
          {expandedPanels.layers ? (
            <OverlayPanel
              paragraph="I"
              label="Layers"
              variant="expanded"
              onClose={() => setExpandedPanels((prev) => ({ ...prev, layers: false }))}
              width={322}
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
              <SearchPanel viewer={viewer} initialQuery={searchSeed} />
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

        <div style={{ position: "absolute", left: 16, bottom: 16, zIndex: 10 }}>
          <TickerPanel />
        </div>
      </div>
    </PerformanceGuard>
    </SpotlightProvider>
  );
}
