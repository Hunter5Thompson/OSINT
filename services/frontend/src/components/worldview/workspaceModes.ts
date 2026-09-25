import type { LayerVisibility } from "../../types";
export const WORKSPACE_MODES = [
  {
    id: "overview",
    label: "Situation",
    description: "Events, earthquakes and disaster alerts",
  },
  {
    id: "movement",
    label: "Movement",
    description: "Civilian flights, military aircraft and vessels",
  },
  {
    id: "infrastructure",
    label: "Infrastructure",
    description: "Cables, pipelines, refineries and datacenters",
  },
] as const;
export type WorkspaceMode = (typeof WORKSPACE_MODES)[number]["id"];
export function layersForMode(mode: WorkspaceMode): LayerVisibility {
  return {
    nuclearPlants: mode === "infrastructure",
    icbmBases: false,
    militaryBases: false,
    countryBorders: true,
    cityBuildings: true,
    recon: true,
    flights: mode === "movement",
    milAircraft: mode === "movement",
    vessels: mode === "movement",
    events: mode === "overview",
    earthquakes: mode === "overview",
    gdacs: mode === "overview",
    cables: mode === "infrastructure",
    pipelines: mode === "infrastructure",
    refineries: mode === "infrastructure",
    datacenters: mode === "infrastructure",
    satellites: false,
    firmsHotspots: false,
    eonet: false,
    cctv: false,
  };
}
export function selectedWorkspaceMode(
  layers: LayerVisibility,
): WorkspaceMode | null {
  return (
    WORKSPACE_MODES.find(({ id }) => {
      const preset = layersForMode(id);
      return (Object.keys(preset) as (keyof LayerVisibility)[]).every(
        (key) => layers[key] === preset[key],
      );
    })?.id ?? null
  );
}
