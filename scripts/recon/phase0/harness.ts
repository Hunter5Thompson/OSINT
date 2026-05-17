import * as THREE from "three";
// Pinned imports — concrete classes per each library's type defs on 2026-05-18.
// If a class name changes in a later version, update both the import and
// package.json pin; do not rely on "default" exports here.
// NOTE: package "@sparkjs/spark" in the plan was an alias; actual npm package
// is "@sparkjsdev/spark" (verified 2026-05-18). Pinned to 0.1.10, the latest
// 0.x release; if the operator wants to test the 2.x rewrite they must update
// both this import and the SplatMesh API call site.
import { SplatMesh, SplatFileType } from "@sparkjsdev/spark";
import * as GaussianSplats3D from "@mkkellogg/gaussian-splats-3d";

const PLY_URL = "/JAX_068_final.ply";

interface Timing {
  first_progress_ms: number | null;
  first_frame_ms: number | null;
  total_ms: number | null;
  error: string | null;
}

const results: { spark: Timing; mkk: Timing; ua: string; pinned_versions: Record<string, string> } = {
  spark: empty(),
  mkk: empty(),
  ua: navigator.userAgent,
  pinned_versions: {
    "@sparkjsdev/spark": "0.1.10",
    "@mkkellogg/gaussian-splats-3d": "0.4.7",
    three: "0.165.0",
  },
};

function empty(): Timing {
  return { first_progress_ms: null, first_frame_ms: null, total_ms: null, error: null };
}

function log(line: string) {
  const el = document.getElementById("results")!;
  el.textContent += line + "\n";
}

// Stream PLY via fetch() so we can measure first_progress_ms honestly.
// The 0.1.10 SplatMesh API has no onProgress hook (verified in
// node_modules/@sparkjsdev/spark/dist/types/SplatMesh.d.ts), and mkk's
// onProgress fires per-chunk but only after the loader is constructed.
// We pre-fetch the file once, time the first non-zero chunk, then hand
// the bytes off to each renderer.
async function fetchPlyBytes(t: Timing, tStart: number): Promise<Uint8Array> {
  const res = await fetch(PLY_URL);
  if (!res.ok || !res.body) throw new Error(`fetch ${PLY_URL} -> ${res.status}`);
  const reader = res.body.getReader();
  const chunks: Uint8Array[] = [];
  let total = 0;
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    if (value && value.byteLength > 0) {
      if (t.first_progress_ms === null) {
        t.first_progress_ms = performance.now() - tStart;
      }
      chunks.push(value);
      total += value.byteLength;
    }
  }
  const merged = new Uint8Array(total);
  let off = 0;
  for (const c of chunks) {
    merged.set(c, off);
    off += c.byteLength;
  }
  return merged;
}

async function runSpark(canvas: HTMLCanvasElement, t: Timing) {
  const tStart = performance.now();
  try {
    // preserveDrawingBuffer: true is REQUIRED so canvas.toBlob() captures
    // pixels after requestAnimationFrame; without it most drivers return a
    // transparent PNG. The cost is a slight perf hit, fine for a smoke test.
    const renderer = new THREE.WebGLRenderer({
      canvas,
      antialias: false, // Spark docs: antialias makes splatting slower without quality gain
      preserveDrawingBuffer: true,
    });
    renderer.setSize(canvas.clientWidth, canvas.clientHeight, false);
    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(60, canvas.clientWidth / canvas.clientHeight, 0.1, 5000);
    camera.position.set(0, 0, 200);
    camera.lookAt(0, 0, 0);

    // Stream the PLY through fetch() to measure first_progress_ms honestly,
    // then hand the bytes to SplatMesh via the fileBytes option (verified in
    // SplatMesh.d.ts). SplatMesh has no onProgress in 0.1.10 and the readiness
    // promise is `initialized`, not `loadPromise`.
    const bytes = await fetchPlyBytes(t, tStart);
    const mesh = new SplatMesh({
      fileBytes: bytes,
      fileType: SplatFileType.PLY,
    });
    await mesh.initialized;
    scene.add(mesh);

    renderer.render(scene, camera);
    t.first_frame_ms = performance.now() - tStart;
    requestAnimationFrame(function loop() {
      renderer.render(scene, camera);
      requestAnimationFrame(loop);
    });
    t.total_ms = performance.now() - tStart;
    log(`spark: progress=${t.first_progress_ms?.toFixed(0)}ms frame=${t.first_frame_ms.toFixed(0)}ms`);
  } catch (e) {
    t.error = (e as Error).message;
    log(`spark ERROR: ${t.error}`);
  }
}

async function runMkk(canvas: HTMLCanvasElement, t: Timing) {
  const tStart = performance.now();
  try {
    // Hand mkk a pre-built renderer wrapping the existing <canvas id="mkk">.
    // Verified in node_modules/@mkkellogg/gaussian-splats-3d/build/gaussian-splats-3d.module.js
    // around line 12295 / 12491 — `options.renderer` flips usingExternalRenderer=true
    // and the viewer skips creating its own canvas. preserveDrawingBuffer is
    // required here too so canvas.toBlob() captures pixels.
    const mkkRenderer = new THREE.WebGLRenderer({
      canvas,
      antialias: false,
      precision: "highp",
      preserveDrawingBuffer: true,
    });
    mkkRenderer.setSize(canvas.clientWidth, canvas.clientHeight, false);

    const viewer = new GaussianSplats3D.Viewer({
      renderer: mkkRenderer,
      useBuiltInControls: false,
      sharedMemoryForWorkers: false,
      selfDrivenMode: true,
    });
    let progressFired = false;
    await viewer.addSplatScene(PLY_URL, {
      onProgress: (_percent: number, _label: string, _status: unknown) => {
        if (!progressFired) {
          t.first_progress_ms = performance.now() - tStart;
          progressFired = true;
        }
      },
    });
    t.first_frame_ms = performance.now() - tStart;
    viewer.start();
    t.total_ms = performance.now() - tStart;
    log(`mkk: progress=${t.first_progress_ms?.toFixed(0)}ms frame=${t.first_frame_ms.toFixed(0)}ms`);
  } catch (e) {
    t.error = (e as Error).message;
    log(`mkk ERROR: ${t.error}`);
  }
}

document.getElementById("start")!.addEventListener("click", async (ev) => {
  // Prevent double-render-on-second-click: both runSpark and viewer.start()
  // schedule infinite rAF loops, so a second click would stack them.
  const btn = ev.currentTarget as HTMLButtonElement;
  btn.disabled = true;
  await Promise.all([
    runSpark(document.getElementById("spark") as HTMLCanvasElement, results.spark),
    runMkk(document.getElementById("mkk") as HTMLCanvasElement, results.mkk),
  ]);
  log(`done`);
});

function downloadCanvas(canvas: HTMLCanvasElement, name: string) {
  canvas.toBlob((blob) => {
    if (!blob) return;
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = name;
    a.click();
    URL.revokeObjectURL(url);
  });
}

document.getElementById("screenshot-spark")!.addEventListener("click", () =>
  downloadCanvas(document.getElementById("spark") as HTMLCanvasElement, "spark.png"),
);
document.getElementById("screenshot-mkk")!.addEventListener("click", () =>
  downloadCanvas(document.getElementById("mkk") as HTMLCanvasElement, "mkk.png"),
);

document.getElementById("export")!.addEventListener("click", () => {
  const blob = new Blob([JSON.stringify(results, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = "phase0-results.json";
  a.click();
  URL.revokeObjectURL(url);
});
