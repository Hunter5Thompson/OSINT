import { useCallback, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useRecon } from "../../state/ReconContext";
import { useReconManifest } from "../../lib/recon/manifest";
import { loadDefaultSplatRenderer, type SplatRenderHandle } from "./renderer";
import { WebGLCheck } from "./WebGLCheck";
import { BandwidthGuard } from "./BandwidthGuard";
import { CameraControls } from "./CameraControls";
import { CaptureButton } from "./CaptureButton";
import "./reconViewer.css";

type Phase =
  | { kind: "idle" }
  | { kind: "loading"; loaded: number; total: number }
  | { kind: "ready" }
  | { kind: "error"; message: string };

const LARGE_SCENE_BYTES = 300 * 1024 * 1024;

export function ReconViewer() {
  const { activeSceneId, closeScene } = useRecon();
  const { scenes } = useReconManifest();
  const scene = activeSceneId ? scenes.find((s) => s.scene_id === activeSceneId) : null;

  const canvasRef = useRef<HTMLCanvasElement>(null);
  const handleRef = useRef<SplatRenderHandle | null>(null);
  const [phase, setPhase] = useState<Phase>({ kind: "idle" });
  const [retryToken, setRetryToken] = useState(0);
  // Gate the renderer effect on BandwidthGuard confirm. Without this, the
  // render effect can fire before <canvas> is mounted (BandwidthGuard hides
  // children on metered connections) and the "Load anyway" click would have
  // no signal to re-run the effect because it changes no dependency.
  const [loadAllowed, setLoadAllowed] = useState(false);

  // Reset loadAllowed when switching from one scene to a *different* scene —
  // a different scene needs to re-pass the bandwidth gate. We skip the
  // initial null→sceneId transition because BandwidthGuard's onConfirm
  // (a child effect) fires BEFORE this parent effect; resetting here on
  // the initial mount would stomp the confirm and leave loadAllowed stuck
  // at false on a fast connection.
  const prevSceneIdRef = useRef<string | null>(null);
  useEffect(() => {
    if (prevSceneIdRef.current !== null && prevSceneIdRef.current !== activeSceneId) {
      setLoadAllowed(false);
    }
    prevSceneIdRef.current = activeSceneId;
  }, [activeSceneId]);

  // ESC closes the modal.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") closeScene(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [closeScene]);

  // Renderer lifecycle — re-runs when scene changes, when bandwidth is
  // confirmed (canvas appears), or when Retry is clicked.
  useEffect(() => {
    if (!scene || !loadAllowed) return;
    const canvas = canvasRef.current;
    if (!canvas) return;
    let cancelled = false;
    setPhase({ kind: "loading", loaded: 0, total: scene.ply_size_bytes });

    (async () => {
      try {
        const renderer = await loadDefaultSplatRenderer();
        if (cancelled) return;
        const handle = await renderer.render(canvas, {
          plyUrl: scene.ply_url,
          defaultCamera: scene.default_camera,
          onProgress: (p) => {
            if (!cancelled) setPhase({ kind: "loading", loaded: p.loaded, total: p.total });
          },
          onFirstFrame: () => {
            if (!cancelled) setPhase({ kind: "ready" });
          },
          onError: (e) => {
            if (!cancelled) setPhase({ kind: "error", message: e.message });
          },
        });
        if (cancelled) { handle.dispose(); return; }
        handleRef.current = handle;
      } catch (e) {
        if (!cancelled) setPhase({ kind: "error", message: (e as Error).message });
      }
    })();

    return () => {
      cancelled = true;
      handleRef.current?.dispose();
      handleRef.current = null;
    };
  }, [scene, loadAllowed, retryToken]);

  const onRetry = useCallback(() => setRetryToken((t) => t + 1), []);
  const onBandwidthConfirm = useCallback(() => setLoadAllowed(true), []);

  if (!scene) return null;
  const mb = Math.round(scene.ply_size_bytes / (1024 * 1024));
  const isLarge = scene.ply_size_bytes > LARGE_SCENE_BYTES;

  const modal = (
    <div className="recon-viewer" role="dialog" aria-label={scene.display_name}>
      <WebGLCheck
        fallback={
          <div className="recon-viewer__progress">
            WebGL2 is required for the recon viewer. Please upgrade your browser.
            <button onClick={closeScene}>Close</button>
          </div>
        }
      >
        <BandwidthGuard
          sizeBytes={scene.ply_size_bytes}
          onConfirm={onBandwidthConfirm}
          onCancel={closeScene}
        >
          <canvas ref={canvasRef} className="recon-viewer__canvas" />

          {phase.kind === "loading" && (
            <div className="recon-viewer__progress">
              Loading {scene.display_name} — {Math.round(phase.loaded / 1024 / 1024)} / {mb} MB
            </div>
          )}

          {phase.kind === "error" && (
            <div className="recon-viewer__progress recon-viewer__progress--error">
              <p>Recon viewer failed: {phase.message}</p>
              <button onClick={onRetry}>Retry</button>
            </div>
          )}

          {phase.kind === "ready" && (
            <>
              <CameraControls canvasRef={canvasRef} handleRef={handleRef} />
              <div className="recon-viewer__hud">
                <CaptureButton handleRef={handleRef} sceneId={scene.scene_id} />
              </div>
            </>
          )}
        </BandwidthGuard>
      </WebGLCheck>

      {isLarge && (
        <span className="recon-viewer__large-badge" aria-label="large scene">
          LARGE — {mb} MB
        </span>
      )}

      <button className="recon-viewer__close" onClick={closeScene}>Close ✕</button>
      <div className="recon-viewer__footer">{scene.attribution}</div>
    </div>
  );

  return createPortal(modal, document.body);
}
