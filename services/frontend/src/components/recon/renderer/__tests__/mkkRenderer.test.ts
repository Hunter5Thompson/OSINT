import { describe, it, expect } from "vitest";
import * as THREE from "three";
import { _computeRightVector } from "../mkkRenderer";

/**
 * Regression test for the strafe-right cross-product order.
 *
 * Bug history: the move("x") branch used `forward.cross(camera.up)` which
 * yielded the wrong strafe direction in-app (camera moved left when the
 * user pressed strafe-right). The fix uses `up × forward` via
 * crossVectors(up, forward).
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

  it("for a camera at +Z looking down -Z, returns up × forward = (-1,0,0)", () => {
    // Canonical camera: position (0,0,10), looking at origin → forward=(0,0,-1).
    // up × forward = (0,1,0) × (0,0,-1) = (-1, 0, 0).
    const camera = new THREE.PerspectiveCamera(60, 1, 0.1, 100);
    camera.position.set(0, 0, 10);
    camera.lookAt(0, 0, 0);

    const right = _computeRightVector(camera);

    expect(right.x).toBeCloseTo(-1, 5);
    expect(right.y).toBeCloseTo(0, 5);
    expect(right.z).toBeCloseTo(0, 5);
  });

  it("regression: returns the opposite of the buggy forward × up direction", () => {
    // The original bug computed forward.cross(camera.up). Verify our fix
    // produces the negation — i.e., flipped sign — to lock in the cross order.
    const camera = new THREE.PerspectiveCamera(60, 1, 0.1, 100);
    camera.position.set(3, 5, 8);
    camera.lookAt(0, 0, 0);

    const correctRight = _computeRightVector(camera);

    const forward = new THREE.Vector3();
    camera.getWorldDirection(forward);
    const buggyRight = forward.clone().cross(camera.up).normalize();

    expect(correctRight.x).toBeCloseTo(-buggyRight.x, 5);
    expect(correctRight.y).toBeCloseTo(-buggyRight.y, 5);
    expect(correctRight.z).toBeCloseTo(-buggyRight.z, 5);
  });
});
