// Public catalog interface. Protocol, assets and lifecycle implementations remain internal.
export {
  type SpatialCatalogErrorInit,
  SpatialCatalogError,
  type SpatialBoundaryAttributionSource,
  type SpatialBoundaryProvenance,
  type SpatialBoundaryProvenanceLoader,
  type MemorySpatialCatalogOptions,
  type MemoryResolveCall,
  type MemoryPrefetchCall,
  type Position2D,
  type LinearRing,
  type PolygonCoordinates,
  type BoundaryGeometryV1,
  type BoundaryPackFeatureV1,
  type BoundaryPackV1,
  type BoundaryAsset,
  type BoundaryAssetLease,
  type SpatialCatalogClock,
  type BoundaryAssetStoreOptions,
  type BoundaryAssetStoreDiagnostics,
  type HttpSpatialCatalogOptions,
  type HttpSpatialCatalogDiagnostics,
} from "./catalog/core";
export {
  parseScopeProblem,
  parseResolvedScope,
  mapSpatialCatalogProblem,
} from "./catalog/metadata";
export {
  BoundaryAssetStore,
} from "./catalog/assets";
export {
  MemorySpatialCatalog,
} from "./catalog/memory";
export {
  HttpSpatialCatalog,
  createBootstrapSpatialCatalog,
} from "./catalog/http";
