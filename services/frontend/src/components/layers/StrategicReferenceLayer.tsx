import { useEffect, useRef } from "react";
import * as Cesium from "cesium";
import type { LayerVisibility } from "../../types";
import { decodeSites, useReferenceData, type StrategicKind, type StrategicSite } from "./referenceData";

const COLORS: Record<StrategicKind, string> = { nuclearPlants: "#e8c66a", icbmBases: "#f18e7c", militaryBases: "#8ec8c6" };
export function createStrategicIcon(kind: StrategicKind): HTMLCanvasElement {
  const canvas = document.createElement("canvas");
  canvas.width = canvas.height = 64;
  const ctx = canvas.getContext("2d");
  if (!ctx) return canvas;
  ctx.translate(32, 32);
  ctx.fillStyle = "#101b24";
  ctx.strokeStyle = COLORS[kind];
  ctx.lineWidth = 2;
  ctx.beginPath();
  for (let i = 0; i < 6; i++) {
    const a = Math.PI * i / 3;
    if (i === 0) ctx.moveTo(27 * Math.cos(a), 27 * Math.sin(a));
    else ctx.lineTo(27 * Math.cos(a), 27 * Math.sin(a));
  }
  ctx.closePath(); ctx.fill(); ctx.stroke();
  ctx.strokeStyle = COLORS[kind];
  ctx.fillStyle = COLORS[kind];
  if (kind === "nuclearPlants") {
    for (let i = 0; i < 3; i++) {
      ctx.save(); ctx.rotate(i * Math.PI / 3);
      ctx.beginPath(); ctx.ellipse(0, 0, 17, 7, 0, 0, Math.PI * 2); ctx.stroke(); ctx.restore();
    }
    ctx.beginPath(); ctx.arc(0, 0, 3, 0, Math.PI * 2); ctx.fill();
  } else if (kind === "icbmBases") {
    ctx.beginPath(); ctx.moveTo(0, -18); ctx.lineTo(5, -7); ctx.lineTo(5, 10);
    ctx.lineTo(10, 16); ctx.lineTo(0, 12); ctx.lineTo(-10, 16);
    ctx.lineTo(-5, 10); ctx.lineTo(-5, -7); ctx.closePath(); ctx.fill();
  } else {
    ctx.beginPath(); ctx.moveTo(-14, -13); ctx.lineTo(14, -13); ctx.lineTo(12, 6);
    ctx.lineTo(0, 18); ctx.lineTo(-12, 6); ctx.closePath(); ctx.stroke();
    ctx.fillRect(-8, -5, 16, 3); ctx.fillRect(-2, -10, 4, 18);
  }
  return canvas;
}

export function StrategicReferenceLayer({ viewer, layers, onSelect }: {
  viewer: Cesium.Viewer | null; layers: LayerVisibility; onSelect: (site: StrategicSite) => void;
}) {
  const nuclear = useReferenceData("/data/nuclear-sites.json", layers.nuclearPlants, decodeSites);
  const military = useReferenceData("/data/military-sites.json", layers.icbmBases || layers.militaryBases, decodeSites);
  const callback = useRef(onSelect);
  callback.current = onSelect;
  useEffect(() => {
    if (!viewer || viewer.isDestroyed()) return;
    const billboards = viewer.scene.primitives.add(new Cesium.BillboardCollection({ scene: viewer.scene })) as Cesium.BillboardCollection;
    const labels = viewer.scene.primitives.add(new Cesium.LabelCollection({ scene: viewer.scene })) as Cesium.LabelCollection;
    const icons = new Map<StrategicKind, HTMLCanvasElement>();
    const sites = new Map<object, StrategicSite>();
    for (const site of [...(nuclear.data ?? []), ...(military.data ?? [])]) {
      if (!layers[site.kind]) continue;
      if (!icons.has(site.kind)) icons.set(site.kind, createStrategicIcon(site.kind));
      const position = Cesium.Cartesian3.fromDegrees(site.longitude, site.latitude);
      const id = { odinKind: "operational", referenceSite: site.id };
      const billboard = billboards.add({ position, id, image: icons.get(site.kind), width: 30, height: 30,
        disableDepthTestDistance: 3_000_000,
        eyeOffset: new Cesium.Cartesian3(0, 0, -30),
        scaleByDistance: new Cesium.NearFarScalar(500_000, 1.1, 20_000_000, 0.65) });
      sites.set(billboard, site);
      const label = labels.add({ position, id, text: site.name, font: "12px sans-serif",
        fillColor: Cesium.Color.fromCssColorString(COLORS[site.kind]),
        disableDepthTestDistance: 3_000_000,
        outlineColor: Cesium.Color.BLACK, outlineWidth: 3, style: Cesium.LabelStyle.FILL_AND_OUTLINE,
        pixelOffset: new Cesium.Cartesian2(0, -26),
        distanceDisplayCondition: new Cesium.DistanceDisplayCondition(0, site.kind === "nuclearPlants" ? 900_000 : 3_000_000) });
      sites.set(label, site);
    }
    const handler = new Cesium.ScreenSpaceEventHandler(viewer.canvas);
    handler.setInputAction((event: Cesium.ScreenSpaceEventHandler.PositionedEvent) => {
      const hit: unknown = viewer.scene.pick(event.position);
      if (typeof hit !== "object" || hit === null || !("primitive" in hit)) return;
      const site = sites.get(hit.primitive as object);
      if (site) callback.current(site);
    }, Cesium.ScreenSpaceEventType.LEFT_CLICK);
    viewer.scene.requestRender();
    return () => {
      handler.destroy();
      if (!viewer.isDestroyed()) { viewer.scene.primitives.remove(billboards); viewer.scene.primitives.remove(labels); }
    };
  }, [viewer, nuclear.data, military.data, layers.nuclearPlants, layers.icbmBases, layers.militaryBases]);
  const failures = [layers.nuclearPlants && nuclear.error ? nuclear : null,
    (layers.icbmBases || layers.militaryBases) && military.error ? military : null].filter((item) => item !== null);
  if (!failures.length) return null;
  return <div role="alert" style={{ position: "absolute", bottom: 180, left: 18, zIndex: 20, background: "var(--obsidian)", padding: 12 }}>
    Reference layer unavailable. <button onClick={() => failures.forEach((item) => item.retry())}>Retry reference data</button>
  </div>;
}
