import { useEffect, useMemo, useRef, useState } from "react";
import * as Cesium from "cesium";
import { useSpatialScope } from "./react";
import { decodeRegions, regionsInScope, useReferenceData, type RegionProfile } from "../components/layers/referenceData";
import "./regional-atlas.css";
import { layoutCapitalLabels } from "./capitalLabels";

export function RegionalAtlas({ viewer, hidden = false }: { viewer: Cesium.Viewer | null; hidden?: boolean }) {
  const scope = useSpatialScope();
  const key = scope.current?.key ?? "world";
  const enabled = key !== "world";
  const { data, error, retry } = useReferenceData("/data/region-profiles.json", enabled, decodeRegions);
  const [previewKey, setPreviewKey] = useState<string | null>(null);
  const [collapsed, setCollapsed] = useState(false);
  const enter = useRef(scope.enter);
  enter.current = scope.enter;
  const available = useMemo(() => new Map(scope.children.map((child) => [child.key as string, child.key])), [scope.children]);
  const regions = useMemo(() => regionsInScope(data ?? [], key), [data, key]);
  const selected = regions.find((region) => region.key === previewKey) ?? (regions.length === 1 ? regions[0] : null);
  const capitals = regions.filter((region) => region.capital);

  useEffect(() => {
    if (!viewer || viewer.isDestroyed() || !enabled) return;
    const points = viewer.scene.primitives.add(new Cesium.PointPrimitiveCollection()) as Cesium.PointPrimitiveCollection;
    const labels = viewer.scene.primitives.add(new Cesium.LabelCollection({ scene: viewer.scene })) as Cesium.LabelCollection;
    const hits = new Map<object, RegionProfile>();
    const placements: { label: Cesium.Label; position: Cesium.Cartesian3; width: number }[] = [];
    for (const region of regions) {
      const capital = region.capital;
      if (!capital) continue;
      const position = Cesium.Cartesian3.fromDegrees(capital.longitude, capital.latitude, 100);
      const id = { odinKind: "operational", regionalCapital: region.key };
      const point = points.add({ position, id, pixelSize: 9, color: Cesium.Color.fromCssColorString("#e8c66a"),
        outlineColor: Cesium.Color.fromCssColorString("#18252e"), outlineWidth: 3,
        disableDepthTestDistance: 3_000_000,
        distanceDisplayCondition: new Cesium.DistanceDisplayCondition(0, 9_000_000) });
      const label = labels.add({ position, id, text: `${capital.name}\n${region.name}`,
        font: "13px sans-serif", fillColor: Cesium.Color.fromCssColorString("#f2e6c7"),
        outlineColor: Cesium.Color.fromCssColorString("#101820"), outlineWidth: 3,
        style: Cesium.LabelStyle.FILL_AND_OUTLINE, showBackground: true,
        disableDepthTestDistance: 3_000_000,
        backgroundColor: Cesium.Color.fromCssColorString("#111d26").withAlpha(0.82),
        backgroundPadding: new Cesium.Cartesian2(8, 5), pixelOffset: new Cesium.Cartesian2(14, -6),
        horizontalOrigin: Cesium.HorizontalOrigin.LEFT,
        verticalOrigin: Cesium.VerticalOrigin.TOP,
        distanceDisplayCondition: new Cesium.DistanceDisplayCondition(0, 5_000_000) });
      placements.push({ label, position, width: Math.max(capital.name.length, region.name.length) * 7 + 16 });
      hits.set(point, region); hits.set(label, region);
    }
    const layout = () => {
      if (viewer.isDestroyed()) return;
      const projected = placements.map((item) => ({ ...item,
        screen: Cesium.SceneTransforms.worldToWindowCoordinates(viewer.scene, item.position) }))
        .filter((item) => item.screen !== undefined && item.screen.x >= 0 && item.screen.x <= viewer.canvas.clientWidth
          && item.screen.y >= 0 && item.screen.y <= viewer.canvas.clientHeight);
      const offsets = layoutCapitalLabels(projected.map((item) => ({ x: item.screen!.x, y: item.screen!.y, width: item.width })), viewer.canvas.clientWidth, viewer.canvas.clientHeight);
      projected.forEach((item, index) => { const offset = offsets[index]; if (offset) item.label.pixelOffset = new Cesium.Cartesian2(offset.x, offset.y); });
      viewer.scene.requestRender();
    };
    const removeMove = viewer.camera.moveEnd.addEventListener(layout);
    const removeInitial = viewer.scene.postRender.addEventListener(() => { removeInitial(); layout(); });
    const handler = new Cesium.ScreenSpaceEventHandler(viewer.canvas);
    handler.setInputAction((event: Cesium.ScreenSpaceEventHandler.PositionedEvent) => {
      const hit: unknown = viewer.scene.pick(event.position);
      if (typeof hit !== "object" || hit === null || !("primitive" in hit)) return;
      const region = hits.get(hit.primitive as object);
      if (region) setPreviewKey(region.key);
    }, Cesium.ScreenSpaceEventType.LEFT_CLICK);
    viewer.scene.requestRender();
    return () => {
      handler.destroy();
      removeMove(); removeInitial();
      if (!viewer.isDestroyed()) { viewer.scene.primitives.remove(points); viewer.scene.primitives.remove(labels); }
    };
  }, [viewer, regions, enabled]);

  if (!enabled) return null;
  return <aside hidden={hidden} className={`regional-atlas${collapsed ? " regional-atlas--collapsed" : ""}`} aria-label="Regional atlas">
    <div className="regional-atlas__eyebrow">Territory atlas · reference</div>
    <div className="regional-atlas__heading"><h2>{scope.current?.shortLabel}</h2>
      <button aria-label={collapsed ? "Expand regional atlas" : "Collapse regional atlas"} onClick={() => setCollapsed(!collapsed)}>{collapsed ? "+" : "−"}</button>
    </div>
    {!collapsed && <>
      {error ? <p role="alert">Regional data unavailable. <button onClick={retry}>Retry regional data</button></p>
        : data === null ? <p role="status">Loading regional profiles…</p>
        : <>
          <div className="regional-atlas__stats"><span><strong>{regions.length}</strong> regions in reference</span><span><strong>{capitals.length}</strong> capitals mapped</span></div>
          {selected ? <div className="regional-atlas__profile">
            <div className="regional-atlas__eyebrow">{selected.division} · {selected.country}</div>
            <h3>{selected.name}</h3>
            <dl><dt>Regional capital</dt><dd>{selected.capital?.name ?? "Not verified in reference"}</dd>
              {selected.capital?.timezone && <><dt>Capital timezone</dt><dd>{selected.capital.timezone}</dd></>}
              {(selected.capital?.population ?? 0) > 0 && <><dt>Capital population · dataset estimate</dt><dd>{selected.capital!.population!.toLocaleString()}</dd></>}
            </dl>
            {available.has(selected.key) && <button className="regional-atlas__explore" onClick={() => { const target = available.get(selected.key); if (target) void enter.current(target, "child-click"); }}>Explore {selected.name} ↗</button>}
          </div> : <p className="regional-atlas__hint">Select a capital or region to open its profile.</p>}
          {regions.length > 1 && <div className="regional-atlas__list">{regions.map((region) => <button key={region.key}
            aria-pressed={selected?.key === region.key} onClick={() => setPreviewKey(region.key)}>
            <span>{region.name}</span><small>{region.capital?.name ?? "Capital unverified"}</small>
          </button>)}</div>}
          {regions.length === 0 && <p>Regional detail is not available in this reference snapshot.</p>}
          {!scope.current?.childrenAvailable && scope.current?.kind === "country" && <p className="regional-atlas__hint">Capital reference available; province boundaries not yet published for this country.</p>}
          <footer><a href="https://www.naturalearthdata.com/downloads/10m-cultural-vectors/" target="_blank" rel="noopener noreferrer">Natural Earth 5.1.2 ↗</a><br />Reference geography, not live administration or current population.</footer>
        </>}
    </>}
  </aside>;
}
