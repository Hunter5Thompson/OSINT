import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import { BriefingPage } from "../../pages/BriefingPage";
import type { IntelAnalysis, ReportRecord } from "../../types";

const intelState = vi.hoisted(() => ({ result: null as IntelAnalysis | null, error: null as string | null }));

const {
  getReportsMock,
  createReportMock,
  getReportMessagesMock,
  appendReportMessageMock,
  updateReportMock,
} = vi.hoisted(() => ({
  getReportsMock: vi.fn(),
  createReportMock: vi.fn(),
  getReportMessagesMock: vi.fn(),
  appendReportMessageMock: vi.fn(),
  updateReportMock: vi.fn(),
}));

vi.mock("../../services/api", () => ({
  getReports: getReportsMock,
  createReport: createReportMock,
  getReportMessages: getReportMessagesMock,
  appendReportMessage: appendReportMessageMock,
  updateReport: updateReportMock,
}));

vi.mock("../../hooks/useIntel", () => ({
  useIntel: () => ({
    loading: false,
    reportId: "r-044",
    currentAgent: null,
    result: intelState.result,
    error: intelState.error,
    runQuery: vi.fn(() => vi.fn()),
  }),
}));

const sampleReport: ReportRecord = {
  id: "r-044",
  paragraph_num: 44,
  stamp: "14·IV",
  title: "Sinjar Ridge · Escalation Pattern",
  status: "Draft",
  confidence: 0.87,
  location: "Sinjar ridge",
  coords: "36.34N 41.87E",
  findings: ["A", "B", "C"],
  metrics: [
    { label: "clusters", value: "17", sub: "delta", tone: "sentinel" },
    { label: "corridor", value: "4.2 km", sub: "sigma", tone: "amber" },
    { label: "confidence", value: "0.87", sub: "fusion", tone: "sage" },
  ],
  context: "Pattern context",
  body_title: "Body title",
  body_paragraphs: ["Paragraph 1"],
  margin: [{ label: "window", value: "22:14Z" }],
  sources: ["firms·1"],
  created_at: "2026-04-24T00:00:00Z",
  updated_at: "2026-04-24T00:00:00Z",
};

beforeEach(() => {
  intelState.result = null;
  intelState.error = null;
  vi.clearAllMocks();
  getReportsMock.mockResolvedValue([sampleReport]);
  getReportMessagesMock.mockResolvedValue([]);
  createReportMock.mockResolvedValue({
    ...sampleReport,
    id: "r-045",
    paragraph_num: 45,
    title: "Untitled Dossier",
    context: "New dossier scaffolded."
  });
  appendReportMessageMock.mockResolvedValue({
    id: "msg-user",
    role: "user",
    text: "Brief me",
    ts: "2026-04-24T00:00:00Z",
    refs: [],
  });
  updateReportMock.mockResolvedValue({
    ...sampleReport,
    status: "Published",
  });
});

function renderBriefing() {
  return render(
    <MemoryRouter initialEntries={["/briefing"]}>
      <BriefingPage />
    </MemoryRouter>,
  );
}

