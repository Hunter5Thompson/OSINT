import { useCallback, useEffect, useState } from "react";
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
import { InspectorPanel } from "../components/worldview/InspectorPanel";
import { TickerPanel } from "../components/worldview/TickerPanel";
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
import type {
  LayerVisibility,
  ShaderType,
  ClientConfig,
  DatacenterProperties,
  RefineryProperties,
} from "../types";
import type { Selected } from "../components/worldview/InspectorPanel";

type PanelId = "layers" | "search";

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

export function WorldviewPage() {
  const [viewer, setViewer] = useState<Cesium.Viewer | null>(null);
  const [config, setConfig] = useState<ClientConfig | null>(null);
  const [layers, setLayers] = useState<LayerVisibility>(DEFAULT_LAYERS);
  const [activeShader, setActiveShader] = useState<ShaderType>("none");
  const [selected, setSelected] = useState<Selected | null>(null);
  const [expanded, setExpanded] = useState<Record<PanelId, boolean>>({
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
    if (config?.default_layers) {
      setLayers((prev) => ({ ...prev, ...config.default_layers }));
    }
  }, [config]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "/") {
        e.preventDefault();
        setExpanded((p) => ({ ...p, search: true }));
      } else if (e.key.toLowerCase() === "l" && !e.ctrlKey && !e.metaKey) {
        const target = e.target as HTMLElement | null;
        if (target && ["INPUT", "TEXTAREA"].includes(target.tagName)) return;
        setExpanded((p) => ({ ...p, layers: !p.layers }));
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const handleToggleLayer = useCallback((layer: keyof LayerVisibility) => {
    setLayers((prev) => ({ ...prev, [layer]: !prev[layer] }));
  }, []);

  const handleViewerReady = useCallback((v: Cesium.Viewer) => {
    setViewer(v);
  }, []);

  if (!config) {
    return (
      <div style={{ flex: 1, display: "grid", placeItems: "center", color: "var(--stone)" }}>
        <span className="mono">§ Initializing worldview…</span>
      </div>
    );
  }

  return (
    <PerformanceGuard>
      <div style={{ flex: 1, position: "relative", minHeight: 0 }}>
        <GlobeViewer
          onViewerReady={handleViewerReady}
          cesiumToken={config.cesium_ion_token}
          activeShader={activeShader}
          showCountryBorders={layers.countryBorders}
          showCityBuildings={layers.cityBuildings}
        />

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
          onSelect={(h) => setSelected({ type: "firms", data: h })}
        />
        <MilAircraftLayer
          viewer={viewer}
          tracks={milTracks}
          visible={layers.milAircraft}
          onSelect={(t) => setSelected({ type: "aircraft", data: t })}
        />
        <DatacenterLayer
          viewer={viewer}
          datacenters={datacenterData}
          visible={layers.datacenters}
          onSelect={(d: DatacenterProperties) => setSelected({ type: "datacenter", data: d })}
        />
        <RefineryLayer
          viewer={viewer}
          refineries={refineryData}
          visible={layers.refineries}
          onSelect={(r: RefineryProperties) => setSelected({ type: "refinery", data: r })}
        />
        <EONETLayer
          viewer={viewer}
          events={eonetEvents}
          visible={layers.eonet}
          onSelect={(e) => setSelected({ type: "eonet", data: e })}
        />
        <GDACSLayer
          viewer={viewer}
          events={gdacsEvents}
          visible={layers.gdacs}
          onSelect={(e) => setSelected({ type: "gdacs", data: e })}
        />
        <EntityClickHandler viewer={viewer} />

        {/* § Layers — top-left, default collapsed */}
        <div style={{ position: "absolute", top: 16, left: 16, zIndex: 10 }}>
          {expanded.layers ? (
            <OverlayPanel
              paragraph="I"
              label="Layers"
              variant="expanded"
              onClose={() => setExpanded((p) => ({ ...p, layers: false }))}
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
              onExpand={() => setExpanded((p) => ({ ...p, layers: true }))}
            >
              {null}
            </OverlayPanel>
          )}
        </div>

        {/* § Search — top-right, default collapsed, / hotkey */}
        <div style={{ position: "absolute", top: 16, right: 16, zIndex: 10 }}>
          {expanded.search ? (
            <OverlayPanel
              paragraph="II"
              label="Search"
              variant="expanded"
              onClose={() => setExpanded((p) => ({ ...p, search: false }))}
            >
              <SearchPanel viewer={viewer} />
            </OverlayPanel>
          ) : (
            <OverlayPanel
              paragraph="II"
              label="Search"
              variant="collapsed"
              onExpand={() => setExpanded((p) => ({ ...p, search: true }))}
            >
              {null}
            </OverlayPanel>
          )}
        </div>

        {/* § Inspector — right slide-in on entity click */}
        <div style={{ position: "absolute", top: 16, right: 64, zIndex: 10 }}>
          <InspectorPanel
            selected={selected}
            onClose={() => setSelected(null)}
            viewer={viewer}
          />
        </div>

        {/* § Ticker — bottom-left, default expanded */}
        <div style={{ position: "absolute", bottom: 16, left: 16, zIndex: 10 }}>
          <TickerPanel />
        </div>
      </div>
    </PerformanceGuard>
  );
}
