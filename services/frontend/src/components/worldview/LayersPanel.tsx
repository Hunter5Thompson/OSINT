import type { CSSProperties } from "react";
import type { LayerVisibility, ShaderType } from "../../types";

export interface LayersPanelProps {
  layers: LayerVisibility;
  onToggle: (layer: keyof LayerVisibility) => void;
  activeShader: ShaderType;
  onShaderChange: (shader: ShaderType) => void;
}

interface LayerDef {
  key: keyof LayerVisibility;
  label: string;
}

interface GroupDef {
  title: string;
  layers: LayerDef[];
}

const GROUPS: GroupDef[] = [
  {
    title: "Incidents",
    layers: [
      { key: "earthquakes", label: "Earthquakes" },
      { key: "firmsHotspots", label: "FIRMS Hotspots" },
      { key: "events", label: "Events" },
      { key: "eonet", label: "EONET" },
      { key: "gdacs", label: "GDACS" },
    ],
  },
  {
    title: "Transport",
    layers: [
      { key: "flights", label: "Flights" },
      { key: "milAircraft", label: "Military Aircraft" },
      { key: "vessels", label: "Vessels" },
      { key: "satellites", label: "Satellites" },
    ],
  },
  {
    title: "Infrastructure",
    layers: [
      { key: "cables", label: "Submarine Cables" },
      { key: "pipelines", label: "Pipelines" },
      { key: "datacenters", label: "Datacenters" },
      { key: "refineries", label: "Energy/Chem Sites" },
      { key: "countryBorders", label: "Country Borders" },
      { key: "cityBuildings", label: "3D Buildings" },
      { key: "cctv", label: "CCTV" },
    ],
  },
];

const SHADERS: Array<{ id: ShaderType; label: string }> = [
  { id: "none", label: "Standard" },
  { id: "crt", label: "CRT" },
  { id: "nightvision", label: "Night Vision" },
  { id: "flir", label: "FLIR" },
];

const groupTitle: CSSProperties = {
  marginBottom: "0.4rem",
  fontFamily: '"Martian Mono", ui-monospace, monospace',
  fontSize: "0.62rem",
  letterSpacing: "0.16em",
  textTransform: "uppercase",
  color: "var(--ash)",
};

const row: CSSProperties = {
  display: "flex",
  alignItems: "center",
  justifyContent: "space-between",
  gap: "0.5rem",
  padding: "0.24rem 0",
};

const toggleBtn: CSSProperties = {
  width: 18,
  height: 18,
  border: "1px solid var(--granite)",
  background: "transparent",
  color: "var(--bone)",
  cursor: "pointer",
  fontFamily: '"Martian Mono", ui-monospace, monospace',
  fontSize: "0.62rem",
  lineHeight: 1,
};

export function LayersPanel({
  layers,
  onToggle,
  activeShader,
  onShaderChange,
}: LayersPanelProps) {
  return (
    <div style={{ display: "grid", gap: "0.8rem" }}>
      {GROUPS.map((group) => (
        <section key={group.title}>
          <div style={groupTitle}>{`§ ${group.title}`}</div>
          <div style={{ display: "grid", gap: "0.15rem" }}>
            {group.layers.map((layer) => {
              const enabled = layers[layer.key];
              return (
                <div key={layer.key} style={row}>
                  <span style={{ color: enabled ? "var(--bone)" : "var(--stone)", fontSize: "0.78rem" }}>
                    {layer.label}
                  </span>
                  <button
                    type="button"
                    aria-label={layer.key}
                    aria-pressed={enabled}
                    onClick={() => onToggle(layer.key)}
                    style={{
                      ...toggleBtn,
                      borderColor: enabled ? "var(--amber)" : "var(--granite)",
                      color: enabled ? "var(--amber)" : "var(--stone)",
                    }}
                  >
                    {enabled ? "ON" : "OFF"}
                  </button>
                </div>
              );
            })}
          </div>
        </section>
      ))}

      <section>
        <div style={groupTitle}>§ Visual Filter</div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(2, minmax(0, 1fr))", gap: "0.4rem" }}>
          {SHADERS.map((shader) => {
            const active = activeShader === shader.id;
            return (
              <button
                key={shader.id}
                type="button"
                onClick={() => onShaderChange(shader.id)}
                style={{
                  border: `1px solid ${active ? "var(--amber)" : "var(--granite)"}`,
                  background: active ? "rgba(196, 129, 58, 0.12)" : "transparent",
                  color: active ? "var(--parchment)" : "var(--stone)",
                  padding: "0.34rem 0.45rem",
                  cursor: "pointer",
                  fontFamily: '"Martian Mono", ui-monospace, monospace',
                  fontSize: "0.62rem",
                  letterSpacing: "0.08em",
                  textTransform: "uppercase",
                }}
              >
                {shader.label}
              </button>
            );
          })}
        </div>
      </section>
    </div>
  );
}
