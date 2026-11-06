import { render, screen } from "@testing-library/react";
import { expect, it } from "vitest";
import { EvidenceTimeAxes } from "../EvidenceTimeAxes";
import payloads from "../../../../../../tests/fixtures/reviewed-claims-47.json";
import type { EvidenceSummary } from "../../../types";
import passage from "../../../../../../tests/fixtures/notebook-passage.json";

it("labels the original investigation and exposes safe source links with its qualification", () => {
  const p = payloads.find(p => p.review.claim_id === "C060")!;
  const summary = [{ source_ref_id: "parent", evidence_id: "claim-60", source_type: "notebooklm",
    provider: p.provider, published_at: null, observed_at: null, ingested_at: p.ingested_at,
    excerpt: p.content, verification_status: "unverified", review: p.review }] as EvidenceSummary[];
  render(<EvidenceTimeAxes summary={summary} />);
  expect(screen.getByRole("link", { name: "RUSI Silicon Lifeline report", hidden: true })).toHaveAttribute(
    "href", "https://static.rusi.org/RUSI-Silicon-Lifeline-final-updated-web_1.pdf");
  expect(screen.getByText((text, element) => element?.tagName === "P" && text.includes(p.review.qualification_note))).toBeInTheDocument();
});

it("shows original notebook passages and keeps methods separate from event evidence", () => {
  const summary = [{ ...passage, knowledge_role: "method" }] as EvidenceSummary[];
  render(<EvidenceTimeAxes summary={summary} />);
  expect(screen.getByText("Methode · Supply chains")).toBeInTheDocument();
  expect(screen.getByText("Originalpassage · nicht extern faktengeprüft")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Originalquelle öffnen", hidden: true })).toHaveAttribute(
    "href", passage.url);
  expect(screen.getByText(passage.excerpt, { selector: "p", normalizer: text => text })).toBeInTheDocument();
  expect(screen.getByText("Check publication date", { selector: "li" })).toBeInTheDocument();
});

import current from "../../../../../../tests/fixtures/current-research.json";
import type { ResearchCoverage } from "../../../types";

it("shows current coverage, source-read limits and publication separately from retrieval", () => {
  render(<EvidenceTimeAxes summary={current.evidence_summary as EvidenceSummary[]}
    coverage={current.research_coverage as ResearchCoverage} />);
  expect(screen.getByText("Aktuelle Recherche · eingeschränkt")).toBeInTheDocument();
  expect(screen.getByText("Originaltext abgerufen · nicht extern faktengeprüft")).toBeInTheDocument();
  expect(screen.getByText(/Prognose: nicht belastbar bewertet/)).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Originalquelle öffnen", hidden: true })).toHaveAttribute(
    "href", current.evidence_summary[0]?.url);
  expect(screen.getByText(/Publikation laut Suchanbieter: 2026-11-06T12:00:00Z/)).toBeInTheDocument();
  expect(screen.getByText(/Abruf: 2026-11-06T14:35:02Z/)).toBeInTheDocument();
});
