import { describe, it, expect } from "vitest";
import * as THREE from "three";
import { _computeRightVector } from "../mkkRenderer";

/**
 * Regression test for the strafe-right cross-product order.
 *
 * For a canonical THREE camera at (0,0,10) looking at the origin with
 * up=(0,1,0), forward=(0,0,-1). The pilot's right is +X, computed as
 * forward × up = (0,0,-1) × (0,1,0) = (1,0,0).
 *
 * The reverse order up × forward = (-1,0,0) would point LEFT — a common
 * footgun. These tests lock in the correct convention.
 *
 * We test the pure helper deterministically — no WebGL context required.
 */
describe("_computeRightVector", () => {
  it("returns a unit vector", () => {
    const camera = new THREE.PerspectiveCamera(60, 1, 0.1, 100);
    camera.position.set(5, 3, 7);
    camera.lookAt(1, 2, -4);

    const right = _computeRightVector(camera);

    expect(right.length()).toBeCloseTo(1, 5);
  });

  it("returns a vector perpendicular to the camera's forward direction", () => {
    const camera = new THREE.PerspectiveCamera(60, 1, 0.1, 100);
    camera.position.set(2, 4, 6);
    camera.lookAt(-1, 1, 0);

    const right = _computeRightVector(camera);
    const forward = new THREE.Vector3();
    camera.getWorldDirection(forward);

    expect(right.dot(forward)).toBeCloseTo(0, 5);
  });

  it("returns a vector perpendicular to camera.up", () => {
    const camera = new THREE.PerspectiveCamera(60, 1, 0.1, 100);
    camera.position.set(0, 0, 10);
    camera.lookAt(0, 0, 0);

    const right = _computeRightVector(camera);

    expect(right.dot(camera.up)).toBeCloseTo(0, 5);
  });

  it("for a camera at +Z looking down -Z, returns forward × up = (+1,0,0)", () => {
    // Canonical camera: position (0,0,10), looking at origin → forward=(0,0,-1).
    // forward × up = (0,0,-1) × (0,1,0) = (1, 0, 0) — pilot's right.
    const camera = new THREE.PerspectiveCamera(60, 1, 0.1, 100);
    camera.position.set(0, 0, 10);
    camera.lookAt(0, 0, 0);

    const right = _computeRightVector(camera);

    expect(right.x).toBeCloseTo(1, 5);
    expect(right.y).toBeCloseTo(0, 5);
    expect(right.z).toBeCloseTo(0, 5);
  });

  it("strafe-right gives +X for canonical camera (NOT -X — that would be left)", () => {
    const camera = new THREE.PerspectiveCamera(60, 1, 0.1, 1000);
    camera.position.set(0, 0, 10);
    camera.lookAt(0, 0, 0);
    camera.updateMatrixWorld();
    const right = _computeRightVector(camera);
    expect(right.x).toBeCloseTo(1);
    expect(right.y).toBeCloseTo(0);
    expect(right.z).toBeCloseTo(0);
  });
});
