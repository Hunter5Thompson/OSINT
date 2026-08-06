import RBush from "rbush";

import type {
  BoundaryAsset,
  BoundaryGeometryV1,
  BoundaryPackV1,
  LinearRing,
  Position2D,
} from "./catalog";
import {
  parseScopeKeyCandidate,
  type RenderAssetDescriptor,
  type ResolvedPresentationInput,
  type ScopeKey,
} from "./contracts";

const EARTH_RADIUS_METERS = 6_371_008.8;
const COORDINATE_EPSILON = 1e-12;
const DISTANCE_EPSILON_METERS = 1e-6;

export type PointContainment =
  | "inside"
  | "outside"
  | "boundary-uncertain";

export class SpatialGeometryError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "SpatialGeometryError";
  }
}

function assertQueryCoordinate(longitude: number, latitude: number): void {
  if (!Number.isFinite(longitude) || longitude < -180 || longitude > 180) {
    throw new RangeError("Query longitude must be finite and within [-180, 180].");
  }
  if (!Number.isFinite(latitude) || latitude < -90 || latitude > 90) {
    throw new RangeError("Query latitude must be finite and within [-90, 90].");
  }
}

function assertErrorBand(maxErrorMeters: number): void {
  if (!Number.isFinite(maxErrorMeters) || maxErrorMeters < 0) {
    throw new RangeError("Boundary error must be a finite non-negative distance.");
  }
}

export function unwrapQueryAndRing(
  queryLongitude: number,
  ring: LinearRing,
): readonly [number, readonly Position2D[]] {
  if (!Number.isFinite(queryLongitude) || queryLongitude < -180 || queryLongitude > 180) {
    throw new RangeError("Query longitude must be finite and within [-180, 180].");
  }
  if (ring.length === 0) throw new SpatialGeometryError("A ring must not be empty.");

  const first = ring[0];
  if (first === undefined) throw new SpatialGeometryError("A ring must not be empty.");
  const unwrapped: Position2D[] = [[first[0], first[1]]];
  for (let index = 1; index < ring.length; index += 1) {
    const position = ring[index];
    const previous = unwrapped.at(-1);
    if (position === undefined || previous === undefined) {
      throw new SpatialGeometryError("A ring contains an invalid position.");
    }
    let longitude = position[0];
    while (longitude - previous[0] > 180) longitude -= 360;
    while (longitude - previous[0] < -180) longitude += 360;
    unwrapped.push([longitude, position[1]]);
  }

  const meanPositions = unwrapped.length > 1 ? unwrapped.slice(0, -1) : unwrapped;
  const meanLongitude = meanPositions.reduce(
    (total, [longitude]) => total + longitude,
    0,
  ) / meanPositions.length;
  const alignedQuery = queryLongitude
    + Math.round((meanLongitude - queryLongitude) / 360) * 360;
  return [alignedQuery, unwrapped];
}

function pointOnSegment(
  longitude: number,
  latitude: number,
  left: Position2D,
  right: Position2D,
): boolean {
  const cross = (longitude - left[0]) * (right[1] - left[1])
    - (latitude - left[1]) * (right[0] - left[0]);
  if (Math.abs(cross) > COORDINATE_EPSILON) return false;
  return longitude >= Math.min(left[0], right[0]) - COORDINATE_EPSILON
    && longitude <= Math.max(left[0], right[0]) + COORDINATE_EPSILON
    && latitude >= Math.min(left[1], right[1]) - COORDINATE_EPSILON
    && latitude <= Math.max(left[1], right[1]) + COORDINATE_EPSILON;
}

