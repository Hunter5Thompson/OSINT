import type { CSSProperties } from "react";

import { WORLD_SCOPE_KEY } from "./contracts";
import { useSpatialScope } from "./react";

const navStyle: CSSProperties = {
  display: "flex",
  alignItems: "center",
  flexWrap: "wrap",
  gap: "0.4rem",
  padding: "0.45rem 0.65rem",
  border: "1px solid var(--granite)",
  background: "rgba(8, 11, 14, 0.86)",
  color: "var(--stone)",
  fontFamily: '"Martian Mono", ui-monospace, monospace',
  fontSize: "0.62rem",
  letterSpacing: "0.08em",
  textTransform: "uppercase",
};

const buttonStyle: CSSProperties = {
  border: 0,
  padding: "0.15rem 0.2rem",
  background: "transparent",
  color: "inherit",
  cursor: "pointer",
  font: "inherit",
  letterSpacing: "inherit",
  textTransform: "inherit",
};

export function SpatialScopeBreadcrumb() {
  const scope = useSpatialScope();
  if (scope.phase === "hydrating") {
    return (
      <nav aria-label="Spatial scope" style={navStyle}>
        <span role="status" aria-live="polite" aria-atomic="true">
          Loading spatial scope
        </span>
      </nav>
    );
  }

  const statusMessage = scope.pending !== null
    ? "Opening spatial scope…"
    : scope.visual.phase === "unavailable"
      ? "Boundary unavailable"
      : "";

  return (
    <nav aria-label="Spatial scope" style={navStyle}>
      {scope.path.map((item, index) => {
        const current = item.key === scope.current.key;
        return (
          <span key={item.key} style={{ display: "inline-flex", alignItems: "center" }}>
            {index > 0 ? <span aria-hidden="true">/</span> : null}
            <button
              type="button"
              aria-current={current ? "location" : undefined}
              onClick={() => {
                if (!current) void scope.enter(item.key, "breadcrumb");
              }}
              style={{
                ...buttonStyle,
                color: current ? "var(--parchment)" : "var(--stone)",
              }}
            >
              {item.shortLabel}
            </button>
          </span>
        );
      })}
      {scope.current.key !== WORLD_SCOPE_KEY ? (
        <button
          type="button"
          onClick={() => { void scope.ascend("breadcrumb"); }}
          style={{ ...buttonStyle, marginLeft: "0.35rem", color: "var(--signal)" }}
        >
          Eine Ebene hoch
        </button>
      ) : null}
      {scope.children.map((child) => (
        <button
          key={child.key}
          type="button"
          onClick={() => { void scope.enter(child.key, "child-click"); }}
          style={{
            ...buttonStyle,
            color: "var(--signal)",
            border: "1px solid var(--granite)",
          }}
        >
          {child.shortLabel}
        </button>
      ))}
      <span key="scope-status" role="status" aria-live="polite" aria-atomic="true">
        {statusMessage}
      </span>
    </nav>
  );
}
