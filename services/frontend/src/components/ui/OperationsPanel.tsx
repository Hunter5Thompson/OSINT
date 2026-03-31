import type { LayerVisibility, ShaderType } from "../../types";

interface OperationsPanelProps {
  layers: LayerVisibility;
  onToggleLayer: (layer: keyof LayerVisibility) => void;
  activeShader: ShaderType;
  onShaderChange: (shader: ShaderType) => void;
}

const LAYER_CONFIG: { key: keyof LayerVisibility; label: string; icon: string }[] = [
  { key: "flights", label: "FLIGHTS", icon: "^" },
  { key: "satellites", label: "SATELLITES", icon: "*" },
  { key: "earthquakes", label: "EARTHQUAKES", icon: "~" },
  { key: "vessels", label: "VESSELS", icon: "%" },
  { key: "cctv", label: "CCTV", icon: "@" },
  { key: "events", label: "EVENTS", icon: "!" },
  { key: "cables", label: "CABLES", icon: "#" },
];

const SHADER_OPTIONS: { value: ShaderType; label: string }[] = [
  { value: "none", label: "STANDARD" },
  { value: "crt", label: "CRT" },
  { value: "nightvision", label: "NIGHT VISION" },
  { value: "flir", label: "FLIR/THERMAL" },
];

export function OperationsPanel({
  layers,
  onToggleLayer,
  activeShader,
  onShaderChange,
}: OperationsPanelProps) {
  return (
    <div className="absolute left-3 top-16 w-56 bg-black/85 border border-green-500/20 rounded font-mono text-xs z-40 backdrop-blur-sm">
      {/* Header */}
      <div className="px-3 py-2 border-b border-green-500/20 text-green-400 font-bold tracking-wider">
        OPERATIONS
      </div>

      {/* Layer Toggles */}
      <div className="p-3">
        <div className="text-green-500/60 mb-2 text-[10px] tracking-widest">DATA LAYERS</div>
        {LAYER_CONFIG.map(({ key, label, icon }) => (
          <button
            key={key}
            onClick={() => onToggleLayer(key)}
            className={`w-full flex items-center gap-2 px-2 py-1.5 rounded mb-1 transition-colors
              ${layers[key]
                ? "bg-green-500/10 text-green-400 border border-green-500/30"
                : "text-green-500/40 hover:text-green-500/60 border border-transparent"
              }`}
          >
            <span className="w-4 text-center">{icon}</span>
            <span>{label}</span>
            <span className="ml-auto text-[10px]">{layers[key] ? "ON" : "OFF"}</span>
          </button>
        ))}
      </div>

      {/* Shader Selector */}
      <div className="p-3 border-t border-green-500/20">
        <div className="text-green-500/60 mb-2 text-[10px] tracking-widest">VISUAL FILTER</div>
        {SHADER_OPTIONS.map(({ value, label }) => (
          <button
            key={value}
            onClick={() => onShaderChange(value)}
            className={`w-full text-left px-2 py-1.5 rounded mb-1 transition-colors
              ${activeShader === value
                ? "bg-amber-500/10 text-amber-400 border border-amber-500/30"
                : "text-green-500/40 hover:text-green-500/60 border border-transparent"
              }`}
          >
            {label}
          </button>
        ))}
      </div>
    </div>
  );
}
