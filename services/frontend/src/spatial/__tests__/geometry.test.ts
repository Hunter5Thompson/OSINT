import { describe, expect, it } from "vitest";

import type {
  BoundaryGeometryV1,
  BoundaryPackV1,
} from "../catalog";
import type {
  RenderAssetDescriptor,
  ResolvedPresentationInput,
} from "../contracts";
import { parseCatalogRevision, parseScopeKeyCandidate } from "../contracts";
import {
  classifyPointInGeometry,
  createBoundaryGeometryIndex,
  createSpatialChildGeometryIndex,
  selectPreferredChildDescriptor,
  unwrapQueryAndRing,
} from "../geometry";

function geometry(
  polygons: BoundaryGeometryV1["polygons"],
): BoundaryGeometryV1 {
  return { schemaVersion: 1, geometryType: "MultiPolygon", polygons };
}

const square = geometry([
  [[[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]]],
]);

const squareWithHole = geometry([
  [
    [[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]],
    [[3, 3], [3, 7], [7, 7], [7, 3], [3, 3]],
  ],
]);

const multipart = geometry([
  [[[-125, 25], [-66, 25], [-66, 49], [-125, 49], [-125, 25]]],
  [[[-160, 19], [-154, 19], [-154, 23], [-160, 23], [-160, 19]]],
]);

describe("classifyPointInGeometry", () => {
  it("handles polygon holes and multipolygons", () => {
    expect(classifyPointInGeometry(square, 5, 5)).toBe("inside");
    expect(classifyPointInGeometry(square, 11, 5)).toBe("outside");
    expect(classifyPointInGeometry(squareWithHole, 5, 5)).toBe("outside");
    expect(classifyPointInGeometry(squareWithHole, 1, 1)).toBe("inside");
    expect(classifyPointInGeometry(multipart, -100, 40)).toBe("inside");
    expect(classifyPointInGeometry(multipart, -157, 21)).toBe("inside");
    expect(classifyPointInGeometry(multipart, -130, 40)).toBe("outside");
  });

  it("unwraps dateline rings into the query longitude domain", () => {
    const dateline = geometry([
      [[[179, -2], [-179, -2], [-179, 2], [179, 2], [179, -2]]],
    ]);

    const [query, ring] = unwrapQueryAndRing(-179.5, dateline.polygons[0]![0]!);

    expect(query).toBe(180.5);
    expect(Math.max(...ring.map(([longitude]) => longitude))).toBe(181);
    expect(classifyPointInGeometry(dateline, 179.5, 0)).toBe("inside");
    expect(classifyPointInGeometry(dateline, -179.5, 0)).toBe("inside");
    expect(classifyPointInGeometry(dateline, 0, 0)).toBe("outside");
  });

  it("uses the descriptor error band for boundary-uncertain", () => {
    expect(classifyPointInGeometry(square, 5, 5, 60)).toBe("inside");
    expect(classifyPointInGeometry(square, 0.0005, 5, 60)).toBe(
      "boundary-uncertain",
    );
    expect(classifyPointInGeometry(square, -0.0005, 5, 60)).toBe(
      "boundary-uncertain",
    );
    expect(classifyPointInGeometry(square, 0, 5, 0)).toBe(
      "boundary-uncertain",
    );
  });

  it("rejects non-finite and out-of-range query coordinates", () => {
    expect(() => classifyPointInGeometry(square, 181, 0)).toThrow(
      /longitude/i,
    );
    expect(() => classifyPointInGeometry(square, 0, Number.NaN)).toThrow(
      /latitude/i,
    );
  });
});

describe("BoundaryGeometryIndex", () => {
  it("uses one minimal span for an ordinary polygon", () => {
    const index = createBoundaryGeometryIndex([
      { value: "square", geometry: square },
    ]);

    expect(index.indexedSpanCount).toBe(1);
    expect(index.query(5, 5)).toEqual([
      { value: "square", containment: "inside" },
    ]);
  });

  it("deduplicates a dateline feature represented by two RBush spans", () => {
    const dateline = geometry([
      [[[179, -2], [-179, -2], [-179, 2], [179, 2], [179, -2]]],
    ]);
    const index = createBoundaryGeometryIndex([
      { value: "dateline", geometry: dateline },
    ]);

    expect(index.indexedSpanCount).toBe(2);
    expect(index.query(180, 0)).toEqual([
      { value: "dateline", containment: "inside" },
    ]);
    expect(index.query(-180, 0)).toEqual([
      { value: "dateline", containment: "inside" },
    ]);
  });
});

describe("preferred child pick geometry", () => {
  const overviewDescriptor: RenderAssetDescriptor = {
    role: "render",
    lod: "overview",
    assetId: "a".repeat(64),
    mediaType: "application/vnd.odin.boundary-pack+json;v=1",
    byteLength: 1,
    vertexCount: 10,
    featureCount: 2,
  };
  const regionalDescriptor: RenderAssetDescriptor = {
    ...overviewDescriptor,
    lod: "regional",
    assetId: "b".repeat(64),
  };
  const world = parseScopeKeyCandidate("world");
  const childA = parseScopeKeyCandidate("country:AAA");
  const childB = parseScopeKeyCandidate("country:BBB");
  const presentation: ResolvedPresentationInput = {
    mode: "boundary",
    scopeKey: world,
    catalogRevision: parseCatalogRevision("spatial-v1-123456789abc"),
    preferredLod: "overview",
    outlineLods: {},
    childrenLods: {
      overview: overviewDescriptor,
      regional: regionalDescriptor,
    },
    cameraExtent: { kind: "world" },
  };
  const overviewPack: BoundaryPackV1 = {
    schemaVersion: 1,
    parentScopeKey: world,
    features: [
      { kind: "scope", scopeKey: childA, label: "A", geometry: square },
      {
        kind: "scope",
        scopeKey: childB,
        label: "B",
        geometry: geometry([
          [[[10, 0], [20, 0], [20, 10], [10, 10], [10, 0]]],
        ]),
      },
    ],
  };
  const divergentRegionalPack: BoundaryPackV1 = {
    ...overviewPack,
    features: [
      {
        kind: "scope",
        scopeKey: childA,
        label: "A",
        geometry: geometry([
          [[[0, 0], [8, 0], [8, 10], [0, 10], [0, 0]]],
        ]),
      },
      {
        kind: "scope",
        scopeKey: childB,
        label: "B",
        geometry: geometry([
          [[[8, 0], [20, 0], [20, 10], [8, 10], [8, 0]]],
        ]),
      },
    ],
  };

  it("pins picks to childrenLods[preferredLod] across camera LOD changes", () => {
    expect(selectPreferredChildDescriptor(presentation)).toBe(
      overviewDescriptor,
    );
    const pickIndex = createSpatialChildGeometryIndex(
      presentation,
      overviewDescriptor,
      overviewPack,
    );
    const regionalIndex = createBoundaryGeometryIndex(
      divergentRegionalPack.features
        .filter((feature) => feature.kind === "scope")
        .map((feature) => ({ value: feature.scopeKey, geometry: feature.geometry })),
    );

    expect(regionalIndex.query(9, 5)[0]?.value).toBe(childB);
    for (const cameraLod of ["overview", "regional", "local"] as const) {
      expect(cameraLod).toBeTruthy();
      expect(pickIndex.query(9, 5)[0]?.value.scopeKey).toBe(childA);
    }
  });

  it("rejects a camera-selected descriptor as a pick source", () => {
    expect(() =>
      createSpatialChildGeometryIndex(
        presentation,
        regionalDescriptor,
        divergentRegionalPack,
      ),
    ).toThrow(/preferred child descriptor/i);
  });
});
