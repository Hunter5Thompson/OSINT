import "./worldviewHudLoader.css";

export function WorldviewHudLoader() {
  return (
    <div className="wv-loader-wrap" role="status" aria-label="Initializing worldview">
      <div className="wv-loader" aria-hidden="true">
        <div className="wv-loader-cross" />
        <div className="wv-loader-orbit" />
        <div className="wv-loader-ring" />
        <div className="wv-loader-sweep" />
        <div className="wv-loader-reticle" />
        <div className="wv-loader-grain" />
        <div className="wv-loader-vignette" />
        <div className="wv-loader-label">WORLDVIEW BOOTSTRAP</div>
      </div>
    </div>
  );
}
