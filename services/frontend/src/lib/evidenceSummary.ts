import type { EvidenceSummary } from "../types";

function utc(value: string | null): string {
  if (value === null) return "unbekannt";
  const date = new Date(value);
  return Number.isFinite(date.getTime()) ? date.toISOString() : "unbekannt";
}

export function formatEvidenceSummary(summary: EvidenceSummary[] | null | undefined): string {
  if (summary == null) return "Quellenzeitachsen unbekannt.";
  if (summary.length === 0) return "Keine strukturierten Quellenbelege im Modellprompt.";
  return summary.map(ref => `${ref.provider} · ${ref.source_ref_id} · unverifiziert\n`
    + `Publiziert UTC: ${utc(ref.published_at)}\nBeobachtet UTC: ${utc(ref.observed_at)}\n`
    + `Ingest UTC: ${utc(ref.ingested_at)}`).join("\n\n");
}
