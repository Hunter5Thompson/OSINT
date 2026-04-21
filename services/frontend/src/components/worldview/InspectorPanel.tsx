import type * as Cesium from "cesium";
import type { FIRMSHotspot } from "../../types";
import { OverlayPanel } from "../hlidskjalf/OverlayPanel";

export type Selected =
  | { type: "firms"; data: FIRMSHotspot }
  | { type: "aircraft"; data: unknown }
  | { type: "datacenter"; data: unknown }
  | { type: "refinery"; data: unknown }
  | { type: "eonet"; data: unknown }
  | { type: "gdacs"; data: unknown };

export interface InspectorPanelProps {
  selected: Selected | null;
  onClose: () => void;
  viewer: Cesium.Viewer | null;
}

export function InspectorPanel({ selected, onClose }: InspectorPanelProps) {
  return (
    <OverlayPanel
      paragraph="III"
      label="Inspector"
      variant={selected ? "expanded" : "hidden"}
      onClose={onClose}
      width={360}
    >
      <div className="mono" style={{ color: "var(--stone)" }}>
        § placeholder — {selected?.type ?? "nothing selected"}
      </div>
    </OverlayPanel>
  );
}
