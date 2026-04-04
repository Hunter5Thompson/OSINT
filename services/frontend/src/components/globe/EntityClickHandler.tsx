import { useEffect, useState } from "react";
import * as Cesium from "cesium";

const SHIP_TYPES: Record<number, string> = {
  20: "Wing in ground", 30: "Fishing", 31: "Towing", 32: "Towing (large)",
  33: "Dredging", 34: "Diving ops", 35: "Military ops", 36: "Sailing",
  37: "Pleasure craft", 40: "High speed craft", 50: "Pilot vessel",
  51: "SAR", 52: "Tug", 53: "Port tender", 54: "Anti-pollution",
  55: "Law enforcement", 58: "Medical transport", 59: "Noncombatant",
  60: "Passenger", 70: "Cargo", 80: "Tanker", 90: "Other",
};

function shipTypeLabel(code: number): string {
  return SHIP_TYPES[code] ?? SHIP_TYPES[Math.floor(code / 10) * 10] ?? `Type ${code}`;
}

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

      // Guard: Pipeline billboard (custom _pipelineData property)
      const pipelineData = (picked?.primitive as Record<string, unknown>)?._pipelineData as
        | {
            name: string;
            type: string;
            status: string;
            operator: string | null;
            capacity_bcm: number | null;
            length_km: number | null;
            countries: string[];
            lat: number;
            lon: number;
          }
        | undefined;

      if (pipelineData) {
        const props: Record<string, string> = {};
        props.type = pipelineData.type.toUpperCase();
        props.status = pipelineData.status.replace("_", " ").toUpperCase();
        if (pipelineData.operator) props.operator = pipelineData.operator;
        if (pipelineData.capacity_bcm != null) props.capacity = `${pipelineData.capacity_bcm} bcm/yr`;
        if (pipelineData.length_km != null) props.length = `${Math.round(pipelineData.length_km).toLocaleString()} km`;
        if (pipelineData.countries.length > 0) props.countries = pipelineData.countries.join(", ");

        setSelected({
          id: pipelineData.name,
          name: pipelineData.name,
          type: "pipeline",
          position: { lat: pipelineData.lat, lon: pipelineData.lon },
          properties: props,
        });
        return;
      }

      // Guard 3: Vessel billboard (custom _vesselData property)
      const vesselData = (picked?.primitive as Record<string, unknown>)?._vesselData as
        | {
            mmsi: number;
            name: string | null;
            speed_knots: number;
            course: number;
            ship_type: number;
            destination: string | null;
            lat: number;
            lon: number;
          }
        | undefined;

      if (vesselData) {
        const props: Record<string, string> = {};
        props.mmsi = String(vesselData.mmsi);
        if (vesselData.name) props.name = vesselData.name;
        props.speed = `${vesselData.speed_knots.toFixed(1)} kts`;
        props.course = `${Math.round(vesselData.course)}°`;
        if (vesselData.ship_type) props.type = shipTypeLabel(vesselData.ship_type);
        if (vesselData.destination) props.destination = vesselData.destination;

        setSelected({
          id: String(vesselData.mmsi),
          name: vesselData.name ?? `MMSI ${vesselData.mmsi}`,
          type: "vessel",
          position: { lat: vesselData.lat, lon: vesselData.lon },
          properties: props,
        });
        return;
      }

      // Guard 4: Flight billboard
      const flightData = (picked?.primitive as Record<string, unknown>)?._flightData as
        | {
            icao24: string;
            callsign: string | null;
            altitude_m: number;
            velocity_ms: number;
            heading: number;
            vertical_rate: number;
            on_ground: boolean;
            is_military: boolean;
            aircraft_type: string | null;
            lat: number;
            lon: number;
          }
        | undefined;

      if (flightData) {
        const props: Record<string, string> = {};
        props.icao24 = flightData.icao24;
        if (flightData.callsign) props.callsign = flightData.callsign;
        if (flightData.aircraft_type) props.type = flightData.aircraft_type;
        props.altitude = `${Math.round(flightData.altitude_m).toLocaleString()} m (FL${Math.round(flightData.altitude_m / 30.48)})`;
        props.speed = `${Math.round(flightData.velocity_ms * 1.944)} kts (${Math.round(flightData.velocity_ms * 3.6)} km/h)`;
        props.heading = `${Math.round(flightData.heading)}°`;
        if (flightData.vertical_rate !== 0) props.vrate = `${flightData.vertical_rate > 0 ? "+" : ""}${Math.round(flightData.vertical_rate)} m/s`;
        props.status = flightData.on_ground ? "ON GROUND" : flightData.is_military ? "MILITARY" : "AIRBORNE";

        setSelected({
          id: flightData.icao24,
          name: flightData.callsign ?? flightData.icao24,
          type: "aircraft",
          position: { lat: flightData.lat, lon: flightData.lon },
          properties: props,
        });
        return;
      }

      // Guard 4: Satellite point (custom _satelliteData property)
      const satData = (picked?.primitive as Record<string, unknown>)?._satelliteData as
        | {
            norad_id: number;
            name: string;
            category: string;
            inclination_deg: number;
            period_min: number;
            altitude_km: number;
            lat: number;
            lon: number;
          }
        | undefined;

      if (satData) {
        const props: Record<string, string> = {};
        props.norad = String(satData.norad_id);
        props.category = satData.category.toUpperCase();
        props.altitude = `${Math.round(satData.altitude_km).toLocaleString()} km`;
        props.inclination = `${satData.inclination_deg.toFixed(1)}°`;
        props.period = `${satData.period_min.toFixed(1)} min`;

        setSelected({
          id: String(satData.norad_id),
          name: satData.name,
          type: "satellite",
          position: { lat: satData.lat, lon: satData.lon },
          properties: props,
        });
        return;
      }

      // Guard 6: Existing Cesium Entity logic
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
