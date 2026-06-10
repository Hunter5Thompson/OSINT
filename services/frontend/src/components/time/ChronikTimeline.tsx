import { useRef, useState } from "react";
import type { HistogramBucket, TimelineNotable } from "../../types";
import { DEFAULT_COLOR, EVENT_COLORS } from "../layers/EventLayer";
import { severityRank } from "../../lib/severity";
import "./ChronikTimeline.css";

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
const PRESETS: Preset[] = ["24h", "7d", "30d"];

function dotColor(rank: number): string {
  if (rank >= 4) return "#c4503a"; // critical
  if (rank >= 3) return "var(--amber, #c4813a)"; // high
  return "var(--stone, #958a7a)";
}

export function ChronikTimeline({
  buckets, notables, rangeStartMs, rangeEndMs, cursorMs, mode, playing, preset,
  geoLocatedCount, totalCount, onSeek, onBrush, onSelectNotable, onTogglePlay, onNow, onPreset,
}: ChronikTimelineProps) {
  const stripRef = useRef<HTMLDivElement | null>(null);
  const dragStartXRef = useRef<number | null>(null);
  const [dragPct, setDragPct] = useState<{ left: number; width: number } | null>(null);

  const span = Math.max(rangeEndMs - rangeStartMs, 1);
  const maxCount = Math.max(1, ...buckets.map((b) => b.count));
  const stripHeightPx = 60;

  const msToPct = (ms: number) => ((ms - rangeStartMs) / span) * 100;
  const xToFrac = (clientX: number) => {
    const rect = stripRef.current?.getBoundingClientRect();
    const left = rect?.left ?? 0;
    const width = rect && rect.width > 0 ? rect.width : 1;
    return Math.min(1, Math.max(0, (clientX - left) / width));
  };
  const xToMs = (clientX: number) => rangeStartMs + xToFrac(clientX) * span;

  const onMouseDown = (e: React.MouseEvent) => {
    dragStartXRef.current = e.clientX;
    setDragPct(null);
  };
  const onMouseMove = (e: React.MouseEvent) => {
    const startX = dragStartXRef.current;
    if (startX == null || Math.abs(e.clientX - startX) < DRAG_THRESHOLD_PX) return;
    const a = xToFrac(startX) * 100;
    const b = xToFrac(e.clientX) * 100;
    setDragPct({ left: Math.min(a, b), width: Math.abs(b - a) }); // visual brush preview
  };
  const onMouseUp = (e: React.MouseEvent) => {
    const startX = dragStartXRef.current;
    dragStartXRef.current = null;
    setDragPct(null);
    if (startX == null) return;
    if (Math.abs(e.clientX - startX) >= DRAG_THRESHOLD_PX) {
      const a = xToMs(startX);
      const b = xToMs(e.clientX);
      onBrush(Math.min(a, b), Math.max(a, b)); // drag = brush
    } else {
      onSeek(xToMs(e.clientX)); // click = seek
    }
  };
  const onMouseLeave = () => {
    dragStartXRef.current = null;
    setDragPct(null);
  };

  const cursorLabel = Number.isFinite(cursorMs)
    ? `${new Date(cursorMs).toISOString().replace("T", " ").slice(0, 19)}Z`
    : "--";

  return (
    <section className="chronik" aria-label="chronik timeline">
      <div className="chronik__controls">
        <span className="chronik__mark"><b>§</b> CHRONIK</span>
        <button type="button" className="chronik__btn" aria-label="toggle play" onClick={onTogglePlay}>
          {playing ? "⏸" : "▶"}
        </button>
        <button type="button" className="chronik__btn" aria-label="now" onClick={onNow}>⏭ NOW</button>
        {PRESETS.map((p) => (
          <button
            key={p}
            type="button"
            className={`chronik__btn${p === preset ? " chronik__btn--on" : ""}`}
            onClick={() => onPreset(p)}
          >
            {p}
          </button>
        ))}
        <span className="chronik__cursor chronik__spacer">{cursorLabel}</span>
        <span className={mode === "live" ? "chronik__badge--live" : "chronik__badge--replay"}>
          {mode === "live" ? "● LIVE" : "▶ REPLAY"}
        </span>
        <span className="chronik__located">located: {geoLocatedCount} / {totalCount}</span>
      </div>

      <div
        ref={stripRef}
        data-testid="chronik-strip"
        role="group"
        aria-label="event density"
        className="chronik__strip"
        onMouseDown={onMouseDown}
        onMouseMove={onMouseMove}
        onMouseUp={onMouseUp}
        onMouseLeave={onMouseLeave}
      >
        {buckets.map((b) => (
          <div
            key={b.ts}
            data-testid="chronik-bar"
            className="chronik__bar"
            title={`${b.count} · ${b.dominant_category}`}
            style={{
              left: `${msToPct(Date.parse(b.ts))}%`,
              height: Math.max(2, (b.count / maxCount) * stripHeightPx),
              background: EVENT_COLORS[b.dominant_category] ?? DEFAULT_COLOR,
            }}
          />
        ))}

        {notables.map((n) => {
          const r = severityRank(n.severity);
          const size = 4 + r * 1.5;
          return (
            <button
              key={n.id}
              type="button"
              className="chronik__dot"
              title={`${n.time} · ${n.severity}`}
              onClick={() => onSelectNotable(n.id)}
              style={{
                left: `${msToPct(Date.parse(n.time))}%`,
                width: size,
                height: size,
                background: dotColor(r),
              }}
            >
              <span className="chronik__sr">{n.title ?? n.codebook_type ?? n.id}</span>
            </button>
          );
        })}

        {dragPct ? (
          <div className="chronik__brush" style={{ left: `${dragPct.left}%`, width: `${dragPct.width}%` }} />
        ) : null}

        <div className="chronik__playhead" aria-label="playhead" style={{ left: `${msToPct(cursorMs)}%` }} />
      </div>
    </section>
  );
}
