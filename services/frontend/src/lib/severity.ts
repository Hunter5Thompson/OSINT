// Mirror of services/backend/app/services/severity.py — keep in lockstep.
export const SEVERITY_ORDER = ["unknown", "low", "medium", "high", "critical"] as const;
export type Severity = (typeof SEVERITY_ORDER)[number];

const MAP: Record<string, Severity> = {
  low: "low",
  warning: "low",
  moderate: "medium",
  medium: "medium",
  elevated: "high",
  high: "high",
  critical: "critical",
  severe: "critical",
  extreme: "critical",
};

export function normalizeSeverity(raw: unknown): Severity {
  if (typeof raw !== "string") return "unknown";
  return MAP[raw.trim().toLowerCase()] ?? "unknown";
}

export function severityRank(raw: unknown): number {
  const v =
    typeof raw === "string" && (SEVERITY_ORDER as readonly string[]).includes(raw)
      ? (raw as Severity)
      : normalizeSeverity(raw);
  return SEVERITY_ORDER.indexOf(v);
}
