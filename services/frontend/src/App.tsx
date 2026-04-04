import { useState, useEffect, useCallback } from "react";
import * as Cesium from "cesium";
import { GlobeViewer } from "./components/globe/GlobeViewer";
import { EntityClickHandler } from "./components/globe/EntityClickHandler";
import { FlightLayer } from "./components/layers/FlightLayer";
import { SatelliteLayer } from "./components/layers/SatelliteLayer";
import { EarthquakeLayer } from "./components/layers/EarthquakeLayer";
import { ShipLayer } from "./components/layers/ShipLayer";
import { CCTVLayer } from "./components/layers/CCTVLayer";
import { EventLayer } from "./components/layers/EventLayer";
import { CableLayer } from "./components/layers/CableLayer";
import { PipelineLayer } from "./components/layers/PipelineLayer";
import { OperationsPanel } from "./components/ui/OperationsPanel";
import { RightPanel } from "./components/ui/RightPanel";
import { ThreatRegister } from "./components/ui/ThreatRegister";
import { ClockBar } from "./components/ui/ClockBar";
import { StatusBar } from "./components/ui/StatusBar";
import { useFlights } from "./hooks/useFlights";
import { useSatellites } from "./hooks/useSatellites";
import { useEarthquakes } from "./hooks/useEarthquakes";
import { useEvents } from "./hooks/useEvents";
import { useCables } from "./hooks/useCables";
import { useVessels } from "./hooks/useVessels";
import { usePipelines } from "./hooks/usePipelines";
import { useIntel } from "./hooks/useIntel";
import { getConfig, getHotspots } from "./services/api";
import type { LayerVisibility, ShaderType, Hotspot, ClientConfig } from "./types";

export function App() {
  const [viewer, setViewer] = useState<Cesium.Viewer | null>(null);
  const [config, setConfig] = useState<ClientConfig | null>(null);

  const [layers, setLayers] = useState<LayerVisibility>({
    flights: true,
    satellites: true,
    earthquakes: true,
    vessels: false,
    cctv: false,
    events: false,
    cables: false,
    pipelines: false,
  });

  const [activeShader, setActiveShader] = useState<ShaderType>("none");

  const { flights, lastUpdate: flightsUpdate } = useFlights(layers.flights);
  const { satellites, lastUpdate: satellitesUpdate } = useSatellites(layers.satellites);
  const { earthquakes, lastUpdate: earthquakesUpdate } = useEarthquakes(layers.earthquakes);
  const { events, lastUpdate: eventsUpdate } = useEvents(layers.events);
  const { cables, landingPoints, lastUpdate: cablesUpdate } = useCables(layers.cables);
  const { vessels, lastUpdate: vesselsUpdate } = useVessels(layers.vessels);
  const { pipelines: pipelineData, lastUpdate: pipelinesUpdate } = usePipelines(layers.pipelines);
  const [hotspots, setHotspots] = useState<Hotspot[]>([]);

  const intel = useIntel();

  useEffect(() => {
    void getConfig()
      .then(setConfig)
      .catch(() => {
        setConfig({
          cesium_ion_token: "",
          default_layers: { flights: true, satellites: true, earthquakes: true, vessels: false, cctv: false, events: false, cables: false, pipelines: false },
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
    void getHotspots().then(setHotspots).catch(() => {});
  }, []);

  const handleToggleLayer = useCallback((layer: keyof LayerVisibility) => {
    setLayers((prev) => ({ ...prev, [layer]: !prev[layer] }));
  }, []);

  const handleViewerReady = useCallback((v: Cesium.Viewer) => {
    setViewer(v);
  }, []);

  const handleHotspotSelect = useCallback(
    (hotspot: Hotspot) => {
      viewer?.camera.flyTo({
        destination: Cesium.Cartesian3.fromDegrees(hotspot.longitude, hotspot.latitude, 2_000_000),
        duration: 2.0,
      });
    },
    [viewer],
  );

  const handleIntelQuery = useCallback(
    (query: string, useLegacy: boolean) => {
      intel.runQuery({ query, use_legacy: useLegacy });
    },
    [intel],
  );

  if (!config) {
    return (
      <div className="w-full h-full flex items-center justify-center bg-black">
        <div className="text-green-400 font-mono text-sm animate-pulse">
          INITIALIZING WORLDVIEW...
        </div>
      </div>
    );
  }

  return (
    <div className="w-full h-full relative">
      <GlobeViewer
        onViewerReady={handleViewerReady}
        cesiumToken={config.cesium_ion_token}
        activeShader={activeShader}
      />

      <FlightLayer viewer={viewer} flights={flights} visible={layers.flights} />
      <SatelliteLayer viewer={viewer} satellites={satellites} visible={layers.satellites} />
      <EarthquakeLayer viewer={viewer} earthquakes={earthquakes} visible={layers.earthquakes} />
      <ShipLayer viewer={viewer} vessels={vessels} visible={layers.vessels} />
      <CCTVLayer viewer={viewer} visible={layers.cctv} />
      <EventLayer viewer={viewer} events={events} visible={layers.events} />
      <CableLayer viewer={viewer} cables={cables} landingPoints={landingPoints} visible={layers.cables} />
      <PipelineLayer viewer={viewer} pipelines={pipelineData} visible={layers.pipelines} />

      <EntityClickHandler viewer={viewer} />

      <ClockBar />

      <OperationsPanel
        layers={layers}
        onToggleLayer={handleToggleLayer}
        activeShader={activeShader}
        onShaderChange={setActiveShader}
      />

      <RightPanel
        loading={intel.loading}
        currentAgent={intel.currentAgent}
        result={intel.result}
        error={intel.error}
        history={intel.history}
        onQuery={handleIntelQuery}
      />

      <ThreatRegister hotspots={hotspots} onSelect={handleHotspotSelect} />

      <StatusBar
        freshness={{
          flights: flightsUpdate,
          satellites: satellitesUpdate,
          earthquakes: earthquakesUpdate,
          vessels: vesselsUpdate,
          events: eventsUpdate,
          cables: cablesUpdate,
          pipelines: pipelinesUpdate,
        }}
        flightCount={flights.length}
        satelliteCount={satellites.length}
        earthquakeCount={earthquakes.length}
        vesselCount={vessels.length}
        eventCount={events.length}
        cableCount={cables.length}
        pipelineCount={pipelineData?.features.length ?? 0}
      />
    </div>
  );
}
