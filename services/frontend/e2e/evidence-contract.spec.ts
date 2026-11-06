import { test, expect } from "@playwright/test";
import payloads from "../../../tests/fixtures/reviewed-claims-47.json" with { type: "json" };
import passage from "../../../tests/fixtures/notebook-passage.json" with { type: "json" };

test.beforeEach(async ({ page, baseURL }) => {
  const origin = new URL(baseURL!).origin;
  await page.context().routeWebSocket("**/*", socket => socket.close());
  await page.route("**/*", async route => {
    const url = new URL(route.request().url());
    if (url.origin !== origin) return route.abort();
    if (url.pathname === "/api/config") return route.fulfill({ json: { cesium_ion_token: "" } });
    if (url.pathname.endsWith("/stream")) return route.fulfill({ contentType: "text/event-stream", body: ": fixture\n\n" });
    if (url.pathname.startsWith("/api/")) return route.fulfill({ json: [] });
    return route.continue();
  });
});

test("reviewed claim identities and original dates survive saved report display", async ({ page }, testInfo) => {
  const selected = payloads.filter(p => ["C048", "C060", "C061"].includes(p.review.claim_id));
  const report = {
    id: "reviewed-fixture", paragraph_num: 1, stamp: "01·XI", title: "Reviewed provenance fixture",
    status: "Draft", confidence: 0.3, location: "Fixture", coords: "--",
    findings: [], metrics: [], context: "", body_title: "Fixture answer",
    body_paragraphs: ["Known claim IDs are displayed with their original evidence."],
    margin: [], sources: [], created_at: "2026-11-01T00:00:00Z", updated_at: "2026-11-01T00:00:00Z",
    assessment_status: { threat: "declared", confidence: "declared", issues: [] },
    verification_status: "unverified",
    evidence_summary: selected.map(p => ({
      source_ref_id: "shared-notebook-parent", evidence_id: p.review.candidate_id,
      source_type: "notebooklm", provider: p.provider, title: p.title, excerpt: p.content,
      published_at: null, observed_at: null, ingested_at: p.ingested_at,
      verification_status: "unverified", review: p.review,
    })),
  };
  await page.route(/\/api\/reports(?:\?.*)?$/, route => route.fulfill({ json: [report] }));
  await page.route("**/api/reports/reviewed-fixture/messages*", route => route.fulfill({ json: [] }));
  await page.goto("/briefing");
  await expect(page.getByRole("heading", { name: report.title })).toBeVisible();
  await page.getByText("Quellen und Zeitachsen", { exact: true }).click();
  const evidence = page.getByTestId("evidence-provenance");
  for (const claim of await page.getByTestId("reviewed-claim").all()) {
    await claim.locator(":scope > summary").click();
  }
  for (const p of selected) {
    await expect(evidence).toContainText(p.review.candidate_id);
    await expect(evidence).toContainText(p.review.qualification_note);
    for (const origin of p.review.evidence) {
      await expect(evidence).toContainText(origin.url);
      await expect(evidence).toContainText(origin.independent_lineage);
    }
  }
  await expect(evidence).toContainText("August 2022");
  await expect(evidence).not.toContainText("2022-08-01");
  await page.screenshot({ path: testInfo.outputPath("reviewed-provenance.png"), fullPage: true });
});

test("saved abstention never renders a previous confidence score", async ({ page }, testInfo) => {
  await page.route(/\/api\/reports(?:\?.*)?$/, route => route.fulfill({ json: [{
    id: "empty-fixture", paragraph_num: 2, stamp: "01·XI", title: "Empty evidence fixture",
    status: "Draft", confidence: null, location: "Fixture", coords: "--", findings: [], metrics: [],
    context: "", body_title: "Recherche ohne Belege", body_paragraphs: ["Keine Belege in diesem Recherchelauf."],
    margin: [], sources: [], created_at: "2026-11-01T00:00:00Z", updated_at: "2026-11-01T00:00:00Z",
    assessment_status: { threat: "not_assessed", confidence: "not_assessed", issues: ["no-consumed-evidence"] },
    verification_status: "unverified", evidence_summary: [],
  }] }));
  await page.route("**/api/reports/empty-fixture/messages*", route => route.fulfill({ json: [{
    id: "saved-abstention", role: "munin", text: "Keine Belege in diesem Recherchelauf.",
    ts: "2026-11-01T00:00:00Z", refs: [], confidence: null, evidence_summary: [],
    assessment_status: { threat: "not_assessed", confidence: "not_assessed", issues: ["no-consumed-evidence"] },
    verification_status: "unverified",
  }] }));
  await page.goto("/briefing");
  await expect(page.getByRole("heading", { name: "Empty evidence fixture" })).toBeVisible();
  await expect(page.locator(".briefing-dossier-headline")).toContainText("conf unbekannt");
  await expect(page.locator(".briefing-dossier").getByText(/Keine Modellbewertung/)).toBeVisible();
  await expect(page.locator(".briefing-dossier")).not.toContainText("MODERATE");
  await expect(page.locator(".briefing-chat-list")).toContainText("Keine Modellbewertung");
  await expect(page.locator(".briefing-chat-list")).not.toContainText("Modellantwort · unverifiziert");
  await page.reload();
  await expect(page.locator(".briefing-chat-list")).toContainText("Keine Modellbewertung");
  await expect(page.locator(".briefing-chat-list")).not.toContainText("Modellantwort · unverifiziert");
  await page.screenshot({ path: testInfo.outputPath("empty-evidence.png"), fullPage: true });
});

