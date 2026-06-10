import { useRef } from "react";
import type { HistogramBucket, TimelineNotable } from "../../types";
import { DEFAULT_COLOR, EVENT_COLORS } from "../layers/EventLayer";
import { severityRank } from "../../lib/severity";

type Preset = "24h" | "7d" | "30d";

interface ChronikTimelineProps {
  buckets: HistogramBucket[];
  notables: TimelineNotable[];
  rangeStartMs: number;
  rangeEndMs: number;
  cursorMs: number;
  mode: "live" | "replay";
  playing: boolean;
  preset: Preset;
  geoLocatedCount: number;
  totalCount: number;
  onSeek: (ms: number) => void;
  onBrush: (startMs: number, endMs: number) => void;
  onSelectNotable: (id: string) => void;
  onTogglePlay: () => void;
  onNow: () => void;
  onPreset: (p: Preset) => void;
}

const DRAG_THRESHOLD_PX = 6;
const STRIP_HEIGHT = 56;
const PRESETS: Preset[] = ["24h", "7d", "30d"];

// Functional shell only — visual treatment goes through the Hlíðskjalf polish pass.
export function ChronikTimeline({
  buckets, notables, rangeStartMs, rangeEndMs, cursorMs, mode, playing, preset,
  geoLocatedCount, totalCount, onSeek, onBrush, onSelectNotable, onTogglePlay, onNow, onPreset,
}: ChronikTimelineProps) {
  const stripRef = useRef<HTMLDivElement | null>(null);
  const dragStartXRef = useRef<number | null>(null);

  const span = Math.max(rangeEndMs - rangeStartMs, 1);
  const maxCount = Math.max(1, ...buckets.map((b) => b.count));

  const msToPct = (ms: number) => ((ms - rangeStartMs) / span) * 100;
  const xToMs = (clientX: number) => {
    const rect = stripRef.current?.getBoundingClientRect();
    const left = rect?.left ?? 0;
    const width = rect && rect.width > 0 ? rect.width : 1;
    const frac = Math.min(1, Math.max(0, (clientX - left) / width));
    return rangeStartMs + frac * span;
  };

  const onMouseDown = (e: React.MouseEvent) => {
    dragStartXRef.current = e.clientX;
  };
  const onMouseUp = (e: React.MouseEvent) => {
    const startX = dragStartXRef.current;
    dragStartXRef.current = null;
    if (startX == null) return;
    if (Math.abs(e.clientX - startX) >= DRAG_THRESHOLD_PX) {
      const a = xToMs(startX);
      const b = xToMs(e.clientX);
      onBrush(Math.min(a, b), Math.max(a, b)); // drag = brush
    } else {
      onSeek(xToMs(e.clientX)); // click = seek
    }
  };

  const cursorLabel = Number.isFinite(cursorMs)
    ? `${new Date(cursorMs).toISOString().replace("T", " ").slice(0, 19)}Z`
    : "--";

  return (
    <section
      aria-label="chronik timeline"
      style={{
        position: "absolute", left: 0, right: 0, bottom: 0, height: 90,
        display: "flex", flexDirection: "column", gap: 4, padding: "6px 12px",
        background: "var(--hl-panel-bg, rgba(10,10,12,0.72))",
        backdropFilter: "blur(var(--hl-panel-blur, 12px))",
        borderTop: "1px solid var(--granite, #333)",
        fontFamily: "var(--hl-font-mono, monospace)", fontSize: 11, color: "#ddd",
      }}
    >
      {/* controls row */}
      <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
        <span style={{ fontWeight: 600, letterSpacing: "0.1em" }}>§ CHRONIK</span>
        <button type="button" aria-label="toggle play" onClick={onTogglePlay}>
          {playing ? "⏸" : "▶"}
        </button>
        <button type="button" aria-label="now" onClick={onNow}>⏭ NOW</button>
        {PRESETS.map((p) => (
          <button
            key={p}
            type="button"
            onClick={() => onPreset(p)}
            style={{ fontWeight: p === preset ? 700 : 400, opacity: p === preset ? 1 : 0.6 }}
          >
            {p}
          </button>
        ))}
        <span style={{ marginLeft: "auto", opacity: 0.85 }}>{cursorLabel}</span>
        <span style={{ opacity: 0.85 }}>{mode === "live" ? "● LIVE" : "▶ REPLAY"}</span>
        <span style={{ opacity: 0.6 }}>located: {geoLocatedCount} / {totalCount}</span>
      </div>

      {/* strip: bars + notable dots + playhead */}
      <div
        ref={stripRef}
        data-testid="chronik-strip"
        role="group"
        aria-label="event density"
        onMouseDown={onMouseDown}
        onMouseUp={onMouseUp}
        style={{ position: "relative", height: STRIP_HEIGHT, cursor: "crosshair" }}
      >
        {buckets.map((b) => {
          const color = EVENT_COLORS[b.dominant_category] ?? DEFAULT_COLOR;
          const h = Math.max(2, (b.count / maxCount) * STRIP_HEIGHT);
          return (
            <div
              key={b.ts}
              data-testid="chronik-bar"
              title={`${b.count} · ${b.dominant_category}`}
              style={{
                position: "absolute", bottom: 0, left: `${msToPct(Date.parse(b.ts))}%`,
                width: 3, height: h, background: color, transform: "translateX(-1px)",
              }}
            />
          );
        })}

        {notables.map((n) => {
          const r = severityRank(n.severity);
          const size = 4 + r * 1.5;
          return (
            <button
              key={n.id}
              type="button"
              title={`${n.time} · ${n.severity}`}
              onClick={() => onSelectNotable(n.id)}
              style={{
                position: "absolute", top: 0, left: `${msToPct(Date.parse(n.time))}%`,
                width: size, height: size, borderRadius: "50%", padding: 0,
                transform: "translateX(-50%)",
                background: r >= 4 ? "#ff5050" : r >= 3 ? "#f59e0b" : "#aaa",
                border: "1px solid rgba(0,0,0,0.6)", cursor: "pointer",
              }}
            >
              <span style={{
                position: "absolute", width: 1, height: 1, overflow: "hidden",
                clip: "rect(0 0 0 0)",
              }}>
                {n.title ?? n.codebook_type ?? n.id}
              </span>
            </button>
          );
        })}

        <div
          aria-label="playhead"
          style={{
            position: "absolute", top: 0, bottom: 0, left: `${msToPct(cursorMs)}%`,
            width: 1, background: "#fff", boxShadow: "0 0 4px rgba(255,255,255,0.6)",
          }}
        />
      </div>
    </section>
  );
}