function ringContains(
  longitude: number,
  latitude: number,
  ring: readonly Position2D[],
): boolean {
  let inside = false;
  for (let index = 0; index < ring.length - 1; index += 1) {
    const left = ring[index];
    const right = ring[index + 1];
    if (left === undefined || right === undefined) continue;
    if (pointOnSegment(longitude, latitude, left, right)) return true;
    const crosses = (left[1] > latitude) !== (right[1] > latitude);
    if (!crosses) continue;
    const crossingLongitude = left[0]
      + (latitude - left[1]) * (right[0] - left[0])
        / (right[1] - left[1]);
    if (longitude < crossingLongitude) inside = !inside;
  }
  return inside;
}

function containsPoint(
  geometry: BoundaryGeometryV1,
  longitude: number,
  latitude: number,
): boolean {
  for (const polygon of geometry.polygons) {
    const outer = polygon[0];
    if (outer === undefined) continue;
    const [outerQuery, unwrappedOuter] = unwrapQueryAndRing(longitude, outer);
    if (!ringContains(outerQuery, latitude, unwrappedOuter)) continue;

    let insideHole = false;
    for (const hole of polygon.slice(1)) {
      const [holeQuery, unwrappedHole] = unwrapQueryAndRing(longitude, hole);
      if (ringContains(holeQuery, latitude, unwrappedHole)) {
        insideHole = true;
        break;
      }
    }
    if (!insideHole) return true;
  }
  return false;
}

function pointSegmentDistanceMeters(
  queryLongitude: number,
  queryLatitude: number,
  left: Position2D,
  right: Position2D,
): number {
  const latitudeRadians = queryLatitude * Math.PI / 180;
  const project = (position: Position2D): readonly [number, number] => [
    (position[0] - queryLongitude) * Math.PI / 180
      * Math.cos(latitudeRadians) * EARTH_RADIUS_METERS,
    (position[1] - queryLatitude) * Math.PI / 180 * EARTH_RADIUS_METERS,
  ];
  const [leftX, leftY] = project(left);
  const [rightX, rightY] = project(right);
  const deltaX = rightX - leftX;
  const deltaY = rightY - leftY;
  const lengthSquared = deltaX * deltaX + deltaY * deltaY;
  if (lengthSquared === 0) return Math.hypot(leftX, leftY);
  const fraction = Math.max(
    0,
    Math.min(1, -(leftX * deltaX + leftY * deltaY) / lengthSquared),
  );
  return Math.hypot(leftX + fraction * deltaX, leftY + fraction * deltaY);
}

function distanceToBoundaryMeters(
  geometry: BoundaryGeometryV1,
  longitude: number,
  latitude: number,
): number {
  let minimum = Number.POSITIVE_INFINITY;
  for (const polygon of geometry.polygons) {
    for (const ring of polygon) {
      const [query, unwrapped] = unwrapQueryAndRing(longitude, ring);
      for (let index = 0; index < unwrapped.length - 1; index += 1) {
        const left = unwrapped[index];
        const right = unwrapped[index + 1];
        if (left === undefined || right === undefined) continue;
        minimum = Math.min(
          minimum,
          pointSegmentDistanceMeters(query, latitude, left, right),
        );
      }
    }
  }
  return minimum;
}

export function classifyPointInGeometry(
  geometry: BoundaryGeometryV1,
  longitude: number,
  latitude: number,
  maxErrorMeters = 0,
): PointContainment {
  assertQueryCoordinate(longitude, latitude);
  assertErrorBand(maxErrorMeters);
  if (
    distanceToBoundaryMeters(geometry, longitude, latitude)
      <= maxErrorMeters + DISTANCE_EPSILON_METERS
  ) {
    return "boundary-uncertain";
  }
  return containsPoint(geometry, longitude, latitude) ? "inside" : "outside";
}

interface LongitudeSpan {
  readonly west: number;
  readonly east: number;
}

interface BoundaryIndexNode {
  readonly minX: number;
  readonly minY: number;
  readonly maxX: number;
  readonly maxY: number;
  readonly featureIndex: number;
}

export interface BoundaryGeometryIndexFeature<T> {
  readonly value: T;
  readonly geometry: BoundaryGeometryV1;
}

