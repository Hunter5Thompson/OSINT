import { expect, it, vi } from "vitest";
import type { Viewer } from "cesium";
import { captureTerrainCacheRelease } from "./terrainCacheCleanup";
const caches = vi.hoisted(() => ({ plain: {}, skirt: {} }));
vi.mock("cesium", () => ({ VERSION: "1.142.0", TerrainProvider: {
  getRegularGridIndices: () => caches.plain,
  getRegularGridAndSkirtIndicesAndEdgeIndices: () => ({ indices: caches.skirt }),
} }));
const viewer = (id: string, destroyed = true) => ({ isDestroyed: () => destroyed, scene: { context: { id } } }) as unknown as Viewer;

it("removes only this context's destroyed buffers, including cache entries added after capture", () => {
  caches.plain = {}; caches.skirt = {};
  const release = captureTerrainCacheRelease(viewer("owned"));
  const live = { isDestroyed: () => false };
  const dead = { isDestroyed: () => true };
  Object.assign(caches.plain, { indexBuffers: { owned: dead, foreign: live } });
  Object.assign(caches.skirt, { indexBuffers: { owned: dead, otherDead: dead } });
  release(); release();
  expect(caches.plain).toEqual({ indexBuffers: { foreign: live } });
  expect(caches.skirt).toEqual({ indexBuffers: { otherDead: dead } });
});
it("does not delete a still-live buffer when teardown has failed", () => {
  const live = { isDestroyed: () => false };
  caches.plain = { indexBuffers: { owned: live } };
  captureTerrainCacheRelease(viewer("owned", false))();
  expect(caches.plain).toEqual({ indexBuffers: { owned: live } });
});
it("fails visibly if the pinned internal context contract changes", () => {
  expect(() => captureTerrainCacheRelease({ scene: {} } as Viewer)).toThrow(/Cesium/);
});

it("destroys an orphaned buffer still reference-counted after its owning viewer was destroyed", () => {
  const destroy = vi.fn();
  caches.plain = { indexBuffers: { owned: { isDestroyed: () => false, destroy } } };
  caches.skirt = {};
  captureTerrainCacheRelease(viewer("owned"))();
  expect(destroy).toHaveBeenCalledOnce();
  expect(caches.plain).toEqual({ indexBuffers: {} });
});
