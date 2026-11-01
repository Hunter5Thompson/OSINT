import type { EvidenceSummary } from "../../types";
import { formatEvidenceSummary } from "../../lib/evidenceSummary";

export function EvidenceTimeAxes({ summary }: { summary: EvidenceSummary[] | null | undefined }) {
  return <details style={{ fontSize: ".75rem", color: "var(--stone)" }}>
    <summary>Quellen und Zeitachsen</summary>
    <pre style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere", font: "inherit" }}>{formatEvidenceSummary(summary)}</pre>
  </details>;
}
