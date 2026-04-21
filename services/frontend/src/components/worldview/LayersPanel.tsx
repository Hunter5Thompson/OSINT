import type { LayerVisibility, ShaderType } from "../../types";

export interface LayersPanelProps {
  layers: LayerVisibility;
  onToggle: (layer: keyof LayerVisibility) => void;
  activeShader: ShaderType;
  onShaderChange: (shader: ShaderType) => void;
}

export function LayersPanel(_props: LayersPanelProps) {
  return <div className="mono" style={{ color: "var(--stone)" }}>§ placeholder</div>;
}
