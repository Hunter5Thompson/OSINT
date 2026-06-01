// services/frontend/src/components/globe/spotlight/__tests__/CountryAlmanacBriefing.test.tsx
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";

afterEach(() => vi.restoreAllMocks());

describe("CountryAlmanacPanel briefing block", () => {
  it("shows a generate button and runs the briefing", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response("missing", { status: 404 }));
    const briefing = await import("../../../../hooks/useCountryBriefing");
    const run = vi.fn();
    vi.spyOn(briefing, "useCountryBriefing").mockReturnValue({
      loading: false, currentAgent: null, result: null, error: null, run, reset: vi.fn(),
    } as never);
    const { CountryAlmanacPanel } = await import("../CountryAlmanacPanel");
    render(<CountryAlmanacPanel iso3="DEU" m49="276" />);
    const btn = await screen.findByRole("button", { name: /Munin-Briefing/i });
    fireEvent.click(btn);
    expect(run).toHaveBeenCalled();
  });

  it("shows the loader while running", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response("missing", { status: 404 }));
    const briefing = await import("../../../../hooks/useCountryBriefing");
    vi.spyOn(briefing, "useCountryBriefing").mockReturnValue({
      loading: true, currentAgent: "synthesis_agent", result: null, error: null, run: vi.fn(), reset: vi.fn(),
    } as never);
    const { CountryAlmanacPanel } = await import("../CountryAlmanacPanel");
    render(<CountryAlmanacPanel iso3="DEU" m49="276" />);
    expect(screen.getByText(/Munin · synthesis_agent/)).toBeInTheDocument();
  });

  function _resultMock(over: object = {}) {
    return {
      loading: false, currentAgent: null, error: null, run: vi.fn(), reset: vi.fn(),
      result: { query: "q", analysis: "Lagebericht…", confidence: 0.8, threat_assessment: "HIGH", sources_used: [] },
      ...over,
    };
  }

  it("renders the report, saves it, and links to the dossier", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response("missing", { status: 404 }));
    const briefing = await import("../../../../hooks/useCountryBriefing");
    vi.spyOn(briefing, "useCountryBriefing").mockReturnValue(_resultMock() as never);
    const api = await import("../../../../services/api");
    const save = vi.spyOn(api, "saveCountryBriefing").mockResolvedValue({ id: "r-001" } as never);
    const { CountryAlmanacPanel } = await import("../CountryAlmanacPanel");
    render(<CountryAlmanacPanel iso3="DEU" m49="276" />);
    fireEvent.click(screen.getByText(/HIGH · 80%/));                 // open the default-closed <details>
    expect(screen.getByText(/Lagebericht/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /speichern/i }));
    expect(save).toHaveBeenCalledWith("DEU", expect.objectContaining({ analysis: "Lagebericht…" }));
    const link = await screen.findByRole("link", { name: /öffnen/i });
    expect(link).toHaveAttribute("href", "/briefing/r-001");        // navigation to the saved dossier
  });

  it("shows a save error without crashing", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response("missing", { status: 404 }));
    const briefing = await import("../../../../hooks/useCountryBriefing");
    vi.spyOn(briefing, "useCountryBriefing").mockReturnValue(_resultMock() as never);
    const api = await import("../../../../services/api");
    vi.spyOn(api, "saveCountryBriefing").mockRejectedValue(new Error("save failed: 503"));
    const { CountryAlmanacPanel } = await import("../CountryAlmanacPanel");
    render(<CountryAlmanacPanel iso3="DEU" m49="276" />);
    fireEvent.click(screen.getByText(/HIGH · 80%/));                 // open the <details>
    fireEvent.click(screen.getByRole("button", { name: /speichern/i }));
    expect(await screen.findByText(/Speichern ·/)).toBeInTheDocument();
  });

  it("shows the briefing error line", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response("missing", { status: 404 }));
    const briefing = await import("../../../../hooks/useCountryBriefing");
    vi.spyOn(briefing, "useCountryBriefing").mockReturnValue({
      loading: false, currentAgent: null, result: null, error: "HTTP 503", run: vi.fn(), reset: vi.fn(),
    } as never);
    const { CountryAlmanacPanel } = await import("../CountryAlmanacPanel");
    render(<CountryAlmanacPanel iso3="DEU" m49="276" />);
    expect(screen.getByText(/Munin · HTTP 503/)).toBeInTheDocument();
  });

  it("disables the save button after a successful save", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response("missing", { status: 404 }));
    const briefing = await import("../../../../hooks/useCountryBriefing");
    vi.spyOn(briefing, "useCountryBriefing").mockReturnValue(_resultMock() as never);
    const api = await import("../../../../services/api");
    vi.spyOn(api, "saveCountryBriefing").mockResolvedValue({ id: "r-001" } as never);
    const { CountryAlmanacPanel } = await import("../CountryAlmanacPanel");
    render(<CountryAlmanacPanel iso3="DEU" m49="276" />);
    fireEvent.click(screen.getByText(/HIGH · 80%/));
    const saveBtn = screen.getByRole("button", { name: /speichern/i });
    fireEvent.click(saveBtn);
    await screen.findByRole("link", { name: /öffnen/i });          // save resolved
    expect(screen.getByRole("button", { name: /Briefing Room/i })).toBeDisabled();
  });

  it("clears the prior dossier link when the inspected country changes", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response("missing", { status: 404 }));
    const briefing = await import("../../../../hooks/useCountryBriefing");
    const reset = vi.fn();
    vi.spyOn(briefing, "useCountryBriefing").mockReturnValue(_resultMock({ reset }) as never);
    const api = await import("../../../../services/api");
    vi.spyOn(api, "saveCountryBriefing").mockResolvedValue({ id: "r-001" } as never);
    const { CountryAlmanacPanel } = await import("../CountryAlmanacPanel");
    const { rerender } = render(<CountryAlmanacPanel iso3="DEU" m49="276" />);
    fireEvent.click(screen.getByText(/HIGH · 80%/));
    fireEvent.click(screen.getByRole("button", { name: /speichern/i }));
    await screen.findByRole("link", { name: /öffnen/i });           // link present for DEU
    rerender(<CountryAlmanacPanel iso3="FRA" m49="250" />);         // switch country
    expect(reset).toHaveBeenCalled();                               // hook reset fired
    expect(screen.queryByRole("link", { name: /öffnen/i })).toBeNull();  // stale link cleared
  });
});
