import type { CSSProperties } from "react";
import type { LayerVisibility, ShaderType } from "../../types";

export interface LayersPanelProps {
  layers: LayerVisibility;
  onToggle: (layer: keyof LayerVisibility) => void;
  activeShader: ShaderType;
  onShaderChange: (shader: ShaderType) => void;
}

interface Group {
  title: string;
  keys: (keyof LayerVisibility)[];
}

const GROUPS: Group[] = [
  { title: "Incidents", keys: ["earthquakes", "firmsHotspots", "events", "eonet", "gdacs"] },
  { title: "Transport", keys: ["flights", "milAircraft", "vessels"] },
  { title: "Infrastructure", keys: ["cables", "pipelines", "datacenters", "refineries", "countryBorders", "cityBuildings"] },
  { title: "Atmosphere", keys: ["satellites", "cctv"] },
];

const groupStyle: CSSProperties = {
  marginBottom: "14px",
};

const groupTitle: CSSProperties = {
  fontFamily: "'Hanken Grotesk', sans-serif",
  fontSize: "10px",
  letterSpacing: "0.3em",
  textTransform: "uppercase",
  color: "var(--ash)",
  marginBottom: "6px",
};

const rowStyle: CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: "8px",
  padding: "4px 0",
  fontFamily: "'Hanken Grotesk', sans-serif",
  fontSize: "12px",
  color: "var(--bone)",
  cursor: "pointer",
};

const dotOn: CSSProperties = {
  width: "6px",
  height: "6px",
  borderRadius: "50%",
  background: "var(--amber)",
};

const dotOff: CSSProperties = {
  width: "6px",
  height: "6px",
  borderRadius: "50%",
  background: "transparent",
  border: "1px solid var(--granite)",
};

// Visually hidden but keeps the input in the accessibility tree so
// getByRole("checkbox") still finds it. `display: none` would remove it.
const visuallyHidden: CSSProperties = {
  position: "absolute",
  width: 1,
  height: 1,
  padding: 0,
  margin: -1,
  overflow: "hidden",
  clip: "rect(0 0 0 0)",
  whiteSpace: "nowrap",
  border: 0,
};

export function LayersPanel({ layers, onToggle }: LayersPanelProps) {
  return (
    <div>
      {GROUPS.map((group) => (
        <div key={group.title} style={groupStyle}>
          <div style={groupTitle}>§ {group.title}</div>
          {group.keys.map((key) => (
            <label key={key} style={rowStyle}>
              <input
                type="checkbox"
                checked={layers[key]}
                onChange={() => onToggle(key)}
                aria-label={key}
                style={visuallyHidden}
              />
              <span style={layers[key] ? dotOn : dotOff} aria-hidden="true" />
              <span>{key}</span>
            </label>
          ))}
        </div>
      ))}
    </div>
  );
}
