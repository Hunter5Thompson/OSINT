import { expect, it } from "vitest";
import { formatEvidenceSummary } from "./evidenceSummary";
import payloads from "../../../../tests/fixtures/reviewed-claims-47.json";
import type { EvidenceSummary } from "../types";

it.each(payloads)("shows original source, qualification and exact dates for $review.candidate_id", p => {
  const row = { source_ref_id: "parent", evidence_id: p.review.candidate_id,
    provider: p.provider, source_type: "notebooklm", published_at: null, observed_at: null,
    ingested_at: p.ingested_at, verification_status: "unverified", review: p.review } as EvidenceSummary;
  const text = formatEvidenceSummary([row]);
  expect(text).toContain(p.review.candidate_id);
  expect(text).toContain(p.review.qualification_note);
  for (const source of p.review.evidence) {
    expect(text).toContain(source.url);
    expect(text).toContain(source.independent_lineage);
    if (source.publication_or_reference_date) expect(text).toContain(source.publication_or_reference_date);
  }
});

it("shows the citation identity and source address of a consumed RSS signal", () => {
  const row: EvidenceSummary = {
    source_ref_id: "rss-origin", evidence_id: "ev-rss", provider: "example.org", source_type: "rss",
    title: "News", excerpt: "Reported development", url: "https://example.org/news",
    published_at: null, observed_at: null, ingested_at: null, verification_status: "unverified",
  };
  expect(formatEvidenceSummary([row])).toContain("[ev-rss]");
  expect(formatEvidenceSummary([row])).toContain(row.url);
});
