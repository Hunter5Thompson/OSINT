import { useRouteError } from "react-router-dom";

/**
 * S1 temporary: catch Cesium-layer cleanup crashes on `/worldview` so they
 * don't take down the rest of the app. S2 "Worldview-Port" will harden the
 * layer lifecycle against React remounts and this boundary can be removed.
 */
export function WorldviewErrorBoundary() {
  const error = useRouteError();
  const message =
    error instanceof Error ? error.message : String(error ?? "unknown");

  return (
    <main
      className="hlid"
      style={{
        minHeight: "calc(100vh - 48px)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        padding: "48px",
      }}
    >
      <div style={{ maxWidth: "520px" }}>
        <div
          style={{
            fontFamily: "'Hanken Grotesk', sans-serif",
            fontSize: "10px",
            letterSpacing: "0.3em",
            textTransform: "uppercase",
            color: "var(--sentinel)",
          }}
        >
          § Worldview · viewer fault
        </div>
        <div
          style={{
            height: "1px",
            background: "var(--granite)",
            margin: "12px 0 16px",
          }}
        />
        <h1
          style={{
            fontFamily: "'Instrument Serif', serif",
            fontStyle: "italic",
            fontWeight: 400,
            color: "var(--parchment)",
            fontSize: "28px",
            lineHeight: 1.15,
            letterSpacing: "-0.01em",
            margin: 0,
          }}
        >
          The globe could not bind to a Cesium viewer this session.
        </h1>
        <p
          style={{
            fontFamily: "'Instrument Serif', serif",
            fontStyle: "italic",
            color: "var(--stone)",
            fontSize: "15px",
            lineHeight: 1.5,
            marginTop: "16px",
          }}
        >
          This is a known layer-cleanup race under React 19 remounts.
          Sprint&nbsp;2 will harden the viewer lifecycle. Use the top bar to
          return to another view.
        </p>
        <pre
          style={{
            fontFamily: "'Martian Mono', monospace",
            fontSize: "10px",
            color: "var(--ash)",
            marginTop: "20px",
            padding: "10px 12px",
            border: "1px solid var(--granite)",
            background: "var(--basalt)",
            overflowX: "auto",
            whiteSpace: "pre-wrap",
          }}
        >
          {message}
        </pre>
      </div>
    </main>
  );
}
