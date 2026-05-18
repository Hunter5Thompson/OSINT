// Minimal ambient module declaration for @mkkellogg/gaussian-splats-3d.
// The package ships no `.d.ts`. We type just the surface mkkRenderer.ts uses;
// the concrete viewer is wrapped behind `MkkViewerLike` in mkkRenderer.ts.
declare module "@mkkellogg/gaussian-splats-3d" {
  export const Viewer: new (opts: Record<string, unknown>) => any;
  const _default: Record<string, any>;
  export default _default;
}
