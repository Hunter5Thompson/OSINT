/**
 * Orrery — Hlíðskjalf brand signature (ODIN S1 · Task 3).
 *
 * Three elliptical orbits (Munin / Hugin / Sentinel) around an Amber kernel.
 * Physics per spec §2.5:
 *   θᵢ = ωᵢ·t + φᵢ
 *   (x₀, y₀) = (rx·cos θ, ry·sin θ)
 *   (x, y)   = rotate(x₀, y₀, tilt)   — ellipse rotated by tilt
 *   depth    = (sin θ + 1) / 2
 *   opacity  = 0.35 + depth·0.65
 *   scale    = 0.7  + depth·0.5
 *
 * Bodies pulse *independently* (different φ offsets) so no two stars peak
 * simultaneously. Rendering is pure SVG + `requestAnimationFrame`; a single
 * module-level engine multiplexes all mounted Orreries through one rAF loop.
 *
 * Reduced-motion: when `prefers-reduced-motion: reduce` matches, OR an
 * ancestor has `[data-reduced-motion="true"]`, the Orrery renders statically
 * at θ=π/3 and never schedules a frame.
 */
import { useEffect, useRef, useState, type CSSProperties } from "react";

// ── Pure physics ──────────────────────────────────────────────────────────

export interface BodyPosition {
  x: number;
  y: number;
  opacity: number;
  scale: number;
}

export function computeBodyPosition(
  rx: number,
  ry: number,
  tilt: number,
  omega: number,
  phi: number,
  t: number,
): BodyPosition {
  const theta = omega * t + phi;
  const x0 = rx * Math.cos(theta);
  const y0 = ry * Math.sin(theta);
  const ct = Math.cos(tilt);
  const st = Math.sin(tilt);
  const x = x0 * ct - y0 * st;
  const y = x0 * st + y0 * ct;
  const depth = (Math.sin(theta) + 1) / 2;
  const opacity = 0.35 + depth * 0.65;
  const scale = 0.7 + depth * 0.5;
  return { x, y, opacity, scale };
}

// ── Body specs ────────────────────────────────────────────────────────────

export type BodyName = "munin" | "hugin" | "sentinel";

export interface BodySpec {
  name: BodyName;
  rx: number;
  ry: number;
  tilt: number; // radians
  omega: number;
  phi: number;
  color: string; // CSS var reference
}

const deg = (d: number) => (d * Math.PI) / 180;

export const BODIES: readonly BodySpec[] = [
  { name: "munin",    rx: 50, ry: 18, tilt: deg(-12), omega:  0.35, phi: 0,   color: "var(--amber)" },
  { name: "hugin",    rx: 38, ry: 14, tilt: deg( 25), omega: -0.52, phi: 2.1, color: "var(--sage)" },
  { name: "sentinel", rx: 26, ry: 10, tilt: deg( -4), omega:  0.78, phi: 4.2, color: "var(--sentinel)" },
] as const;

// ── rAF engine (module-level singleton) ───────────────────────────────────

type Subscriber = (t: number) => void;

function createEngine() {
  const subscribers = new Set<Subscriber>();
  let rafId: number | null = null;
  let startMs: number | null = null;

  const tick = (now: number) => {
    if (startMs === null) startMs = now;
    const t = (now - startMs) / 1000;
    for (const cb of subscribers) cb(t);
    rafId = window.requestAnimationFrame(tick);
  };

  function subscribe(cb: Subscriber): () => void {
    subscribers.add(cb);
    if (rafId === null) {
      rafId = window.requestAnimationFrame(tick);
    }
    return () => {
      subscribers.delete(cb);
      if (subscribers.size === 0 && rafId !== null) {
        window.cancelAnimationFrame(rafId);
        rafId = null;
        startMs = null;
      }
    };
  }

  function reset() {
    if (rafId !== null) {
      window.cancelAnimationFrame(rafId);
    }
    subscribers.clear();
    rafId = null;
    startMs = null;
  }

  function subscriberCount() {
    return subscribers.size;
  }

  function isRunning() {
    return rafId !== null;
  }

  return { subscribe, reset, subscriberCount, isRunning };
}

/** Exposed for tests only — do not use in production code. */
export const __orreryEngine = createEngine();

// ── Reduced-motion detection ──────────────────────────────────────────────

function detectReducedMotion(el: Element | null): boolean {
  if (typeof window !== "undefined" && typeof window.matchMedia === "function") {
    try {
      if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return true;
    } catch {
      // matchMedia not available — ignore
    }
  }
  // Ancestor traversal from the (possibly not-yet-mounted) ref target.
  let cur: Element | null = el;
  while (cur) {
    if (cur.getAttribute && cur.getAttribute("data-reduced-motion") === "true") return true;
    cur = cur.parentElement;
  }
  // Fallback: check document root (tests set this attribute on documentElement).
  if (typeof document !== "undefined" && document.documentElement.getAttribute("data-reduced-motion") === "true") {
    return true;
  }
  return false;
}

// ── Component ─────────────────────────────────────────────────────────────