export interface BoundaryGeometryIndexHit<T> {
  readonly value: T;
  readonly containment: Exclude<PointContainment, "outside">;
}

function normalizedAngle(longitude: number): number {
  const angle = (longitude + 180) % 360;
  return angle < 0 ? angle + 360 : angle;
}

function cleanLongitude(longitude: number): number {
  if (Math.abs(longitude + 180) <= COORDINATE_EPSILON) return -180;
  if (Math.abs(longitude - 180) <= COORDINATE_EPSILON) return 180;
  if (Math.abs(longitude) <= COORDINATE_EPSILON) return 0;
  return longitude;
}

function minimalLongitudeSpans(longitudes: readonly number[]): readonly LongitudeSpan[] {
  const angles = [...new Set(longitudes.map(normalizedAngle))].sort((a, b) => a - b);
  if (angles.length === 0) throw new SpatialGeometryError("Geometry has no positions.");
  if (angles.length === 1) {
    const longitude = cleanLongitude((angles[0] ?? 0) - 180);
    return [{ west: longitude, east: longitude }];
  }

  let largestGap = -1;
  let largestGapIndex = -1;
  for (let index = 0; index < angles.length; index += 1) {
    const current = angles[index];
    const next = index === angles.length - 1
      ? (angles[0] ?? 0) + 360
      : angles[index + 1];
    if (current === undefined || next === undefined) continue;
    const gap = next - current;
    if (gap > largestGap) {
      largestGap = gap;
      largestGapIndex = index;
    }
  }

  const startIndex = (largestGapIndex + 1) % angles.length;
  const start = angles[startIndex] ?? 0;
  let end = angles[largestGapIndex] ?? 0;
  if (end < start || largestGapIndex === angles.length - 1) end += 360;
  const west = cleanLongitude(start - 180);
  const eastUnwrapped = end - 180;
  if (eastUnwrapped <= 180 + COORDINATE_EPSILON) {
    return [{ west, east: cleanLongitude(Math.min(eastUnwrapped, 180)) }];
  }
  return [
    { west: -180, east: cleanLongitude(eastUnwrapped - 360) },
    { west, east: 180 },
  ];
}

function polygonIndexNodes(
  geometry: BoundaryGeometryV1,
  featureIndex: number,
): BoundaryIndexNode[] {
  const nodes: BoundaryIndexNode[] = [];
  for (const polygon of geometry.polygons) {
    const positions = polygon.flatMap((ring) => ring.slice(0, -1));
    if (positions.length === 0) continue;
    const south = Math.min(...positions.map((position) => position[1]));
    const north = Math.max(...positions.map((position) => position[1]));
    for (const span of minimalLongitudeSpans(
      positions.map((position) => position[0]),
    )) {
      nodes.push({
        minX: span.west,
        minY: south,
        maxX: span.east,
        maxY: north,
        featureIndex,
      });
    }
  }
  return nodes;
}

function queryLongitudeSpans(
  longitude: number,
  longitudeDelta: number,
): readonly LongitudeSpan[] {
  if (longitudeDelta >= 180) return [{ west: -180, east: 180 }];
  const west = longitude - longitudeDelta;
  const east = longitude + longitudeDelta;
  if (west < -180) {
    return [
      { west: -180, east },
      { west: west + 360, east: 180 },
    ];
  }
  if (east > 180) {
    return [
      { west: -180, east: east - 360 },
      { west, east: 180 },
    ];
  }
  return [{ west, east }];
}

export class BoundaryGeometryIndex<T> {
  readonly indexedSpanCount: number;
  private readonly tree = new RBush<BoundaryIndexNode>();

  constructor(private readonly features: readonly BoundaryGeometryIndexFeature<T>[]) {
    const nodes = features.flatMap((feature, index) =>
      polygonIndexNodes(feature.geometry, index),
    );
    this.indexedSpanCount = nodes.length;
    this.tree.load(nodes);
  }