describe("BriefingPage", () => {
  it("keeps live chat source metadata attached to that answer", async () => {
    const view = renderBriefing();
    await screen.findAllByText(/Sinjar Ridge/);
    intelState.result = { query: "synthetic", agent_chain: [], sources_used: [], analysis: "Synthetic answer",
      confidence: .3, threat_assessment: "MODERATE", timestamp: "2026-10-10T00:00:00Z",
      verification_status: "unverified", evidence_summary: [{ source_ref_id: "synthetic-chat-ref",
        source_type: "dataset", provider: "fixture.example.invalid", published_at: null,
        observed_at: "2020-01-01T00:00:00Z", ingested_at: "2026-10-10T00:00:00Z", verification_status: "unverified" }] };
    view.rerender(<MemoryRouter initialEntries={["/briefing"]}><BriefingPage /></MemoryRouter>);
    expect(screen.getByText(/synthetic-chat-ref · unverifiziert/)).toBeInTheDocument();
    expect(screen.getByText(/Beobachtet UTC: 2020-01-01T00:00:00.000Z/)).toBeInTheDocument();
    expect(screen.getByText("Modellantwort · unverifiziert")).toBeInTheDocument();
  });

  it("does not display an old confidence metric when the saved assessment declares a default", async () => {
    getReportsMock.mockResolvedValue([{ ...sampleReport,
      assessment_status: { threat: "default", confidence: "default", issues: ["confidence-missing"] } }]);
    renderBriefing();
    await screen.findAllByText(/Sinjar Ridge/);
    expect(screen.queryAllByText("0.87", { exact: true })).toHaveLength(0);
    expect(screen.getByText("nicht gelesen")).toBeInTheDocument();
  });
  it("retains saved source time axes and explicit unknown publication", async () => {
    getReportsMock.mockResolvedValue([{ ...sampleReport, evidence_summary: [{
      source_ref_id: "synthetic-ref", source_type: "dataset", provider: "fixture.example.invalid",
      published_at: null, observed_at: "2020-01-01T00:00:00Z", ingested_at: "2026-10-10T00:00:00Z",
      verification_status: "unverified" }] }]);
    renderBriefing();
    await screen.findAllByText(/Sinjar Ridge/);
    expect(screen.getByText(/Publiziert UTC: unbekannt/)).toBeInTheDocument();
    expect(screen.getByText(/Beobachtet UTC: 2020-01-01T00:00:00.000Z/)).toBeInTheDocument();
    expect(screen.getByText(/Ingest UTC: 2026-10-10T00:00:00.000Z/)).toBeInTheDocument();
  });
  it("keeps saved assessment defaults unavailable in archive and dossier headers", async () => {
    getReportsMock.mockResolvedValue([{ ...sampleReport, title: "Synthetic default report",
      confidence: 0.5,
      assessment_status: { threat: "default", confidence: "default", issues: ["confidence-missing"] },
      verification_status: "unverified" }]);
    renderBriefing();
    await screen.findAllByText(/Synthetic default report/);
    expect(screen.queryAllByText(/conf 0\.50/)).toHaveLength(0);
    expect(screen.getAllByText(/conf unbekannt/).length).toBeGreaterThan(0);
    expect(screen.getByText(/Quellenbelege sind nicht unabhängig verifiziert/)).toBeInTheDocument();
  });

  it("renders archive/index and dossier shell from API", async () => {
    renderBriefing();

    expect(screen.getAllByText(/Dossier Archive/i).length).toBeGreaterThan(0);
    expect((await screen.findAllByText(/Sinjar Ridge · Escalation Pattern/i)).length).toBeGreaterThan(0);
    expect(screen.getByRole("button", { name: /\+ New Dossier/i })).toBeInTheDocument();
  });

  it("filters reports and supports retry", async () => {
    renderBriefing();
    await screen.findAllByText(/Sinjar Ridge · Escalation Pattern/i);

    const filter = screen.getByPlaceholderText(/date, entity, status/i);
    fireEvent.change(filter, { target: { value: "zzzz-no-hit" } });

    expect(screen.getByText(/no dossiers yet/i)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /retry/i }));

    await waitFor(() => {
      expect(getReportsMock).toHaveBeenCalledTimes(2);
    });
  });

  it("creates a new dossier from backend", async () => {
    renderBriefing();
    await screen.findAllByText(/Sinjar Ridge · Escalation Pattern/i);

    fireEvent.click(screen.getByRole("button", { name: /\+ New Dossier/i }));

    await waitFor(() => {
      expect(createReportMock).toHaveBeenCalledTimes(1);
    });
    expect((await screen.findAllByText(/Untitled Dossier/i)).length).toBeGreaterThan(0);
  });

  it("expands and collapses full dossier body", async () => {
    renderBriefing();
    await screen.findAllByText(/Sinjar Ridge · Escalation Pattern/i);

    const expandButton = screen.getByRole("button", { name: /Read full dossier/i });
    expect(expandButton).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(expandButton);

    const bodyTitle = await screen.findByRole("heading", { name: /Body title/i });
    expect(bodyTitle).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Collapse dossier/i })).toHaveAttribute(
      "aria-expanded",
      "true",
    );

    fireEvent.click(screen.getByRole("button", { name: /Collapse dossier/i }));
    await waitFor(() => {
      expect(screen.queryByRole("heading", { name: /Body title/i })).not.toBeInTheDocument();
    });
    expect(screen.getByRole("button", { name: /Read full dossier/i })).toHaveAttribute(
      "aria-expanded",
      "false",
    );
  });
});


it("shows a recoverable chat load failure instead of an empty dossier channel", async () => {
  getReportMessagesMock.mockRejectedValueOnce(new Error("chat store unavailable"));
  renderBriefing();
  expect(await screen.findByRole("alert")).toHaveTextContent("chat store unavailable");
  expect(screen.queryByText("No dialogue yet for this dossier.")).not.toBeInTheDocument();
  getReportMessagesMock.mockResolvedValueOnce([{ id: "saved", role: "user", text: "Saved question", ts: "2026-01-01T00:00:00Z", refs: [] }]);
  fireEvent.click(screen.getByRole("button", { name: "Retry dossier chat" }));
  expect(await screen.findByText("Saved question")).toBeInTheDocument();
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
});

it("keeps the actual model overload reason visible and labels both inputs", async () => {
  intelState.error = "Analysis capacity is busy. Try again shortly.";
  renderBriefing();
  await screen.findAllByText(/Sinjar Ridge/);
  expect(screen.getByRole("alert")).toHaveTextContent("Analysis capacity is busy");
  expect(screen.getByRole("textbox", { name: "Ask Munin about this dossier" })).toBeInTheDocument();
  expect(screen.getByRole("textbox", { name: "Filter dossiers" })).toBeInTheDocument();
});

it("never inserts an answer into a different dossier selected while analysis ran", async () => {
  getReportsMock.mockResolvedValue([sampleReport, { ...sampleReport, id: "r-other", title: "Other dossier", paragraph_num: 45 }]);
  const view = renderBriefing();
  await screen.findAllByText(/Sinjar Ridge/);
  fireEvent.click(screen.getByRole("button", { name: /Other dossier/ }));
  await screen.findByRole("heading", { name: "Other dossier" });
  intelState.result = { query: "old dossier", agent_chain: [], sources_used: [], analysis: "Answer belongs to the original dossier",
    confidence: .8, threat_assessment: "MODERATE", timestamp: "2026-11-01T00:00:00Z" };
  view.rerender(<MemoryRouter><BriefingPage /></MemoryRouter>);
  expect(screen.queryByText("Answer belongs to the original dossier")).not.toBeInTheDocument();
});