const SIZE_PX: Record<"s" | "m" | "l", number> = { s: 40, m: 110, l: 220 };
const STATIC_THETA = Math.PI / 3;
const KERNEL_R = 4;
const BODY_BASE_R = 2; // at scale=1 → 2px radius; scaled per body

export interface OrreryProps {
  size?: "s" | "m" | "l";
  className?: string;
  style?: CSSProperties;
  /** If set, override auto-detected reduced-motion. For tests / docs. */
  reducedMotion?: boolean;
}

interface Frame {
  munin: BodyPosition;
  hugin: BodyPosition;
  sentinel: BodyPosition;
}

function computeFrame(t: number): Frame {
  const frame = {} as Frame;
  for (const b of BODIES) {
    frame[b.name] = computeBodyPosition(b.rx, b.ry, b.tilt, b.omega, b.phi, t);
  }
  return frame;
}

function staticFrame(): Frame {
  const frame = {} as Frame;
  for (const b of BODIES) {
    // Force θ = π/3 regardless of omega/phi — deterministic constellation.
    // Achieve by passing (omega=1, phi=π/3, t=0).
    frame[b.name] = computeBodyPosition(b.rx, b.ry, b.tilt, 1, STATIC_THETA, 0);
  }
  return frame;
}

export function Orrery({ size = "m", className, style, reducedMotion }: OrreryProps) {
  const rootRef = useRef<SVGSVGElement | null>(null);
  const [reduced, setReduced] = useState<boolean>(() =>
    reducedMotion ?? detectReducedMotion(null),
  );
  const [frame, setFrame] = useState<Frame>(() => staticFrame());

  // Post-mount refine + subscribe to runtime reduced-motion toggles.
  useEffect(() => {
    if (reducedMotion !== undefined) {
      setReduced(reducedMotion);
      return;
    }

    const sync = () => {
      setReduced((prev) => {
        const detected = detectReducedMotion(rootRef.current);
        return detected !== prev ? detected : prev;
      });
    };

    // Initial post-mount re-evaluation (ancestor chain now available).
    sync();

    // 1) matchMedia change listener — OS-level prefers-reduced-motion toggles.
    let mql: MediaQueryList | null = null;
    const mqlHandler = () => sync();
    if (typeof window !== "undefined" && typeof window.matchMedia === "function") {
      try {
        mql = window.matchMedia("(prefers-reduced-motion: reduce)");
        if (typeof mql.addEventListener === "function") {
          mql.addEventListener("change", mqlHandler);
        } else if (typeof (mql as MediaQueryList).addListener === "function") {
          // Legacy Safari fallback.
          (mql as MediaQueryList).addListener(mqlHandler);
        }
      } catch {
        mql = null;
      }
    }

    // 2) MutationObserver — watch for [data-reduced-motion] attribute changes
    //    anywhere in the document tree (ancestors or documentElement).
    let observer: MutationObserver | null = null;
    if (typeof document !== "undefined" && typeof MutationObserver !== "undefined") {
      observer = new MutationObserver(() => sync());
      observer.observe(document.documentElement, {
        attributes: true,
        subtree: true,
        attributeFilter: ["data-reduced-motion"],
      });
    }

    return () => {
      if (mql) {
        if (typeof mql.removeEventListener === "function") {
          mql.removeEventListener("change", mqlHandler);
        } else if (typeof (mql as MediaQueryList).removeListener === "function") {
          (mql as MediaQueryList).removeListener(mqlHandler);
        }
      }
      if (observer) observer.disconnect();
    };
  }, [reducedMotion]);

  // Subscribe to the shared rAF engine unless reduced-motion.
  useEffect(() => {
    if (reduced) {
      setFrame(staticFrame());
      return;
    }
    const unsub = __orreryEngine.subscribe((t) => {
      setFrame(computeFrame(t));
    });
    return unsub;
  }, [reduced]);

  const px = SIZE_PX[size];

  return (
    <svg
      ref={rootRef}
      xmlns="http://www.w3.org/2000/svg"
      viewBox="-60 -60 120 120"
      width={px}
      height={px}
      data-orrery="true"
      data-reduced={reduced ? "true" : undefined}
      aria-hidden="true"
      className={className}
      style={style}
    >
      <circle
        data-part="kernel"
        cx={0}
        cy={0}
        r={KERNEL_R}
        fill="var(--amber)"
      />
      {BODIES.map((b) => (
        <ellipse
          key={`orbit-${b.name}`}
          data-part="orbit"
          data-body={b.name}
          cx={0}
          cy={0}
          rx={b.rx}
          ry={b.ry}
          fill="none"
          stroke="var(--granite)"
          strokeWidth={0.5}
          transform={`rotate(${(b.tilt * 180) / Math.PI})`}
        />
      ))}
      {BODIES.map((b) => {
        const p = frame[b.name];
        return (
          <circle
            key={`body-${b.name}`}
            data-body={b.name}
            cx={p.x}
            cy={p.y}
            r={BODY_BASE_R * p.scale}
            fill={b.color}
            opacity={p.opacity}
          />
        );
      })}
    </svg>
  );
}