  query(
    longitude: number,
    latitude: number,
    maxErrorMeters = 0,
  ): readonly BoundaryGeometryIndexHit<T>[] {
    assertQueryCoordinate(longitude, latitude);
    assertErrorBand(maxErrorMeters);
    const latitudeDelta = maxErrorMeters / EARTH_RADIUS_METERS * 180 / Math.PI;
    const longitudeDelta = Math.min(
      180,
      latitudeDelta / Math.max(Math.abs(Math.cos(latitude * Math.PI / 180)), 1e-6),
    );
    const candidateIndexes = new Set<number>();
    for (const span of queryLongitudeSpans(longitude, longitudeDelta)) {
      for (const node of this.tree.search({
        minX: span.west,
        minY: Math.max(-90, latitude - latitudeDelta),
        maxX: span.east,
        maxY: Math.min(90, latitude + latitudeDelta),
      })) {
        candidateIndexes.add(node.featureIndex);
      }
    }

    const hits: BoundaryGeometryIndexHit<T>[] = [];
    for (const featureIndex of [...candidateIndexes].sort((left, right) => left - right)) {
      const feature = this.features[featureIndex];
      if (feature === undefined) continue;
      const containment = classifyPointInGeometry(
        feature.geometry,
        longitude,
        latitude,
        maxErrorMeters,
      );
      if (containment !== "outside") {
        hits.push({ value: feature.value, containment });
      }
    }
    return hits;
  }
}

export function createBoundaryGeometryIndex<T>(
  features: readonly BoundaryGeometryIndexFeature<T>[],
): BoundaryGeometryIndex<T> {
  return new BoundaryGeometryIndex(features);
}

export interface SpatialChildGeometry {
  readonly scopeKey: ScopeKey;
  readonly label: string;
}

export function selectPreferredChildDescriptor(
  presentation: ResolvedPresentationInput,
): RenderAssetDescriptor {
  const descriptor = presentation.childrenLods[presentation.preferredLod];
  if (descriptor === undefined) {
    throw new SpatialGeometryError(
      "The preferred child descriptor is unavailable for this scope.",
    );
  }
  return descriptor;
}

function asBoundaryPack(asset: BoundaryAsset): BoundaryPackV1 {
  if (!("features" in asset)) {
    throw new SpatialGeometryError("The preferred child asset is not a boundary pack.");
  }
  return asset;
}

export function createSpatialChildGeometryIndex(
  presentation: ResolvedPresentationInput,
  descriptor: RenderAssetDescriptor,
  asset: BoundaryAsset,
): BoundaryGeometryIndex<SpatialChildGeometry> {
  const preferred = selectPreferredChildDescriptor(presentation);
  if (
    descriptor.assetId !== preferred.assetId
    || descriptor.lod !== preferred.lod
    || descriptor.role !== "render"
  ) {
    throw new SpatialGeometryError(
      "Only the preferred child descriptor may create a pick index.",
    );
  }
  const pack = asBoundaryPack(asset);
  if (pack.parentScopeKey !== presentation.scopeKey) {
    throw new SpatialGeometryError("Child pack parent does not match the presented scope.");
  }

  const features: BoundaryGeometryIndexFeature<SpatialChildGeometry>[] = [];
  for (const feature of pack.features) {
    if (feature.kind !== "scope") continue;
    let scopeKey: ScopeKey;
    try {
      scopeKey = parseScopeKeyCandidate(feature.scopeKey);
    } catch (error: unknown) {
      throw new SpatialGeometryError(
        `Child pack contains an invalid scope key: ${String(error)}`,
      );
    }
    if (scopeKey !== feature.scopeKey) {
      throw new SpatialGeometryError("Child pack scope keys must already be canonical.");
    }
    features.push({
      value: { scopeKey, label: feature.label },
      geometry: feature.geometry,
    });
  }
  return createBoundaryGeometryIndex(features);
}
