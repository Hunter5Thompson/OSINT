import { useEffect, useState } from "react";
import * as Cesium from "cesium";

interface EntityClickHandlerProps {
  viewer: Cesium.Viewer | null;
}

interface SelectedEntity {
  id: string;
  name: string;
  type: string;
  position: { lat: number; lon: number };
  properties: Record<string, string>;
}

export function EntityClickHandler({ viewer }: EntityClickHandlerProps) {
  const [selected, setSelected] = useState<SelectedEntity | null>(null);

  useEffect(() => {
    if (!viewer || viewer.isDestroyed()) return;

    const handler = new Cesium.ScreenSpaceEventHandler(viewer.scene.canvas);

    handler.setInputAction((movement: Cesium.ScreenSpaceEventHandler.PositionedEvent) => {
      const picked = viewer.scene.pick(movement.position);
      if (Cesium.defined(picked) && picked.id) {
        const entity = picked.id;
        const props = entity.properties;
        const position = entity.position?.getValue(viewer.clock.currentTime);

        if (position) {
          const carto = Cesium.Cartographic.fromCartesian(position);
          setSelected({
            id: entity.id,
            name: entity.name ?? "Unknown",
            type: props?.type?.getValue(viewer.clock.currentTime) ?? "unknown",
            position: {
              lat: Cesium.Math.toDegrees(carto.latitude),
              lon: Cesium.Math.toDegrees(carto.longitude),
            },
            properties: {},
          });
        }
      } else {
        setSelected(null);
      }
    }, Cesium.ScreenSpaceEventType.LEFT_CLICK);

    return () => {
      handler.destroy();
    };
  }, [viewer]);

  if (!selected) return null;

  return (
    <div className="absolute bottom-20 left-1/2 -translate-x-1/2 bg-black/80 border border-green-500/30 p-3 rounded text-xs font-mono text-green-400 z-50">
      <div className="text-green-300 font-bold">{selected.name}</div>
      <div>
        {selected.position.lat.toFixed(4)}, {selected.position.lon.toFixed(4)}
      </div>
      <div className="text-green-500/60 mt-1">{selected.type}</div>
    </div>
  );
}
