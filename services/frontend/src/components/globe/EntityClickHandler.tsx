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

      // Guard 1: Event billboard (custom _eventData property)
      const eventData = (picked?.primitive as Record<string, unknown>)?._eventData as
        | { id: string; title: string; codebook_type: string; lat: number; lon: number; severity: string; location_name?: string }
        | undefined;

      if (eventData) {
        setSelected({
          id: eventData.id,
          name: eventData.title,
          type: eventData.codebook_type,
          position: { lat: eventData.lat, lon: eventData.lon },
          properties: {
            severity: eventData.severity,
            location: eventData.location_name ?? "",
          },
        });
        return;
      }

      // Guard 2: Cable billboard (custom _cableData property)
      const cableData = (picked?.primitive as Record<string, unknown>)?._cableData as
        | {
            id: string;
            name: string;
            owners: string | null;
            capacity_tbps: number | null;
            length_km: number | null;
            rfs: string | null;
            is_planned: boolean;
            url: string | null;
            landing_points: string[];
            lat: number;
            lon: number;
          }
        | undefined;

      if (cableData) {
        const props: Record<string, string> = {};
        if (cableData.owners) props.owners = cableData.owners;
        if (cableData.capacity_tbps != null) props.capacity = `${cableData.capacity_tbps} Tbps`;
        if (cableData.length_km != null) props.length = `${Math.round(cableData.length_km).toLocaleString()} km`;
        if (cableData.rfs) props.rfs = cableData.rfs;
        props.status = cableData.is_planned ? "PLANNED" : "ACTIVE";
        if (cableData.landing_points.length > 0) props.landings = cableData.landing_points.join(", ");
        if (cableData.url) props.info = cableData.url;

        setSelected({
          id: cableData.id,
          name: cableData.name,
          type: "submarine_cable",
          position: { lat: cableData.lat, lon: cableData.lon },
          properties: props,
        });
        return;
      }

      // Guard 3: Existing Cesium Entity logic
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
      {Object.keys(selected.properties).length > 0 && (
        <div className="mt-1 border-t border-green-500/20 pt-1">
          {Object.entries(selected.properties).map(([k, v]) =>
            v ? (
              <div key={k} className="text-green-500/50">
                <span className="text-green-500/30">{k}:</span> {v}
              </div>
            ) : null,
          )}
        </div>
      )}
    </div>
  );
}
