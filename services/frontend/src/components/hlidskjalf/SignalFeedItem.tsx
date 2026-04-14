/**
 * SignalFeedItem — severity dot + mono timestamp + serif description.
 *
 * Used in War Room + Briefing Room signal feeds. Stub for S1 Task 3.
 */
import type { CSSProperties } from "react";

export type SignalSeverity = "sent" | "amb" | "sage" | "dim";

export interface SignalFeedItemProps {
  severity: SignalSeverity;
  ts: string;
  text: string;
  onClick?: () => void;
  className?: string;
  style?: CSSProperties;
}

const SEVERITY_VAR: Record<SignalSeverity, string> = {
  sent: "var(--sentinel)",
  amb: "var(--amber)",
  sage: "var(--sage)",
  dim: "var(--ash)",
};

export function SignalFeedItem({
  severity,
  ts,
  text,
  onClick,
  className,
  style,
}: SignalFeedItemProps) {
  const interactive = typeof onClick === "function";
  return (
    <div
      className={className}
      data-part="signal-item"
      data-severity={severity}
      role={interactive ? "button" : undefined}
      tabIndex={interactive ? 0 : undefined}
      onClick={onClick}
      onKeyDown={
        interactive
          ? (e) => {
              if (e.key === "Enter" || e.key === " ") {
                e.preventDefault();
                onClick?.();
              }
            }
          : undefined
      }
      style={{
        display: "flex",
        alignItems: "baseline",
        gap: "0.75rem",
        padding: "0.5rem 0",
        cursor: interactive ? "pointer" : undefined,
        ...style,
      }}
    >
      <span
        data-part="dot"
        aria-hidden="true"
        style={{
          width: 6,
          height: 6,
          borderRadius: "50%",
          backgroundColor: SEVERITY_VAR[severity],
          flexShrink: 0,
        }}
      />
      <span
        className="mono"
        data-part="ts"
        style={{ fontSize: "0.7rem", color: "var(--ash)", flexShrink: 0 }}
      >
        {ts}
      </span>
      <span
        className="serif"
        data-part="text"
        style={{ fontStyle: "italic", color: "var(--bone)", fontSize: "0.95rem" }}
      >
        {text}
      </span>
    </div>
  );
}
