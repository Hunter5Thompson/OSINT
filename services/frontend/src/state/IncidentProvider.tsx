/**
 * IncidentProvider — single SSE subscription for /api/incidents/stream.
 *
 * Mirrors useSignalFeed semantics (hydrate REST → connect SSE → reconnect
 * with backoff → dedupe via event_id → handle named `reset` events). All
 * consumers read from one shared context so multiple widgets (toast,
 * pulsing tab dot, WarRoomPage) don't open duplicate connections.
 */
import {
  createContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";

import {
  INCIDENT_STREAM_URL,
  getIncidents,
} from "../services/api";
import type {
  Incident,
  IncidentEnvelope,
  IncidentEnvelopeType,
} from "../types/incident";

export type IncidentsStatus = "idle" | "live" | "reconnecting" | "down";

export interface IncidentContextValue {
  status: IncidentsStatus;
  active: Incident | null;
  history: Incident[];
  latestEnvelope: IncidentEnvelope | null;
}

const HISTORY_CAP = 10;
const DEDUPE_CAP = 200;
const BACKOFF_MS = [1000, 2000, 4000, 8000, 16000, 30000];
const STREAM_TYPES: IncidentEnvelopeType[] = [
  "incident.open",
  "incident.update",
  "incident.silence",
  "incident.promote",
  "incident.close",
];

const DEFAULT_VALUE: IncidentContextValue = {
  status: "idle",
  active: null,
  history: [],
  latestEnvelope: null,
};

export const IncidentContext = createContext<IncidentContextValue>(DEFAULT_VALUE);

function buildUrl(lastId: string | null): string {
  if (!lastId) return INCIDENT_STREAM_URL;
  const sep = INCIDENT_STREAM_URL.includes("?") ? "&" : "?";
  return `${INCIDENT_STREAM_URL}${sep}last_event_id=${encodeURIComponent(lastId)}`;
}

export function IncidentProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<IncidentsStatus>("idle");
  const [active, setActive] = useState<Incident | null>(null);
  const [history, setHistory] = useState<Incident[]>([]);
  const [latestEnvelope, setLatestEnvelope] = useState<IncidentEnvelope | null>(null);

  const esRef = useRef<EventSource | null>(null);
  const seenRef = useRef<Set<string>>(new Set());
  const seenOrderRef = useRef<string[]>([]);
  const lastIdRef = useRef<string | null>(null);
  const attemptRef = useRef(0);
  const reconnectRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    let cancelled = false;
    attemptRef.current = 0;
    setStatus("idle");

    function remember(id: string): boolean {
      if (seenRef.current.has(id)) return false;
      seenRef.current.add(id);
      seenOrderRef.current.push(id);
      if (seenOrderRef.current.length > DEDUPE_CAP) {
        const oldest = seenOrderRef.current.shift();
        if (oldest !== undefined) seenRef.current.delete(oldest);
      }
      return true;
    }

    function applyEnvelope(env: IncidentEnvelope) {
      const incident = env.payload;
      if (env.type === "incident.open" || env.type === "incident.update") {
        setActive(incident);
      } else {
        setActive((prev) => (prev?.id === incident.id ? null : prev));
      }
      setHistory((prev) => {
        const filtered = prev.filter((i) => i.id !== incident.id);
        return [incident, ...filtered].slice(0, HISTORY_CAP);
      });
      setLatestEnvelope(env);
    }

    function handleData(raw: string, fallbackId: string) {
      let env: IncidentEnvelope;
      try {
        env = JSON.parse(raw) as IncidentEnvelope;
      } catch {
        return;
      }
      const id = env.event_id || fallbackId;
      if (!id || !remember(id)) return;
      lastIdRef.current =
        lastIdRef.current && id <= lastIdRef.current ? lastIdRef.current : id;
      applyEnvelope(env);
    }

    async function rehydrate(reason: string) {
      seenRef.current = new Set();
      seenOrderRef.current = [];
      lastIdRef.current = null;
      try {
        const fresh = await getIncidents();
        if (cancelled) return;
        const open = fresh.find((i) => i.status === "open") ?? null;
        setActive(open);
        setHistory(fresh.slice(0, HISTORY_CAP));
        setLatestEnvelope(null);
      } catch {
        void reason;
      }
    }

    async function hydrate() {
      try {
        const open = await getIncidents();
        if (cancelled) return;
        const newest = open[0] ?? null;
        if (newest && newest.status === "open") setActive(newest);
        setHistory(open.slice(0, HISTORY_CAP));
      } catch {
        // soft-fail: stream will populate
      }
      if (!cancelled) connect();
    }

    function connect() {
      if (cancelled) return;
      const Ctor =
        (globalThis as unknown as { EventSource?: new (u: string) => EventSource })
          .EventSource;
      if (!Ctor) {
        setStatus("down");
        return;
      }
      const es = new Ctor(buildUrl(lastIdRef.current));
      esRef.current = es;

      es.onopen = () => {
        if (cancelled) return;
        attemptRef.current = 0;
        setStatus("live");
      };
      es.onmessage = (ev) => {
        if (cancelled) return;
        handleData(ev.data, ev.lastEventId ?? "");
      };
      for (const type of STREAM_TYPES) {
        es.addEventListener(type, ((ev: Event) => {
          if (cancelled) return;
          const msg = ev as MessageEvent<string>;
          handleData(msg.data, (msg.lastEventId ?? "") as string);
        }) as EventListener);
      }
      es.addEventListener("reset", (() => {
        if (cancelled) return;
        void rehydrate("server-reset");
      }) as EventListener);
      es.onerror = () => {
        if (cancelled) return;
        try { es.close(); } catch { /* ignore */ }
        if (esRef.current === es) esRef.current = null;
        setStatus("reconnecting");
        if (reconnectRef.current !== null) {
          clearTimeout(reconnectRef.current);
          reconnectRef.current = null;
        }
        const delay = BACKOFF_MS[Math.min(attemptRef.current, BACKOFF_MS.length - 1)];
        attemptRef.current += 1;
        reconnectRef.current = setTimeout(() => {
          reconnectRef.current = null;
          if (!cancelled) connect();
        }, delay);
      };
    }

    void hydrate();

    return () => {
      cancelled = true;
      if (reconnectRef.current !== null) {
        clearTimeout(reconnectRef.current);
        reconnectRef.current = null;
      }
      if (esRef.current !== null) {
        try { esRef.current.close(); } catch { /* ignore */ }
        esRef.current = null;
      }
    };
  }, []);

  return (
    <IncidentContext.Provider
      value={{ status, active, history, latestEnvelope }}
    >
      {children}
    </IncidentContext.Provider>
  );
}
