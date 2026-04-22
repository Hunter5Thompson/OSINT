import type { ReactNode, CSSProperties } from "react";

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
  fontFamily: "'Hanken Grotesk', sans-serif",
  fontSize: "12px",
  pointerEvents: "auto",
};

const headerStyle: CSSProperties = {
  display: "flex",
  alignItems: "center",
  justifyContent: "space-between",
  padding: "10px 12px",
  borderBottom: "var(--hl-panel-border)",
};

const paragraphStyle: CSSProperties = {
  fontFamily: "'Hanken Grotesk', sans-serif",
  fontSize: "10px",
  letterSpacing: "0.22em",
  textTransform: "uppercase",
  color: "var(--stone)",
};

const closeBtn: CSSProperties = {
  background: "transparent",
  border: "none",
  color: "var(--ash)",
  cursor: "pointer",
  fontFamily: "'Martian Mono', monospace",
  fontSize: "11px",
  padding: "0 4px",
};

const tabStyle: CSSProperties = {
  ...panelBase,
  width: "32px",
  padding: "12px 6px",
  writingMode: "vertical-rl",
  transform: "rotate(180deg)",
  cursor: "pointer",
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
        style={{ ...tabStyle, ...style }}
      >
        § {paragraph} · {label}
      </button>
    );
  }

  return (
    <section
      role="region"
      aria-label={label}
      style={{ ...panelBase, width: `${width}px`, ...style }}
    >
      <header style={headerStyle}>
        <span style={paragraphStyle}>§ {paragraph} · {label}</span>
        {onClose ? (
          <button
            type="button"
            aria-label={`close ${label}`}
            onClick={onClose}
            style={closeBtn}
          >
            ×
          </button>
        ) : null}
      </header>
      <div style={{ padding: "12px" }}>{children}</div>
    </section>
  );
}
