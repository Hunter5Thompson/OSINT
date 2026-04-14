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
  const mountedRef = useRef(true);
  const lastEventIdRef = useRef<string | null>(null);

  // Keep the ref in sync with the state so reconnect handlers see the latest.
  useEffect(() => {
    lastEventIdRef.current = lastEventId;
  }, [lastEventId]);

  useEffect(() => {
    mountedRef.current = true;

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
        if (!mountedRef.current) return;
        seedFromLatest(fresh);
      } catch {
        // Keep items as-is on refetch failure.
      }
    }

    function connect() {
      const Ctor = getEventSourceCtor();
      if (!Ctor) {
        setStatus("down");
        return;
      }
      const es = new Ctor(buildStreamUrl(lastEventIdRef.current));
      esRef.current = es;

      es.onopen = () => {
        if (!mountedRef.current) return;
        attemptRef.current = 0;
        setStatus("live");
      };

      es.onmessage = (ev: MessageEvent) => {
        handleEnvelope(ev.data, ev.lastEventId ?? "");
      };

      // Named events — we don't know the full type set ahead of time, so we
      // catch-all via addEventListener for the known ones and a wildcard via
      // the underlying EventTarget for any `signal.*` type. EventSource doesn't
      // support wildcards natively; instead we rely on `onmessage` for unnamed
      // frames and addEventListener for the ones the backend is known to emit.
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
        es.addEventListener(type, ((ev: MessageEvent) => {
          handleEnvelope(ev.data, ev.lastEventId ?? "");
        }) as EventListener);
      }

      es.addEventListener("reset", (() => {
        void handleReset();
      }) as EventListener);

      es.onerror = () => {
        if (!mountedRef.current) return;
        // Close the broken connection and schedule a reconnect.
        try {
          es.close();
        } catch {
          // ignore
        }
        if (esRef.current === es) esRef.current = null;
        setStatus("reconnecting");
        const delay =
          BACKOFF_MS[Math.min(attemptRef.current, BACKOFF_MS.length - 1)];
        attemptRef.current += 1;
        reconnectTimerRef.current = setTimeout(() => {
          reconnectTimerRef.current = null;
          if (!mountedRef.current) return;
          connect();
        }, delay);
      };
    }

    // Hydrate then connect. We kick off both in parallel; the EventSource will
    // dedupe against the hydrated IDs once it delivers live events.
    void getLatestSignals(FEED_CAP)
      .then((fresh) => {
        if (!mountedRef.current) return;
        seedFromLatest(fresh);
      })
      .catch(() => {
        // Leave items empty on hydration failure; the stream still gets a chance.
      })
      .finally(() => {
        if (!mountedRef.current) return;
        connect();
      });

    return () => {
      mountedRef.current = false;
      if (reconnectTimerRef.current !== null) {
        clearTimeout(reconnectTimerRef.current);
        reconnectTimerRef.current = null;
      }
      if (esRef.current) {
        try {
          esRef.current.close();
        } catch {
          // ignore
        }
        esRef.current = null;
      }
    };
    // Intentionally run-once: the hook owns the lifecycle internally.
  }, []);

  return { status, items, lastEventId };
}
