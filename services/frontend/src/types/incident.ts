export type IncidentSeverity = "low" | "elevated" | "high" | "critical";
export type IncidentStatus = "open" | "silenced" | "promoted" | "closed";

export interface IncidentTimelineEvent {
  t_offset_s: number;
  kind: "trigger" | "signal" | "agent" | "source" | "note" | string;
  text: string;
  severity?: IncidentSeverity | null;
}

export interface Incident {
  id: string;
  kind: string;
  title: string;
  severity: IncidentSeverity;
  coords: [number, number]; // [lat, lon]
  location: string;
  status: IncidentStatus;
  trigger_ts: string;
  closed_ts: string | null;
  sources: string[];
  layer_hints: string[];
  timeline: IncidentTimelineEvent[];
}

export type IncidentEnvelopeType =
  | "incident.open"
  | "incident.update"
  | "incident.silence"
  | "incident.promote"
  | "incident.close";

export interface IncidentEnvelope {
  event_id: string;
  ts: string;
  type: IncidentEnvelopeType;
  payload: Incident;
}

export interface IncidentCreateRequest {
  title: string;
  kind: string;
  severity: IncidentSeverity;
  coords: [number, number];
  location?: string;
  sources?: string[];
  layer_hints?: string[];
  initial_text?: string;
}
