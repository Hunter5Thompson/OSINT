import * as Cesium from "cesium";

import type {
  BoundaryAsset,
  BoundaryGeometryV1,
  BoundaryPackFeatureV1,
  BoundaryPackV1,
  Position2D,
} from "../catalog";
import type { ScopeKey } from "../contracts";
import { spatialScopeColor } from "./hlidskjalfCesiumPalette";
import type { SpatialChildPickId } from "./resolveWorldviewPick";

const MAX_CHUNK_VERTICES = 8_000;
const MAX_CHUNK_MILLISECONDS = 8;

export interface ScopePrimitiveHandle {
  show: boolean;
  readonly ready: boolean;
}

export interface ScopePrimitiveBuild {
  readonly renderPrimitives: readonly ScopePrimitiveHandle[];
  readonly pickPrimitives: readonly ScopePrimitiveHandle[];
  readonly cameraPositions: readonly unknown[];
}

export interface ScopeBuildScheduler {
  now(): number;
  nextFrame(): Promise<void>;
}

export interface ScopeBuildChunk {
  readonly vertices: number;
  readonly durationMs: number;
}

interface ConvertedGeometry<TPosition> {
  readonly polygons: readonly (readonly (readonly TPosition[])[])[];
}

interface ConvertedFeature<TPosition> {
  readonly kind: "active" | BoundaryPackFeatureV1["kind"];
  readonly scopeKey: ScopeKey | null;
  readonly geometry: ConvertedGeometry<TPosition>;
}

export interface ScopeGeometryBuild<TPosition> {
  readonly activeFeatures: readonly ConvertedFeature<TPosition>[];
  readonly childFeatures: readonly ConvertedFeature<TPosition>[];
  readonly cameraPositions: readonly TPosition[];
}

export interface BuildScopeGeometryOptions<TPosition> {
  readonly activeAsset: BoundaryAsset | null;
  readonly childAsset: BoundaryPackV1 | null;
  readonly stateRevision: number;
  readonly signal: AbortSignal;
  readonly convertPosition: (position: Position2D) => TPosition;
  readonly scheduler?: ScopeBuildScheduler;
  readonly onChunk?: (chunk: ScopeBuildChunk) => void;
}

function abortError(): DOMException {
  return new DOMException("The operation was aborted.", "AbortError");
}

function assertNotAborted(signal: AbortSignal): void {
  if (signal.aborted) throw abortError();
}

const browserScheduler: ScopeBuildScheduler = {
  now: () => performance.now(),
  nextFrame: () => new Promise<void>((resolve) => {
    requestAnimationFrame(() => resolve());
  }),
};

function geometryFeatures(
  asset: BoundaryAsset | null,
): readonly {
  readonly kind: "active" | BoundaryPackFeatureV1["kind"];
  readonly scopeKey: ScopeKey | null;
  readonly geometry: BoundaryGeometryV1;
}[] {
  if (asset === null) return [];
  if ("geometryType" in asset) {
    return [{ kind: "active", scopeKey: null, geometry: asset }];
  }
  return asset.features.map((feature) => ({
    kind: feature.kind,
    scopeKey: feature.kind === "scope" ? feature.scopeKey : null,
    geometry: feature.geometry,
  }));
}

