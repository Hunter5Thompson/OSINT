/**
 * useSignalFeed — live signal stream hook for the Landing page (§4.1).
 *
 * Subscribes to `/api/signals/stream` (SSE) and hydrates from
 * `/api/signals/latest?limit=6` on mount. Exposes:
 *   - `status`: "idle" | "live" | "reconnecting" | "down"
 *   - `items`: newest-first, capped at 6 envelopes
 *   - `lastEventId`: highest event_id observed so far
 *
 * Design:
 *  - Native `EventSource` (or injected mock in tests) — the browser auto-sends
 *    `Last-Event-ID` on reconnect based on the last received `id:` frame, so
 *    we don't manage that header ourselves. As a belt-and-suspenders fallback
 *    we also append `?last_event_id=<id>` on explicit reconnect attempts.
 *  - Dedupe via a `Set<event_id>` capped at `DEDUPE_CAP` (oldest evicted).
 *  - `event: reset` frames clear the dedupe set, re-fetch the latest window,
 *    and replace `items` with the fresh snapshot.
 *  - Reconnect is explicit (we close on error and schedule a new EventSource)
 *    with exponential backoff 1s → 2s → 4s → 8s → 16s → 30s (cap).
 *  - Unmount always closes the active EventSource and cancels any timer.
 *  - React 19 Strict-Mode safe: we use a per-effect `cancelled` flag closed
 *    over by the async hydration + inner `connect()`. No module-scoped or
 *    ref-based "mounted" flag that could leak across Strict-Mode re-mounts.
 */
import { useEffect, useRef, useState } from "react";
import { SIGNAL_STREAM_URL, getLatestSignals } from "../services/api";
import type { SignalEnvelope } from "../types/signals";

export type SignalFeedStatus = "idle" | "live" | "reconnecting" | "down";

export interface UseSignalFeedResult {
  status: SignalFeedStatus;
  items: SignalEnvelope[];
  lastEventId: string | null;
}

const FEED_CAP = 6;
const DEDUPE_CAP = 500;
const BACKOFF_MS = [1000, 2000, 4000, 8000, 16000, 30000];

type BrowserEventSource = typeof window extends { EventSource: infer T } ? T : never;

function getEventSourceCtor(): (new (url: string) => EventSource) | null {
  const ctor =
    (typeof globalThis !== "undefined" &&
      (globalThis as unknown as { EventSource?: BrowserEventSource }).EventSource) ||
    null;
  return (ctor as unknown as new (url: string) => EventSource) || null;
}

function buildStreamUrl(lastEventId: string | null): string {
  if (!lastEventId) return SIGNAL_STREAM_URL;
  const sep = SIGNAL_STREAM_URL.includes("?") ? "&" : "?";
  return `${SIGNAL_STREAM_URL}${sep}last_event_id=${encodeURIComponent(lastEventId)}`;
}

