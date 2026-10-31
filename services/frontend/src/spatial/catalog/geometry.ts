// Internal catalog implementation; consumers use ../catalog.ts.
import {
  type AssetDescriptor,
  freezeSpatialValue,
} from "../contracts";
import {
  type GeometryCounts,
  type Position2D,
  assetLimitError,
  parseFiniteNumber,
  type BoundaryGeometryV1,
  asRecord,
  assertExactKeys,
  type PolygonCoordinates,
  type LinearRing,
  MAX_RING_VERTICES,
  MAX_ASSET_RINGS,
  parseString,
  type DecodedAsset,
  geometryError,
  type BoundaryAsset,
  MAX_ASSET_FEATURES,
  type BoundaryPackFeatureV1,
  parseCanonicalScopeKey,
  MAX_ASSET_HEAP_BYTES,
} from "./core";

function emptyGeometryCounts(featureCount: number): GeometryCounts {
  return {
    featureCount,
    polygonCount: 0,
    ringCount: 0,
    vertexCount: 0,
    maxRingVertices: 0,
  };
}

function parsePosition(value: unknown, context: string): Position2D {
  if (!Array.isArray(value) || value.length !== 2) {
    throw assetLimitError(`${context} must be a longitude/latitude pair.`, null);
  }
  const longitude = parseFiniteNumber(value[0], `${context}[0]`);
  const latitude = parseFiniteNumber(value[1], `${context}[1]`);
  if (longitude < -180 || longitude > 180 || latitude < -90 || latitude > 90) {
    throw assetLimitError(`${context} is outside WGS84 bounds.`, null);
  }
  return [longitude, latitude];
}

function decodeGeometry(
  value: unknown,
  context: string,
  counts: GeometryCounts,
): BoundaryGeometryV1 {
  const record = asRecord(value, context);
  assertExactKeys(record, context, ["schema_version", "geometry_type", "polygons"]);
  if (record.schema_version !== 1 || record.geometry_type !== "MultiPolygon") {
    throw assetLimitError(`${context} has an unsupported geometry schema.`, null);
  }
  if (!Array.isArray(record.polygons) || record.polygons.length === 0) {
    throw assetLimitError(`${context}.polygons must not be empty.`, null);
  }
  const polygons: PolygonCoordinates[] = [];
  for (const [polygonIndex, polygonValue] of record.polygons.entries()) {
    if (!Array.isArray(polygonValue) || polygonValue.length === 0) {
      throw assetLimitError(`${context}.polygons[${polygonIndex}] must contain a ring.`, null);
    }
    counts.polygonCount += 1;
    const polygon: LinearRing[] = [];
    for (const [ringIndex, ringValue] of polygonValue.entries()) {
      if (
        !Array.isArray(ringValue) ||
        ringValue.length < 4 ||
        ringValue.length > MAX_RING_VERTICES
      ) {
        throw assetLimitError(`${context} ring size is outside the contract budget.`, null);
      }
      counts.ringCount += 1;
      counts.vertexCount += ringValue.length;
      counts.maxRingVertices = Math.max(counts.maxRingVertices, ringValue.length);
      if (counts.ringCount > MAX_ASSET_RINGS) {
        throw assetLimitError("Asset exceeds the ring budget.", null);
      }
      const ring = ringValue.map((position, positionIndex) => parsePosition(
        position,
        `${context}.polygons[${polygonIndex}][${ringIndex}][${positionIndex}]`,
      ));
      const first = ring[0];
      const last = ring.at(-1);
      if (
        first === undefined ||
        last === undefined ||
        first[0] !== last[0] ||
        first[1] !== last[1]
      ) {
        throw assetLimitError(`${context} ring is not closed.`, null);
      }
      polygon.push(ring);
    }
    polygons.push(polygon);
  }
  return {
    schemaVersion: 1,
    geometryType: "MultiPolygon",
    polygons,
  };
}

function parseUnicodeLabel(value: unknown, context: string): string {
  const label = parseString(value, context, 240);
  if ([...label].length > 120) {
    throw assetLimitError(`${context} exceeds 120 Unicode code points.`, null);
  }
  return label;
}

