export type ViewerFailure = "context-lost" | "render-error";

interface ViewerHealthPort {
  canvas: HTMLCanvasElement;
  useDefaultRenderLoop: boolean;
  isDestroyed(): boolean;
  scene: { renderError: { addEventListener(listener: (scene?: unknown, error?: unknown) => void): () => void } };
}

/** One owner stops failed rendering and reports a recoverable view state. */
export function watchViewerHealth(viewer: ViewerHealthPort, report: (failure: ViewerFailure) => void): () => void {
  let disposed = false;
  let failed = false;
  const fail = (reason: ViewerFailure) => {
    if (disposed || failed || viewer.isDestroyed()) return;
    failed = true;
    viewer.useDefaultRenderLoop = false;
    report(reason);
  };
  const contextLost = (event: Event) => {
    event.preventDefault(); // Permit the browser to restore graphics resources.
    fail("context-lost");
  };
  viewer.canvas.addEventListener("webglcontextlost", contextLost);
  const removeError = viewer.scene.renderError.addEventListener((_scene, error) => {
    if (!disposed && !failed && error !== undefined) console.error("[GlobeViewer] rendering failed", error);
    fail("render-error");
  });
  return () => {
    if (disposed) return;
    disposed = true;
    viewer.canvas.removeEventListener("webglcontextlost", contextLost);
    removeError();
  };
}
