import type { DefaultCamera } from "../../../lib/recon/types";

export interface SplatRenderProgress {
  loaded: number;
  total: number;
}

export type CameraAxis = "x" | "y" | "z";

export interface SplatRenderHandle {
  dispose(): void;
  captureScreenshot(): Promise<Blob>;
  getCanvas(): HTMLCanvasElement;
  /** Translate the camera along its local axis. `delta` is in renderer units. */
  move(axis: CameraAxis, delta: number): void;
  /** Rotate the camera. Inputs are radians; mouse-move multiplies by ~0.002. */
  look(yawDelta: number, pitchDelta: number): void;
}

export interface SplatRenderOptions {
  plyUrl: string;
  defaultCamera: DefaultCamera;
  onProgress?: (p: SplatRenderProgress) => void;
  onFirstFrame?: () => void;
  onError?: (e: Error) => void;
}

export interface SplatRenderer {
  render(canvas: HTMLCanvasElement, opts: SplatRenderOptions): Promise<SplatRenderHandle>;
}
