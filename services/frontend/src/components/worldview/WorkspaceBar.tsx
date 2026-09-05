import type { LayerVisibility } from "../../types";
import {
  selectedWorkspaceMode,
  WORKSPACE_MODES,
  type WorkspaceMode,
} from "./workspaceModes";
interface Props {
  layers: LayerVisibility;
  focusMode: boolean;
  onMode: (mode: WorkspaceMode) => void;
  onFocus: () => void;
}
export function WorkspaceBar({ layers, focusMode, onMode, onFocus }: Props) {
  const selected = selectedWorkspaceMode(layers);
  return (
    <div className="workspace-bar">
      <div className="workspace-identity">
        <span className="eyebrow">WORLDVIEW</span>
        <span>Explore the connections.</span>
      </div>
      <div
        className="workspace-modes"
        role="group"
        aria-label="Map working mode"
      >
        {WORKSPACE_MODES.map((mode) => (
          <button
            key={mode.id}
            type="button"
            aria-pressed={selected === mode.id}
            title={mode.description}
            onClick={() => onMode(mode.id)}
          >
            {mode.label}
          </button>
        ))}
      </div>
      <span className="workspace-layer-count">
        {Object.values(layers).filter(Boolean).length} selected
        {selected === null ? " · custom" : ""}
      </span>
      <button
        className="workspace-focus"
        type="button"
        aria-pressed={focusMode}
        aria-label={focusMode ? "Exit focus mode" : "Enter focus mode"}
        onClick={onFocus}
      >
        {focusMode ? "Show panels" : "Focus map"}
        <kbd>F</kbd>
      </button>
    </div>
  );
}