export function decodeBoundaryAsset(bytes: Uint8Array, descriptor: AssetDescriptor): DecodedAsset {
  let value: unknown;
  try {
    const text = new TextDecoder("utf-8", { fatal: true }).decode(bytes);
    value = JSON.parse(text) as unknown;
  } catch {
    throw geometryError("Spatial asset is not valid UTF-8 JSON.", descriptor.assetId);
  }

  let asset: BoundaryAsset;
  let counts: GeometryCounts;
  if (descriptor.mediaType === "application/vnd.odin.boundary+json;v=1") {
    counts = emptyGeometryCounts(0);
    asset = decodeGeometry(value, "boundary", counts);
    if (descriptor.featureCount !== undefined) {
      throw geometryError("Boundary descriptor must not declare featureCount.", descriptor.assetId);
    }
  } else if (descriptor.mediaType === "application/vnd.odin.boundary-pack+json;v=1") {
    const record = asRecord(value, "boundaryPack");
    assertExactKeys(record, "boundaryPack", ["schema_version", "parent_scope_key", "features"]);
    if (record.schema_version !== 1 || !Array.isArray(record.features)) {
      throw assetLimitError("Boundary pack schema is invalid.", descriptor.assetId);
    }
    if (record.features.length < 1 || record.features.length > MAX_ASSET_FEATURES) {
      throw assetLimitError("Boundary pack feature count is outside the budget.", descriptor.assetId);
    }
    counts = emptyGeometryCounts(record.features.length);
    const identities = new Set<string>();
    const features: BoundaryPackFeatureV1[] = record.features.map((featureValue, index) => {
      const feature = asRecord(featureValue, `boundaryPack.features[${index}]`);
      if (feature.kind === "scope") {
        assertExactKeys(feature, `boundaryPack.features[${index}]`, [
          "kind",
          "scope_key",
          "label",
          "geometry",
        ]);
        const scopeKey = parseCanonicalScopeKey(
          feature.scope_key,
          `boundaryPack.features[${index}].scope_key`,
        );
        const identity = `scope\u0000${scopeKey}`;
        if (identities.has(identity)) throw assetLimitError("Duplicate pack feature.", scopeKey);
        identities.add(identity);
        return {
          kind: "scope",
          scopeKey,
          label: parseUnicodeLabel(feature.label, `boundaryPack.features[${index}].label`),
          geometry: decodeGeometry(
            feature.geometry,
            `boundaryPack.features[${index}].geometry`,
            counts,
          ),
        };
      }
      assertExactKeys(feature, `boundaryPack.features[${index}]`, [
        "kind",
        "feature_id",
        "label",
        "non_scope_reason",
        "geometry",
      ]);
      if (feature.kind !== "context" || feature.non_scope_reason !== "disputed-territory-context") {
        throw assetLimitError("Boundary-pack context feature is invalid.", descriptor.assetId);
      }
      const featureId = parseString(
        feature.feature_id,
        `boundaryPack.features[${index}].feature_id`,
        128,
      );
      const identity = `context\u0000${featureId}`;
      if (identities.has(identity)) throw assetLimitError("Duplicate pack feature.", featureId);
      identities.add(identity);
      return {
        kind: "context",
        featureId,
        label: parseUnicodeLabel(feature.label, `boundaryPack.features[${index}].label`),
        nonScopeReason: "disputed-territory-context",
        geometry: decodeGeometry(
          feature.geometry,
          `boundaryPack.features[${index}].geometry`,
          counts,
        ),
      };
    });
    asset = {
      schemaVersion: 1,
      parentScopeKey: parseCanonicalScopeKey(record.parent_scope_key, "boundaryPack.parent_scope_key"),
      features,
    };
  } else {
    throw geometryError("Asset media type is unsupported.", descriptor.assetId);
  }

  if (counts.vertexCount !== descriptor.vertexCount) {
    throw assetLimitError("Decoded vertex count does not match the descriptor.", descriptor.assetId);
  }
  if (
    descriptor.featureCount !== undefined &&
    counts.featureCount !== descriptor.featureCount
  ) {
    throw assetLimitError("Decoded feature count does not match the descriptor.", descriptor.assetId);
  }
  const estimatedHeapBytes = 1_024
    + counts.featureCount * 256
    + counts.polygonCount * 128
    + counts.ringCount * 64
    + counts.vertexCount * 64;
  if (estimatedHeapBytes > MAX_ASSET_HEAP_BYTES) {
    throw assetLimitError("Decoded asset exceeds the heap budget.", descriptor.assetId);
  }
  return {
    asset: freezeSpatialValue(asset),
    estimatedHeapBytes,
  };
}
