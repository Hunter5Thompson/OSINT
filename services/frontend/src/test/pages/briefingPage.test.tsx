import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import { BriefingPage } from "../../pages/BriefingPage";
import type { ReportRecord } from "../../types";

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
    currentAgent: null,
    result: null,
    error: null,
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

    fireEvent.click(screen.getByRole("button", { name: /Read full dossier/i }));
    expect(screen.getByText(/Body title/i)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Collapse dossier/i }));
    expect(screen.queryByText(/Body title/i)).not.toBeInTheDocument();
  });
});
