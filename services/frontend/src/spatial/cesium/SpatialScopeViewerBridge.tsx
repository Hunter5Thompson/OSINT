import { useEffect } from "react";

export interface SpatialViewerBridgePort {
  attachViewer(viewer: object): void;
  detachViewer(viewer: object): void;
}

export interface SpatialScopeViewerBridgeProps {
  readonly viewer: object | null;
  readonly bridge: SpatialViewerBridgePort;
}

export function SpatialScopeViewerBridge({
  viewer,
  bridge,
}: SpatialScopeViewerBridgeProps) {
  useEffect(() => {
    if (viewer === null) return;
    bridge.attachViewer(viewer);
    return () => bridge.detachViewer(viewer);
  }, [bridge, viewer]);

  return null;
}