export function useSignalFeed(): UseSignalFeedResult {
  const [status, setStatus] = useState<SignalFeedStatus>("idle");
  const [items, setItems] = useState<SignalEnvelope[]>([]);
  const [lastEventId, setLastEventId] = useState<string | null>(null);

  // Mutable refs to avoid re-subscribing on every render.
  const esRef = useRef<EventSource | null>(null);
  const dedupeRef = useRef<Set<string>>(new Set());
  const dedupeOrderRef = useRef<string[]>([]);
  const attemptRef = useRef(0);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const lastEventIdRef = useRef<string | null>(null);

  // Keep the ref in sync with the state so reconnect handlers see the latest.
  useEffect(() => {
    lastEventIdRef.current = lastEventId;
  }, [lastEventId]);

  useEffect(() => {
    // Per-effect local flag — survives Strict-Mode double-invocation because
    // each invocation captures its own `cancelled`. The cleanup of the first
    // mount flips its copy to `true`; the remount starts fresh.
    let cancelled = false;
    attemptRef.current = 0;
    setStatus("idle");

    // Lazy named-listener registry. Types registered here forward their SSE
    // frames to `handleEnvelope`, same as the generic onmessage wildcard.
    const seenTypes = new Set<string>();
    const registerNamed = (type: string) => {
      if (seenTypes.has(type)) return;
      seenTypes.add(type);
      esRef.current?.addEventListener(type, ((ev: Event) => {
        if (cancelled) return;
        const msg = ev as MessageEvent<string>;
        handleEnvelope(msg.data, (msg.lastEventId ?? "") as string);
      }) as EventListener);
    };
    const onRegister = (ev: Event) => {
      const custom = ev as CustomEvent<{ type?: string }>;
      if (custom.detail?.type) registerNamed(custom.detail.type);
    };
    window.addEventListener("signal-feed:register", onRegister as EventListener);

    function rememberSeen(id: string) {
      if (dedupeRef.current.has(id)) return false;
      dedupeRef.current.add(id);
      dedupeOrderRef.current.push(id);
      if (dedupeOrderRef.current.length > DEDUPE_CAP) {
        const oldest = dedupeOrderRef.current.shift();
        if (oldest !== undefined) dedupeRef.current.delete(oldest);
      }
      return true;
    }

    function seedFromLatest(envelopes: SignalEnvelope[]) {
      // Assume server returns newest-first; take up to FEED_CAP.
      const trimmed = envelopes.slice(0, FEED_CAP);
      dedupeRef.current = new Set();
      dedupeOrderRef.current = [];
      for (const env of trimmed) rememberSeen(env.event_id);
      setItems(trimmed);
      const first = trimmed[0];
      if (first) {
        setLastEventId(first.event_id);
        lastEventIdRef.current = first.event_id;
      }
    }

    function handleEnvelope(raw: string, fallbackId: string) {
      let env: SignalEnvelope;
      try {
        env = JSON.parse(raw) as SignalEnvelope;
      } catch {
        return;
      }
      const id = env.event_id || fallbackId;
      if (!id) return;
      if (!rememberSeen(id)) return;
      setItems((prev) => {
        const next = [env, ...prev];
        if (next.length > FEED_CAP) next.length = FEED_CAP;
        return next;
      });
      setLastEventId((prev) => {
        const nextId = prev === null || id > prev ? id : prev;
        lastEventIdRef.current = nextId;
        return nextId;
      });
    }

    async function handleReset() {
      dedupeRef.current = new Set();
      dedupeOrderRef.current = [];
      try {
        const fresh = await getLatestSignals(FEED_CAP);
        if (cancelled) return;
        seedFromLatest(fresh);
      } catch {
        // Keep items as-is on refetch failure.
      }
    }

    function connect() {
      if (cancelled) return;
      const Ctor = getEventSourceCtor();
      if (!Ctor) {
        setStatus("down");
        return;
      }
      const es = new Ctor(buildStreamUrl(lastEventIdRef.current));
      esRef.current = es;

      es.onopen = () => {
        if (cancelled) return;
        attemptRef.current = 0;
        setStatus("live");
      };

      es.onmessage = (ev: MessageEvent) => {
        if (cancelled) return;
        handleEnvelope(ev.data, ev.lastEventId ?? "");
      };

      // Named events — any codebook_type is accepted. Seed with the S1 list for
      // back-compat, but allow late registration via a `signal-feed:register`
      // window event so new taxonomy types (military.*, other.*, …) can opt into
      // the named-event channel without touching this file.
      const SIGNAL_EVENT_TYPES = [
        "signal.firms",
        "signal.ucdp",
        "signal.gdelt",
        "signal.tle",
        "signal.eonet",
        "signal.gdacs",
        "signal.unknown",
      ];
      for (const type of SIGNAL_EVENT_TYPES) {
        es.addEventListener(type, ((ev: Event) => {
          if (cancelled) return;
          const msg = ev as MessageEvent<string>;
          handleEnvelope(msg.data, (msg.lastEventId ?? "") as string);
        }) as EventListener);
        seenTypes.add(type);
      }

      es.addEventListener("reset", (() => {
        if (cancelled) return;
        void handleReset();
      }) as EventListener);

      es.onerror = () => {
        if (cancelled) return;
        // Close the broken connection and schedule a reconnect.
        try {
          es.close();
        } catch {
          // ignore
        }
        if (esRef.current === es) esRef.current = null;
        setStatus("reconnecting");
        // Guard: if `onerror` fires twice before the pending timer runs,
        // we must not stack multiple timers.
        if (reconnectTimerRef.current !== null) {
          clearTimeout(reconnectTimerRef.current);
          reconnectTimerRef.current = null;
        }
        const delay =
          BACKOFF_MS[Math.min(attemptRef.current, BACKOFF_MS.length - 1)];
        attemptRef.current += 1;
        reconnectTimerRef.current = setTimeout(() => {
          reconnectTimerRef.current = null;
          if (cancelled) return;
          connect();
        }, delay);
      };
    }

    // Hydrate, then connect. Connecting only after hydration resolves avoids
    // a Strict-Mode race where the first-mount's `.finally` would open an
    // EventSource owned by an already-cleaned-up effect.
    const hydrate = async () => {
      try {
        const fresh = await getLatestSignals(FEED_CAP);
        if (cancelled) return;
        seedFromLatest(fresh);
      } catch {
        // Leave items empty on hydration failure; the stream still gets a chance.
      }
      if (cancelled) return;
      connect();
    };
    void hydrate();

    return () => {
      cancelled = true;
      if (reconnectTimerRef.current !== null) {
        clearTimeout(reconnectTimerRef.current);
        reconnectTimerRef.current = null;
      }
      if (esRef.current !== null) {
        try {
          esRef.current.close();
        } catch {
          // ignore
        }
        esRef.current = null;
      }
      window.removeEventListener("signal-feed:register", onRegister as EventListener);
      seenTypes.clear();
    };
    // Intentionally run-once: the hook owns the lifecycle internally.
  }, []);

  return { status, items, lastEventId };
}