test("notebook original passages and method limits survive report reload", async ({ page }, testInfo) => {
  const report = {
    id: "notebook-fixture", paragraph_num: 3, stamp: "06·XI", title: "Notebook depth fixture",
    status: "Draft", confidence: null, location: "Fixture", coords: "--", findings: [], metrics: [],
    context: "", body_title: "Attributable background", body_paragraphs: ["Source perspective with explicit limits."],
    margin: [], sources: [], created_at: "2026-11-06T00:00:00Z", updated_at: "2026-11-06T00:00:00Z",
    assessment_status: { threat: "not_assessed", confidence: "not_assessed", issues: [] },
    verification_status: "unverified", evidence_summary: [passage, {
      ...passage, evidence_id: "ev-method", knowledge_role: "method", title: "Independent verification",
    }],
  };
  await page.route(/\/api\/reports(?:\?.*)?$/, route => route.fulfill({ json: [report] }));
  await page.route("**/api/reports/notebook-fixture/messages*", route => route.fulfill({ json: [] }));
  for (let visit = 0; visit < 2; visit++) {
    if (visit === 0) await page.goto("/briefing"); else await page.reload();
    await expect(page.getByRole("heading", { name: report.title })).toBeVisible();
    await page.getByText("Quellen und Zeitachsen", { exact: true }).click();
    const cards = page.getByTestId("notebook-passage");
    await expect(cards).toHaveCount(2);
    for (const card of await cards.all()) await card.locator(":scope > summary").click();
    await expect(cards.first()).toContainText(passage.passage.qualification_note);
    await expect(cards.first()).toContainText(passage.excerpt);
    await expect(cards.last()).toContainText("Analysehilfe; kein Beleg für ein Ereignis.");
    await expect(cards.first().getByRole("link", { name: "Originalquelle öffnen" })).toHaveAttribute("href", passage.url);
  }
  await page.screenshot({ path: testInfo.outputPath("notebook-passages.png"), fullPage: true });
});

import current from "../../../tests/fixtures/current-research.json" with { type: "json" };

test("current research coverage and original reads survive saved report reload", async ({ page }, testInfo) => {
  const report = {
    id: "current-fixture", paragraph_num: 4, stamp: "06·XI", title: "Current research fixture",
    status: "Draft", confidence: null, location: "Fixture", coords: "--", findings: [], metrics: [],
    context: "", body_title: "Current claims", body_paragraphs: ["Attributed current claims."],
    margin: [], sources: [], created_at: "2026-11-06T14:35:00Z", updated_at: "2026-11-06T14:35:00Z",
    verification_status: "unverified", ...current,
  };
  await page.route(/\/api\/reports(?:\?.*)?$/, route => route.fulfill({ json: [report] }));
  await page.route("**/api/reports/current-fixture/messages*", route => route.fulfill({ json: [] }));
  await page.goto("/briefing");
  for (let reload = 0; reload < 2; reload++) {
    await expect(page.getByTestId("current-research-coverage")).toContainText("eingeschränkt");
    await expect(page.getByTestId("current-research-coverage")).toContainText("Prognose: nicht belastbar bewertet");
    await page.getByText("Quellen und Zeitachsen", { exact: true }).click();
    await page.getByTestId("current-source").locator(":scope > summary").click();
    await expect(page.getByTestId("current-source")).toContainText(current.evidence_summary[0]!.excerpt);
    await expect(page.getByTestId("current-source")).toContainText("Ereigniszeit: unbekannt");
    await expect(page.getByRole("link", { name: "Originalquelle öffnen" })).toHaveAttribute(
      "href", current.evidence_summary[0]!.url);
    if (reload === 0) await page.reload();
  }
  await page.screenshot({ path: testInfo.outputPath("current-research.png"), fullPage: true });
});
