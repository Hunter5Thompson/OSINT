/**
 * Signal envelope shared by /api/signals/latest and /api/signals/stream.
 *
 * Mirrors the backend Pydantic models in services/backend/app/models/signals.py.
 */

export type SignalSeverity = "low" | "medium" | "high" | "critical";

export interface SignalPayload {
  title?: string;
  severity?: SignalSeverity;
  source?: string;
  url?: string;
  redis_id: string;
  [extra: string]: unknown;
}

export interface SignalEnvelope {
  event_id: string;
  ts: string; // ISO 8601 UTC (ends with 'Z')
  type: string; // e.g. "signal.firms"
  payload: SignalPayload;
}
