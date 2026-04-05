import type { LayerVisibility, ShaderType } from "../../types";

interface OperationsPanelProps {
  layers: LayerVisibility;
  onToggleLayer: (layer: keyof LayerVisibility) => void;
  activeShader: ShaderType;
  onShaderChange: (shader: ShaderType) => void;
}

const LAYER_CONFIG: { key: keyof LayerVisibility; label: string; color: string }[] = [
  { key: "flights", label: "FLIGHTS", color: "#c4813a" },
  { key: "satellites", label: "SATELLITES", color: "#06b6d4" },
  { key: "earthquakes", label: "EARTHQUAKES", color: "#ef4444" },
  { key: "vessels", label: "VESSELS", color: "#4fc3f7" },
  { key: "cctv", label: "CCTV", color: "#d4cdc0" },
  { key: "events", label: "EVENTS", color: "#f97316" },
  { key: "cables", label: "CABLES", color: "#22c55e" },
  { key: "pipelines", label: "PIPELINES", color: "#eab308" },
];

function LayerIcon({ layerKey, color }: { layerKey: string; color: string }) {
  const s = { width: 16, height: 16, viewBox: "0 0 32 32", fill: "none" } as const;
  switch (layerKey) {
    case "flights":
      return (<svg {...s}><path d="M16 6 L22 20 L16 17 L10 20 Z" fill={color} opacity={0.8} /></svg>);
    case "satellites":
      return (<svg {...s}><circle cx={16} cy={16} r={5} fill={color} opacity={0.8} /><ellipse cx={16} cy={16} rx={14} ry={6} transform="rotate(-20 16 16)" stroke={color} strokeWidth={1} opacity={0.4} fill="none" /></svg>);
    case "earthquakes":
      return (<svg {...s}><circle cx={16} cy={16} r={8} stroke={color} strokeWidth={2} opacity={0.6} fill="none" /><circle cx={16} cy={16} r={3} fill={color} opacity={0.9} /></svg>);
    case "vessels":
      return (<svg {...s}><path d="M16 6 L22 16 L16 14 L10 16 Z" fill={color} opacity={0.8} /><path d="M10 18 L22 18 L20 26 L12 26 Z" fill={color} opacity={0.4} /></svg>);
    case "cctv":
      return (<svg {...s}><rect x={10} y={12} width={12} height={8} rx={2} fill={color} opacity={0.6} /><path d="M22 14 L28 10 L28 22 L22 18 Z" fill={color} opacity={0.4} /><circle cx={15} cy={16} r={2} fill={color} opacity={0.9} /></svg>);
    case "events":
      return (<svg {...s}><circle cx={16} cy={16} r={10} stroke={color} strokeWidth={1.5} opacity={0.4} fill="none" /><circle cx={16} cy={16} r={5} stroke={color} strokeWidth={1.5} opacity={0.6} fill="none" /><circle cx={16} cy={16} r={2} fill={color} opacity={0.9} /></svg>);
    case "cables":
      return (<svg {...s}><path d="M4 24 C10 24 10 8 16 8 C22 8 22 24 28 24" stroke={color} strokeWidth={2} opacity={0.7} fill="none" /></svg>);
    case "pipelines":
      return (<svg {...s}><path d="M4 16 Q10 10 16 16 Q22 22 28 16" stroke={color} strokeWidth={2.5} opacity={0.7} fill="none" /><circle cx={4} cy={16} r={3} fill={color} opacity={0.6} /><circle cx={28} cy={16} r={3} fill={color} opacity={0.6} /></svg>);
    default:
      return <span style={{ color }}>●</span>;
  }
}

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
        {LAYER_CONFIG.map(({ key, label, color }) => (
          <button
            key={key}
            onClick={() => onToggleLayer(key)}
            className="w-full flex items-center gap-2 px-2 py-1.5 rounded mb-1 transition-colors border"
            style={layers[key] ? {
              backgroundColor: `${color}1a`,
              borderColor: `${color}4d`,
              color: color,
            } : {
              color: "rgba(0, 255, 65, 0.4)",
              borderColor: "transparent",
            }}
          >
            <span className="w-4 flex items-center justify-center" style={{ opacity: layers[key] ? 1 : 0.3 }}>
              <LayerIcon layerKey={key} color={color} />
            </span>
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
