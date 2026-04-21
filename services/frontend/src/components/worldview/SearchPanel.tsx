import type * as Cesium from "cesium";

export interface SearchPanelProps {
  viewer: Cesium.Viewer | null;
}

export function SearchPanel(_props: SearchPanelProps) {
  return <div className="mono" style={{ color: "var(--stone)" }}>§ placeholder</div>;
}
