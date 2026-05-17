import * as THREE from "three";
// Pinned imports — concrete classes per each library's README on 2026-05-11.
// If a class name changes in a later version, update both the import and
// package.json pin; do not rely on "default" exports here.
// NOTE: package "@sparkjs/spark" in the plan was an alias; actual npm package
// is "@sparkjsdev/spark" (verified 2026-05-18). Pinned to 0.1.10, the latest
// 0.x release; if the operator wants to test the 2.x rewrite they must update
// both this import and the SplatMesh API call site.
import { SplatMesh } from "@sparkjsdev/spark";
import * as GaussianSplats3D from "@mkkellogg/gaussian-splats-3d";

const PLY_URL = "/JAX_068_final.ply";
const PLY_EXPECTED_BYTES = 240164505;

interface Timing {
  module_load_ms: number;
  first_progress_ms: number | null;
  first_frame_ms: number | null;
  total_ms: number | null;
  error: string | null;
}

const results: { spark: Timing; mkk: Timing; ua: string; pinned_versions: Record<string,string> } = {
  spark: empty(), mkk: empty(),
  ua: navigator.userAgent,
  pinned_versions: { "@sparkjsdev/spark": "0.1.10", "@mkkellogg/gaussian-splats-3d": "0.4.7", three: "0.165.0" },
};

function empty(): Timing {
  return { module_load_ms: 0, first_progress_ms: null, first_frame_ms: null, total_ms: null, error: null };
}

function log(line: string) {
  const el = document.getElementById("results")!;
  el.textContent += line + "\n";
}

async function runSpark(canvas: HTMLCanvasElement, t: Timing) {
  const tStart = performance.now();
  try {
    const renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
    renderer.setSize(canvas.clientWidth, canvas.clientHeight, false);
    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(60, canvas.clientWidth / canvas.clientHeight, 0.1, 5000);
    camera.position.set(0, 0, 200);
    camera.lookAt(0, 0, 0);

    let progressFired = false;
    // SplatMesh exposes onProgress / onLoad per Spark 0.7 README.
    const mesh = new SplatMesh({
      url: PLY_URL,
      onProgress: (loaded: number, total: number) => {
        if (!progressFired) {
          t.first_progress_ms = performance.now() - tStart;
          progressFired = true;
        }
      },
    });
    scene.add(mesh);

    // Render loop; first frame timestamp = first requestAnimationFrame after mesh load resolves.
    await mesh.loadPromise;
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
    // Viewer API per gaussian-splats-3d 0.5 README.
    const viewer = new GaussianSplats3D.Viewer({
      useBuiltInControls: false,
      rootElement: canvas.parentElement!,
      sharedMemoryForWorkers: false,
    });
    let progressFired = false;
    await viewer.addSplatScene(PLY_URL, {
      onProgress: (percent: number) => {
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

document.getElementById("start")!.addEventListener("click", async () => {
  const moduleLoadStart = performance.now();
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
    a.href = url; a.download = name; a.click();
    URL.revokeObjectURL(url);
  });
}

document.getElementById("screenshot-spark")!.addEventListener("click",
  () => downloadCanvas(document.getElementById("spark") as HTMLCanvasElement, "spark.png"));
document.getElementById("screenshot-mkk")!.addEventListener("click",
  () => downloadCanvas(document.getElementById("mkk") as HTMLCanvasElement, "mkk.png"));

document.getElementById("export")!.addEventListener("click", () => {
  const blob = new Blob([JSON.stringify(results, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url; a.download = "phase0-results.json"; a.click();
  URL.revokeObjectURL(url);
});