export async function buildScopeGeometry<TPosition>(
  options: BuildScopeGeometryOptions<TPosition>,
): Promise<ScopeGeometryBuild<TPosition>> {
  const scheduler = options.scheduler ?? browserScheduler;
  let chunkStartedAt = scheduler.now();
  let chunkVertices = 0;

  const convertRing = async (
    ring: readonly Position2D[],
  ): Promise<readonly TPosition[]> => {
    const positions: TPosition[] = [];
    for (const position of ring) {
      assertNotAborted(options.signal);
      positions.push(options.convertPosition(position));
      chunkVertices += 1;
      const durationMs = scheduler.now() - chunkStartedAt;
      if (
        chunkVertices >= MAX_CHUNK_VERTICES
        || durationMs >= MAX_CHUNK_MILLISECONDS
      ) {
        options.onChunk?.({ vertices: chunkVertices, durationMs });
        chunkVertices = 0;
        await scheduler.nextFrame();
        assertNotAborted(options.signal);
        chunkStartedAt = scheduler.now();
      }
    }
    return positions;
  };

  const convertFeature = async (
    feature: ReturnType<typeof geometryFeatures>[number],
  ): Promise<ConvertedFeature<TPosition>> => {
    const polygons: Array<Array<readonly TPosition[]>> = [];
    for (const polygon of feature.geometry.polygons) {
      const rings: Array<readonly TPosition[]> = [];
      for (const ring of polygon) {
        rings.push(await convertRing(ring));
      }
      polygons.push(rings);
    }
    return {
      kind: feature.kind,
      scopeKey: feature.scopeKey,
      geometry: { polygons },
    };
  };

  const activeFeatures: ConvertedFeature<TPosition>[] = [];
  for (const feature of geometryFeatures(options.activeAsset)) {
    activeFeatures.push(await convertFeature(feature));
  }
  const childFeatures: ConvertedFeature<TPosition>[] = [];
  for (const feature of geometryFeatures(options.childAsset)) {
    childFeatures.push(await convertFeature(feature));
  }
  if (chunkVertices > 0) {
    options.onChunk?.({
      vertices: chunkVertices,
      durationMs: scheduler.now() - chunkStartedAt,
    });
  }
  assertNotAborted(options.signal);

  const cameraSource = activeFeatures.length > 0 ? activeFeatures : childFeatures;
  const cameraPositions = cameraSource.flatMap((feature) =>
    feature.geometry.polygons.flatMap((polygon) => polygon.flatMap((ring) => ring)),
  );
  return { activeFeatures, childFeatures, cameraPositions };
}

type CesiumScopePrimitive = Cesium.GroundPrimitive | Cesium.GroundPolylinePrimitive;

export class CesiumScopePrimitiveHandle implements ScopePrimitiveHandle {
  constructor(
    readonly primitive: CesiumScopePrimitive,
  ) {
    this.primitive.show = false;
  }

  get show(): boolean {
    return this.primitive.show;
  }

  set show(value: boolean) {
    this.primitive.show = value;
  }

  get ready(): boolean {
    return this.primitive.ready;
  }
}

function withoutClosingDuplicate(
  positions: readonly Cesium.Cartesian3[],
): readonly Cesium.Cartesian3[] {
  if (
    positions.length > 1
    && Cesium.Cartesian3.equals(positions[0], positions.at(-1))
  ) {
    return positions.slice(0, -1);
  }
  return positions;
}

function polygonHierarchy(
  polygon: readonly (readonly Cesium.Cartesian3[])[],
): Cesium.PolygonHierarchy | null {
  const outer = polygon[0];
  if (outer === undefined) return null;
  return new Cesium.PolygonHierarchy(
    [...withoutClosingDuplicate(outer)],
    polygon.slice(1).map((hole) =>
      new Cesium.PolygonHierarchy([...withoutClosingDuplicate(hole)]),
    ),
  );
}

function polygonInstances(
  features: readonly ConvertedFeature<Cesium.Cartesian3>[],
  color: Cesium.Color,
  stateRevision: number,
  pickable: boolean,
): Cesium.GeometryInstance[] {
  const instances: Cesium.GeometryInstance[] = [];
  for (const feature of features) {
    if (pickable && (feature.kind !== "scope" || feature.scopeKey === null)) continue;
    for (const polygon of feature.geometry.polygons) {
      const hierarchy = polygonHierarchy(polygon);
      if (hierarchy === null) continue;
      const id: SpatialChildPickId | undefined = pickable && feature.scopeKey !== null
        ? Object.freeze({
            odinKind: "spatial-child",
            scopeKey: feature.scopeKey,
            stateRevision,
          })
        : undefined;
      instances.push(new Cesium.GeometryInstance({
        geometry: new Cesium.PolygonGeometry({
          polygonHierarchy: hierarchy,
          vertexFormat: Cesium.PerInstanceColorAppearance.VERTEX_FORMAT,
        }),
        ...(id === undefined ? {} : { id }),
        attributes: {
          color: Cesium.ColorGeometryInstanceAttribute.fromColor(color),
        },
      }));
    }
  }
  return instances;
}

