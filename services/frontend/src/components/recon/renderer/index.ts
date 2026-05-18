export type {
  SplatRenderer,
  SplatRenderHandle,
  SplatRenderOptions,
  SplatRenderProgress,
  CameraAxis,
} from "./SplatRenderer";

/**
 * Dynamically loads the concrete renderer chosen in Phase 0. Callers MUST
 * use this rather than a static import to keep the splat library and three.js
 * out of the main Vite bundle (spec §5.2).
 */
export async function loadDefaultSplatRenderer(): Promise<
  import("./SplatRenderer").SplatRenderer
> {
  const mod = await import("./mkkRenderer");
  return mod.defaultSplatRenderer;
}
