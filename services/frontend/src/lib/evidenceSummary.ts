import type { EvidenceSummary, ResearchCoverage } from "../types";

export function formatUnassessedEvidence(summary: EvidenceSummary[] | null | undefined): string {
  return summary?.length
    ? "Keine Modellbewertung · Quellenangaben vorhanden, nicht extern faktengeprüft."
    : "Keine Modellbewertung · Keine verwendbaren Belege in diesem Recherchelauf.";
}

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
    + `Ingest UTC: ${utc(ref.ingested_at)}`
    + (ref.retrieval ? `\nAbruf UTC: ${utc(ref.retrieval.retrieved_at)}`
      + `\nInhalt: ${ref.retrieval.content_kind === "snippet" ? "Suchauszug" : "Originaltext oder Originalauszug"}`
      + `\nInhalts-Hash: ${ref.retrieval.content_sha256}`
      + `\nHerkunft: ${ref.retrieval.original_lineage} · Unabhängigkeit ungeprüft` : "")
    + (ref.evidence_id && !ref.review && !ref.passage ?
      `\nBeleg-ID: [${ref.evidence_id}]` + (ref.url ? `\nOriginalquelle: ${ref.url}` : "")
      + (ref.excerpt ? `\n${ref.excerpt}` : "") : "") + (ref.review ?
      `\nBeleg-ID: [${ref.evidence_id}]\nAussage: ${ref.excerpt ?? "unbekannt"}`
      + `\nAussage-ID: ${ref.review.candidate_id} · ${ref.review.claim_id}`
      + `\nAblage: Notebook ${ref.review.notebook_id} · Original ${ref.review.original_source_id}`
      + `\nBelegadressen: ${(ref.review.evidence_urls ?? []).join(", ") || "unbekannt"}`
      + `\nAussageart: ${ref.review.epistemic_type}`
      + `\nPrüfgrenze: ${ref.review.qualification_note}`
      + `\nQuellendatum-Kontext: ${ref.review.source_date_context ?? "unbekannt"}`
      + `\nGeprüft: ${ref.review.reviewed_at ?? "unbekannt"}`
      + `\nBelegstelle: ${ref.review.source_anchor?.anchor ?? "unbekannt"}`
      + `\nZeichenposition: ${ref.review.source_anchor?.character_offset ?? "unbekannt"}`
      + ref.review.evidence.map(origin =>
        `\nUrsprünglicher Beleg: ${origin.title ?? origin.id}\n${origin.url ?? "URL unbekannt"}`
        + `\nHerkunft: ${origin.independent_lineage ?? "unbekannt"}`
        + `\nGeltungsbereich: ${origin.analyst_scope ?? "unbekannt"}`
        + `\nPublikations-/Referenzdatum (Originalangabe): ${origin.publication_or_reference_date ?? "unbekannt"}`
        + `\nAbgerufen: ${origin.retrieved_at ?? "unbekannt"}`).join("\n")
      : "") + (ref.passage ?
        `\nBeleg-ID: [${ref.evidence_id}]\nRolle: ${ref.knowledge_role}`
        + `\nOriginalquelle: ${ref.url ?? "unbekannt"}`
        + `\nHerkunft: ${ref.passage.independent_lineage}`
        + `\nZeichenbereich: ${ref.passage.start}–${ref.passage.end}`
        + `\nQuelltext SHA-256: ${ref.passage.text_sha256}`
        + `\nPassage SHA-256: ${ref.passage.passage_sha256}`
        + `\nPrüfgrenze: ${ref.passage.qualification_note}`
        + `\nNicht extern faktengeprüft.\n${ref.excerpt ?? ""}` : "")).join("\n\n");
}


export function formatResearchCoverage(coverage: ResearchCoverage | null | undefined): string {
  if (!coverage) return "";
  return `Recherche-Stand: ${coverage.as_of} · ${coverage.status === "complete" ? "Abrufe abgeschlossen" : "eingeschränkt"}`
    + `\n${coverage.current_evidence_ids.length} datierte Originalbelege im Kontext; Aussagen ungeprüft.`
    + "\nPrognose nicht belastbar bewertet. Szenarien sind bedingte Überlegungen.";
}
