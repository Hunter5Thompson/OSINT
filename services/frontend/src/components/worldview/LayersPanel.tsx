import type { CSSProperties } from "react";
import type { LayerVisibility, ShaderType } from "../../types";

export interface LayersPanelProps {
  layers: LayerVisibility;
  onToggle: (layer: keyof LayerVisibility) => void;
  activeShader: ShaderType;
  onShaderChange: (shader: ShaderType) => void;
}

type AlwaysOnKey = "void" | "atmosphere" | "spotlight";
type ToggleKey = keyof LayerVisibility;
type ItemKey = ToggleKey | AlwaysOnKey;

interface PanelItem {
  key: ItemKey;
  label: string;
}

interface PanelGroup {
  group: "A · sky" | "B · earth" | "C · signal · network" | "C · signal · glyphs" | "D · lens & chrome";
  always?: boolean;
  items: PanelItem[];
}

const PANEL_GROUPS: PanelGroup[] = [
  {
    group: "A · sky",
    always: true,
    items: [
      { key: "void", label: "Void & Stars" },
      { key: "atmosphere", label: "Atmosphere" },
    ],
  },
  {
    group: "B · earth",
    items: [
      { key: "countryBorders", label: "Country Borders" },
      { key: "cityBuildings", label: "City Buildings" },
    ],
  },
  {
    group: "C · signal · network",
    items: [
      { key: "cables", label: "Cables" },
      { key: "pipelines", label: "Pipelines" },
      { key: "satellites", label: "Satellites" },
    ],
  },
  {
    group: "C · signal · glyphs",
    items: [
      { key: "flights", label: "Flights" },
      { key: "earthquakes", label: "Earthquakes" },
      { key: "vessels", label: "Vessels" },
      { key: "cctv", label: "CCTV" },
      { key: "events", label: "Graph Events" },
      { key: "firmsHotspots", label: "FIRMS Hotspots" },
      { key: "milAircraft", label: "Mil-air" },
      { key: "datacenters", label: "Datacenters" },
      { key: "refineries", label: "Refineries" },
      { key: "eonet", label: "EONET" },
      { key: "gdacs", label: "GDACS" },
    ],
  },
  {
    group: "D · lens & chrome",
    always: true,
    items: [
      { key: "spotlight", label: "Spotlight" },
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

const separator: CSSProperties = {
  border: "none",
  borderTop: "1px solid var(--granite)",
  margin: "0.4rem 0 0.6rem",
  opacity: 0.4,
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

const alwaysOnBadge: CSSProperties = {
  width: 18,
  height: 18,
  border: "1px solid var(--granite)",
  background: "transparent",
  color: "var(--stone)",
  fontFamily: '"Martian Mono", ui-monospace, monospace',
  fontSize: "0.55rem",
  lineHeight: 1,
  display: "flex",
  alignItems: "center",
  justifyContent: "center",
  opacity: 0.5,
};

export function LayersPanel({
  layers,
  onToggle,
  activeShader,
  onShaderChange,
}: LayersPanelProps) {
  return (
    <div style={{ display: "grid", gap: "0.8rem" }}>
      {PANEL_GROUPS.map((group, groupIndex) => (
        <section key={group.group}>
          {groupIndex > 0 && <hr style={separator} />}
          <div style={groupTitle}>{`§ ${group.group}`}</div>
          <div style={{ display: "grid", gap: "0.15rem" }}>
            {group.items.map((item) => {
              if (group.always) {
                // Always-on items: display-only, no interactive toggle
                return (
                  <div key={item.key} style={row} data-testid={`layer-toggle-${item.key}`}>
                    <span style={{ color: "var(--stone)", fontSize: "0.78rem" }}>
                      {item.label}
                    </span>
                    <div style={alwaysOnBadge} aria-hidden="true">∞</div>
                  </div>
                );
              }

              // Regular toggle item — key is guaranteed to be a LayerVisibility key
              const toggleKey = item.key as ToggleKey;
              const enabled = layers[toggleKey];
              return (
                <div key={item.key} style={row} data-testid={`layer-toggle-${item.key}`}>
                  <span style={{ color: enabled ? "var(--bone)" : "var(--stone)", fontSize: "0.78rem" }}>
                    {item.label}
                  </span>
                  <button
                    type="button"
                    aria-label={toggleKey}
                    aria-pressed={enabled}
                    onClick={() => onToggle(toggleKey)}
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
        <hr style={separator} />
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
