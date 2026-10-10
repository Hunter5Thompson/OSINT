import type { EvidenceSummary } from "../../types";
import { formatEvidenceSummary } from "../../lib/evidenceSummary";

export function EvidenceTimeAxes({ summary }: { summary: EvidenceSummary[] | null | undefined }) {
  return <details style={{ fontSize: ".72rem", color: "var(--ash)" }}>
    <summary>Quellen und Zeitachsen</summary>
    <pre style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere", font: "inherit" }}>{formatEvidenceSummary(summary)}</pre>
  </details>;
}
