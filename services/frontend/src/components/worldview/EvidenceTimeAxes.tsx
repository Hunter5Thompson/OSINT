import type { EvidenceSummary } from "../../types";
import { formatEvidenceSummary } from "../../lib/evidenceSummary";

function sourceLink(url: string | null | undefined): string | undefined {
  if (!url) return undefined;
  try {
    const parsed = new URL(url);
    return ["https:", "http:"].includes(parsed.protocol) && !parsed.username && !parsed.password
      ? parsed.href : undefined;
  } catch {
    return undefined;
  }
}

const textStyle = { whiteSpace: "pre-wrap", overflowWrap: "anywhere", font: "inherit" } as const;

export function EvidenceTimeAxes({ summary }: { summary: EvidenceSummary[] | null | undefined }) {
  return <details data-testid="evidence-provenance" style={{ fontSize: ".8rem", lineHeight: 1.6, color: "var(--stone)" }}>
    <summary>Quellen und Zeitachsen</summary>
    {summary?.length ? summary.map((ref, index) => {
      const review = ref.review;
      const passage = ref.passage;
      if (passage) return <details key={ref.evidence_id ?? index} data-testid="notebook-passage"
        style={{ margin: "12px 0", padding: "10px 12px", border: "1px solid currentColor", borderRadius: 3 }}>
        <summary>{ref.knowledge_role === "method" ? "Methode" : "Hintergrund"} · {ref.title}</summary>
        <p>Originalpassage · nicht extern faktengeprüft</p>
        <p style={textStyle}>{ref.excerpt}</p>
        <p><strong>Prüfgrenze: </strong>{passage.qualification_note}</p>
        {ref.knowledge_role === "method" && <p>Analysehilfe; kein Beleg für ein Ereignis.</p>}
        {sourceLink(ref.url) && <a href={sourceLink(ref.url)} target="_blank" rel="noopener noreferrer">Originalquelle öffnen</a>}
        <p>Quellendatum: {passage.source_date_context ?? "unbekannt"}</p>
        {passage.unresolved_checks.length > 0 && <ul>{passage.unresolved_checks.map(check => <li key={check}>{check}</li>)}</ul>}
        <details><summary>Beleg-ID und Textstelle</summary>
          <pre style={textStyle}>{formatEvidenceSummary([ref])}</pre>
        </details>
      </details>;
      if (!review) return <pre key={index} style={textStyle}>{formatEvidenceSummary([ref])}</pre>;
      const titles = [...new Set(review.evidence.map(origin => origin.title).filter(Boolean))];
      return <details key={ref.evidence_id ?? index} data-testid="reviewed-claim"
        style={{ margin: "12px 0", padding: "10px 12px", border: "1px solid currentColor", borderRadius: 3 }}>
        <summary>{review.claim_id} · {titles.join(" / ") || "Aussage aus Notebook-Quelle"}</summary>
        <p>{ref.excerpt}</p>
        <p><strong>Prüfgrenze: </strong>{review.qualification_note || "Keine zusätzliche Einschränkung hinterlegt."}</p>
        <ul style={{ paddingLeft: 18, overflowWrap: "anywhere" }}>
          {review.evidence.length ? review.evidence.map((origin, i) => <li key={`${origin.id}-${i}`}>
            {sourceLink(origin.url)
              ? <a href={sourceLink(origin.url)} target="_blank" rel="noopener noreferrer">{origin.title ?? origin.id}</a>
              : <span>{origin.title ?? origin.id}</span>}
            <div>Herkunft: {origin.independent_lineage ?? "unbekannt"}</div>
            <div>Publikations-/Referenzdatum: {origin.publication_or_reference_date ?? "unbekannt"}</div>
            {origin.analyst_scope && <div>{origin.analyst_scope}</div>}
          </li>) : (review.evidence_urls ?? []).map(url => <li key={url}>
            {sourceLink(url) ? <a href={sourceLink(url)} target="_blank" rel="noopener noreferrer">{url}</a> : url}
            <div>Ursprüngliche Untersuchung nicht weiter aufgeschlüsselt.</div>
          </li>)}
        </ul>
        <details style={{ color: "var(--ash)" }}>
          <summary>Beleg-ID, Textstelle und vollständige Herkunft</summary>
          <pre style={textStyle}>{formatEvidenceSummary([ref])}</pre>
        </details>
      </details>;
    }) : <pre style={textStyle}>{formatEvidenceSummary(summary)}</pre>}
  </details>;
}
