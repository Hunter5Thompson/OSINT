import { useState, useEffect, useCallback } from "react";
import * as Cesium from "cesium";
import { GlobeViewer } from "./components/globe/GlobeViewer";
import { EntityClickHandler } from "./components/globe/EntityClickHandler";
import { FlightLayer } from "./components/layers/FlightLayer";
import { SatelliteLayer } from "./components/layers/SatelliteLayer";
import { EarthquakeLayer } from "./components/layers/EarthquakeLayer";
import { ShipLayer } from "./components/layers/ShipLayer";
import { CCTVLayer } from "./components/layers/CCTVLayer";
import { OperationsPanel } from "./components/ui/OperationsPanel";
import { IntelPanel } from "./components/ui/IntelPanel";
import { ThreatRegister } from "./components/ui/ThreatRegister";
import { ClockBar } from "./components/ui/ClockBar";
import { StatusBar } from "./components/ui/StatusBar";
import { useFlights } from "./hooks/useFlights";
import { useSatellites } from "./hooks/useSatellites";
import { useEarthquakes } from "./hooks/useEarthquakes";
import { useIntel } from "./hooks/useIntel";
import { getConfig, getHotspots, getVessels } from "./services/api";
import type { LayerVisibility, ShaderType, Hotspot, Vessel, ClientConfig } from "./types";

export function App() {
  // Viewer
  const [viewer, setViewer] = useState<Cesium.Viewer | null>(null);
  const [config, setConfig] = useState<ClientConfig | null>(null);

  // Layer visibility
  const [layers, setLayers] = useState<LayerVisibility>({
    flights: true,
    satellites: true,
    earthquakes: true,
    vessels: false,
    cctv: false,
  });

  // Shader
  const [activeShader, setActiveShader] = useState<ShaderType>("none");

  // Data
  const { flights, lastUpdate: flightsUpdate } = useFlights(layers.flights);
  const { satellites, lastUpdate: satellitesUpdate } = useSatellites(layers.satellites);
  const { earthquakes, lastUpdate: earthquakesUpdate } = useEarthquakes(layers.earthquakes);
  const [vessels, setVessels] = useState<Vessel[]>([]);
  const [hotspots, setHotspots] = useState<Hotspot[]>([]);

  // Intel
  const intel = useIntel();

  // Load config
  useEffect(() => {
    void getConfig()
      .then(setConfig)
      .catch(() => {
        // Use empty token as fallback
        setConfig({
          cesium_ion_token: "",
          default_layers: { flights: true, satellites: true, earthquakes: true, vessels: false, cctv: false },
          api_version: "v1",
        });
      });
  }, []);

  // Load hotspots
  useEffect(() => {
    void getHotspots().then(setHotspots).catch(() => {});
  }, []);

  // Poll vessels
  useEffect(() => {
    if (!layers.vessels) return;
    const fetch = () => void getVessels().then(setVessels).catch(() => {});
    fetch();
    const timer = setInterval(fetch, 60_000);
    return () => clearInterval(timer);
  }, [layers.vessels]);

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
    (query: string) => {
      intel.runQuery({ query });
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
      {/* 3D Globe */}
      <GlobeViewer
        onViewerReady={handleViewerReady}
        cesiumToken={config.cesium_ion_token}
        activeShader={activeShader}
      />

      {/* Data Layers */}
      <FlightLayer viewer={viewer} flights={flights} visible={layers.flights} />
      <SatelliteLayer viewer={viewer} satellites={satellites} visible={layers.satellites} />
      <EarthquakeLayer viewer={viewer} earthquakes={earthquakes} visible={layers.earthquakes} />
      <ShipLayer viewer={viewer} vessels={vessels} visible={layers.vessels} />
      <CCTVLayer viewer={viewer} visible={layers.cctv} />

      {/* Click Handler */}
      <EntityClickHandler viewer={viewer} />

      {/* UI Overlay */}
      <ClockBar />

      <OperationsPanel
        layers={layers}
        onToggleLayer={handleToggleLayer}
        activeShader={activeShader}
        onShaderChange={setActiveShader}
      />

      <IntelPanel
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
          vessels: null,
        }}
        flightCount={flights.length}
        satelliteCount={satellites.length}
        earthquakeCount={earthquakes.length}
        vesselCount={vessels.length}
      />
    </div>
  );
}