function outlineInstances(
  features: readonly ConvertedFeature<Cesium.Cartesian3>[],
): Cesium.GeometryInstance[] {
  const instances: Cesium.GeometryInstance[] = [];
  for (const feature of features) {
    for (const polygon of feature.geometry.polygons) {
      for (const ring of polygon) {
        if (ring.length < 2) continue;
        instances.push(new Cesium.GeometryInstance({
          geometry: new Cesium.GroundPolylineGeometry({
            positions: [...ring],
            width: 1.5,
          }),
          attributes: {
            color: Cesium.ColorGeometryInstanceAttribute.fromColor(
              spatialScopeColor.scopeOutline(),
            ),
          },
        }));
      }
    }
  }
  return instances;
}

function groundFill(
  instances: readonly Cesium.GeometryInstance[],
  allowPicking: boolean,
): ScopePrimitiveHandle | null {
  if (instances.length === 0) return null;
  return new CesiumScopePrimitiveHandle(new Cesium.GroundPrimitive({
    geometryInstances: [...instances],
    appearance: new Cesium.PerInstanceColorAppearance({
      flat: true,
      translucent: true,
      closed: false,
    }),
    allowPicking,
    asynchronous: true,
    classificationType: Cesium.ClassificationType.BOTH,
    releaseGeometryInstances: true,
  }));
}

function groundOutlines(
  instances: readonly Cesium.GeometryInstance[],
): ScopePrimitiveHandle | null {
  if (instances.length === 0) return null;
  return new CesiumScopePrimitiveHandle(new Cesium.GroundPolylinePrimitive({
    geometryInstances: [...instances],
    appearance: new Cesium.PolylineColorAppearance({ translucent: true }),
    asynchronous: true,
    releaseGeometryInstances: true,
  }));
}

export interface BuildScopePrimitivesOptions {
  readonly activeAsset: BoundaryAsset | null;
  readonly childRenderAsset: BoundaryPackV1 | null;
  readonly childPickAsset: BoundaryPackV1 | null;
  readonly stateRevision: number;
  readonly includePickSurface: boolean;
  readonly signal: AbortSignal;
  readonly scheduler?: ScopeBuildScheduler;
  readonly onChunk?: (chunk: ScopeBuildChunk) => void;
}

function buildCesiumScopeGeometry(
  activeAsset: BoundaryAsset | null,
  childAsset: BoundaryPackV1 | null,
  options: BuildScopePrimitivesOptions,
): Promise<ScopeGeometryBuild<Cesium.Cartesian3>> {
  return buildScopeGeometry({
    activeAsset,
    childAsset,
    stateRevision: options.stateRevision,
    signal: options.signal,
    convertPosition: ([longitude, latitude]) =>
      Cesium.Cartesian3.fromDegrees(longitude, latitude),
    scheduler: options.scheduler,
    onChunk: options.onChunk,
  });
}

export async function buildScopePrimitives(
  options: BuildScopePrimitivesOptions,
): Promise<ScopePrimitiveBuild> {
  const geometryBuild = await buildCesiumScopeGeometry(
    options.activeAsset,
    options.childRenderAsset,
    options,
  );
  assertNotAborted(options.signal);

  const renderPrimitives: ScopePrimitiveHandle[] = [];
  const activeFill = groundFill(
    polygonInstances(
      geometryBuild.activeFeatures,
      spatialScopeColor.activeFill(),
      options.stateRevision,
      false,
    ),
    false,
  );
  if (activeFill !== null) renderPrimitives.push(activeFill);
  const outlines = groundOutlines(outlineInstances([
    ...geometryBuild.activeFeatures,
    ...geometryBuild.childFeatures,
  ]));
  if (outlines !== null) renderPrimitives.push(outlines);

  const pickPrimitives: ScopePrimitiveHandle[] = [];
  if (options.includePickSurface) {
    const pickFeatures = options.childPickAsset === options.childRenderAsset
      ? geometryBuild.childFeatures
      : (await buildCesiumScopeGeometry(
          null,
          options.childPickAsset,
          options,
        )).childFeatures;
    assertNotAborted(options.signal);
    const childFill = groundFill(
      polygonInstances(
        pickFeatures,
        spatialScopeColor.childPickSurface(),
        options.stateRevision,
        true,
      ),
      true,
    );
    if (childFill !== null) pickPrimitives.push(childFill);
  }
  assertNotAborted(options.signal);
  return {
    renderPrimitives,
    pickPrimitives,
    cameraPositions: geometryBuild.cameraPositions,
  };
}
