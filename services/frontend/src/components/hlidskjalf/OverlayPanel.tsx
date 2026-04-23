import type { CSSProperties, ReactNode } from "react";

export type OverlayPanelVariant = "expanded" | "collapsed" | "hidden";

export interface OverlayPanelProps {
  paragraph: string;
  label: string;
  variant: OverlayPanelVariant;
  onClose?: () => void;
  onExpand?: () => void;
  width?: number;
  children: ReactNode;
  style?: CSSProperties;
}

const panelBase: CSSProperties = {
  background: "var(--hl-panel-bg)",
  border: "var(--hl-panel-border)",
  backdropFilter: "var(--hl-panel-blur)",
  WebkitBackdropFilter: "var(--hl-panel-blur)",
  color: "var(--bone)",
  fontFamily: '"Hanken Grotesk", system-ui, sans-serif',
  fontSize: 12,
  pointerEvents: "auto",
};

const panelHeader: CSSProperties = {
  display: "flex",
  alignItems: "center",
  justifyContent: "space-between",
  gap: "0.75rem",
  padding: "0.55rem 0.75rem",
  borderBottom: "var(--hl-panel-border)",
};

const panelTag: CSSProperties = {
  fontFamily: '"Martian Mono", ui-monospace, monospace',
  fontSize: "0.62rem",
  letterSpacing: "0.14em",
  textTransform: "uppercase",
  color: "var(--stone)",
};

const panelCloseBtn: CSSProperties = {
  border: "none",
  background: "transparent",
  color: "var(--ash)",
  cursor: "pointer",
  fontFamily: '"Martian Mono", ui-monospace, monospace',
  fontSize: "0.78rem",
  lineHeight: 1,
  padding: 0,
};

const collapsedTab: CSSProperties = {
  ...panelBase,
  width: 30,
  minHeight: 122,
  padding: "0.6rem 0.4rem",
  writingMode: "vertical-rl",
  transform: "rotate(180deg)",
  display: "inline-flex",
  alignItems: "center",
  justifyContent: "center",
  borderRadius: 0,
  cursor: "pointer",
  letterSpacing: "0.12em",
  textTransform: "uppercase",
  fontFamily: '"Martian Mono", ui-monospace, monospace',
  fontSize: "0.62rem",
};

export function OverlayPanel({
  paragraph,
  label,
  variant,
  onClose,
  onExpand,
  width = 320,
  children,
  style,
}: OverlayPanelProps) {
  if (variant === "hidden") return null;

  if (variant === "collapsed") {
    return (
      <button
        type="button"
        aria-label={`expand ${label}`}
        onClick={onExpand}
        style={{ ...collapsedTab, ...style }}
      >
        {`§ ${paragraph} · ${label}`}
      </button>
    );
  }

  return (
    <section
      role="region"
      aria-label={label}
      style={{ ...panelBase, ...style, width: `min(calc(100vw - 2rem), ${width}px)` }}
    >
      <header style={panelHeader}>
        <span style={panelTag}>{`§ ${paragraph} · ${label}`}</span>
        {onClose ? (
          <button
            type="button"
            aria-label={`close ${label}`}
            onClick={onClose}
            style={panelCloseBtn}
          >
            ×
          </button>
        ) : null}
      </header>
      <div style={{ padding: "0.75rem" }}>{children}</div>
    </section>
  );
}
