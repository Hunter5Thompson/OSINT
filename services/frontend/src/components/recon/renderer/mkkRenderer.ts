import * as THREE from "three";
import * as GaussianSplats3D from "@mkkellogg/gaussian-splats-3d";
import type {
  CameraAxis,
  SplatRenderer,
  SplatRenderHandle,
  SplatRenderOptions,
} from "./SplatRenderer";

const MOVE_STEP = 0.5;
const PITCH_LIMIT = (Math.PI / 2) - 0.01;

/**
 * Camera-local right vector. For a camera with forward = -Z and up = +Y
 * (the THREE default), `forward × up = +X` — the pilot's right hand.
 * Reversing the order to `up × forward` would give -X (left) — a common
 * footgun. See `__tests__/mkkRenderer.test.ts` for the regression guard.
 */
export function _computeRightVector(camera: THREE.Camera): THREE.Vector3 {
  const forward = new THREE.Vector3();
  camera.getWorldDirection(forward);
  return new THREE.Vector3().crossVectors(forward, camera.up).normalize();
}

interface MkkViewerLike {
  addSplatScene(url: string, opts: Record<string, unknown>): Promise<unknown>;
  start(): void;
  dispose?(): void;
  stop?(): void;
}

async function fetchPlyWithProgress(
  url: string,
  onProgress?: (loaded: number, total: number) => void,
  signal?: AbortSignal,
): Promise<void> {
  // mkk's addSplatScene re-fetches from URL — we do a pre-fetch only for
  // the progress signal. The browser HTTP cache (matched on URL+headers)
  // serves the addSplatScene's request from cache, avoiding a double wire
  // transfer in practice. The Cache-Control: public, max-age=31536000,
  // immutable on /static/recon/* guarantees the cache hit.
  const res = await fetch(url, { signal });
  if (!res.ok) {
    throw new Error(`PLY fetch failed: ${res.status} ${res.statusText}`);
  }
  const total = Number(res.headers.get("content-length") ?? 0);
  const reader = res.body?.getReader();
  if (!reader) {
    onProgress?.(total || 1, total || 1);
    return;
  }
  let loaded = 0;
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      loaded += value.byteLength;
      onProgress?.(loaded, total || loaded);
    }
  } finally {
    reader.releaseLock();
  }
}

class MkkSplatRenderer implements SplatRenderer {
  async render(canvas: HTMLCanvasElement, opts: SplatRenderOptions): Promise<SplatRenderHandle> {
    const abort = new AbortController();
    const renderer = new THREE.WebGLRenderer({
      canvas,
      antialias: true,
      preserveDrawingBuffer: true,
    });
    renderer.setSize(canvas.clientWidth || 800, canvas.clientHeight || 600, false);

    const camera = new THREE.PerspectiveCamera(
      opts.defaultCamera.fov_deg,
      (canvas.clientWidth || 800) / (canvas.clientHeight || 600),
      0.1,
      5000,
    );
    const [px, py, pz] = opts.defaultCamera.position;
    const [lx, ly, lz] = opts.defaultCamera.look_at;
    camera.position.set(px, py, pz);
    camera.lookAt(lx, ly, lz);

    try {
      // 1) progress pre-fetch (loaded%total fires for the UI)
      await fetchPlyWithProgress(opts.plyUrl, (loaded, total) => {
        opts.onProgress?.({ loaded, total });
      }, abort.signal);

      // 2) mkk Viewer with the external renderer so screenshots target our canvas
      const ViewerCtor = (GaussianSplats3D as unknown as {
        Viewer: new (opts: Record<string, unknown>) => MkkViewerLike;
      }).Viewer;
      const viewer = new ViewerCtor({
        renderer,
        camera,
        useBuiltInControls: false,
        sharedMemoryForWorkers: false,
        selfDrivenMode: true,  // viewer.start() runs the rAF loop
      });
      await viewer.addSplatScene(opts.plyUrl, {});
      viewer.start();
      opts.onFirstFrame?.();

      return makeHandle(canvas, renderer, camera, viewer, abort);
    } catch (e) {
      // tear down anything we built so the caller can retry cleanly
      try { abort.abort(); } catch { /* ignore */ }
      try { renderer.dispose(); } catch { /* ignore */ }
      opts.onError?.(e instanceof Error ? e : new Error(String(e)));
      throw e;
    }
  }
}

function makeHandle(
  canvas: HTMLCanvasElement,
  renderer: THREE.WebGLRenderer,
  camera: THREE.PerspectiveCamera,
  viewer: MkkViewerLike,
  abort: AbortController,
): SplatRenderHandle {
  let disposed = false;

  return {
    getCanvas: () => canvas,

    dispose() {
      if (disposed) return;
      disposed = true;
      try { abort.abort(); } catch { /* ignore */ }
      try { viewer.stop?.(); } catch { /* ignore */ }
      try { viewer.dispose?.(); } catch { /* ignore */ }
      try { renderer.dispose(); } catch { /* ignore */ }
    },

    async captureScreenshot(): Promise<Blob> {
      // preserveDrawingBuffer=true on the renderer means toBlob captures the
      // last drawn frame correctly.
      return new Promise<Blob>((resolve, reject) => {
        canvas.toBlob(
          (blob) => blob ? resolve(blob) : reject(new Error("toBlob produced null")),
          "image/png",
        );
      });
    },

    move(axis: CameraAxis, delta: number) {
      const step = delta * MOVE_STEP;
      if (axis === "x") {
        // strafe along camera-local right (forward × up = +X for the
        // canonical camera; see _computeRightVector docblock).
        const right = _computeRightVector(camera);
        camera.position.addScaledVector(right, step);
      } else if (axis === "y") {
        // translate world-up
        camera.position.y += step;
      } else { // "z"
        const forward = new THREE.Vector3();
        camera.getWorldDirection(forward);
        camera.position.addScaledVector(forward, -step);
      }
    },

    look(yawDelta: number, pitchDelta: number) {
      // yaw around world-up
      const euler = new THREE.Euler(0, 0, 0, "YXZ");
      euler.setFromQuaternion(camera.quaternion);
      euler.y -= yawDelta;
      euler.x -= pitchDelta;
      euler.x = Math.max(-PITCH_LIMIT, Math.min(PITCH_LIMIT, euler.x));
      camera.quaternion.setFromEuler(euler);
    },
  };
}

export const defaultSplatRenderer: SplatRenderer = new MkkSplatRenderer();
