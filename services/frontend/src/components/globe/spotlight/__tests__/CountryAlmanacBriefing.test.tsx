// services/frontend/src/components/globe/spotlight/__tests__/CountryAlmanacBriefing.test.tsx
import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { SpatialCountryAlmanacState } from "../../../../hooks/useSpatialCountryAlmanac";
import {
  parseCatalogRevision,
  parseScopeKeyCandidate,
  type SpatialQueryRef,
} from "../../../../spatial/contracts";

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

function spatialQuery(scopeKey: string): SpatialQueryRef {
  return {
    schemaVersion: 1,
    scopeKey: parseScopeKeyCandidate(scopeKey),
    catalogRevision: parseCatalogRevision("spatial-v1-fe9828dcda05"),
    boundaryPolicy: "odin-reference-v1",
  };
}

function spatialFacts(name: string): SpatialCountryAlmanacState {
  return {
    status: "ready",
    error: null,
    data: {
      id: name,
      iso3: name.slice(0, 3).toUpperCase(),
      m49: "000",
      name,
      region: "Europe",
      subregion: "",
      capital: null,
      facts: {
        profile: [{ label: "Status", value: "Current" }],
        people: [],
        government: [],
        economy: [],
        security: [],
      },
      updated_at: "2026-08-10",
      source_note: "fixture",
      scope_key: "country:UKR",
      catalog_revision: "spatial-v1-fe9828dcda05",
    },
  };
}

function deferred<T>() {
  let resolvePromise: (value: T) => void = () => undefined;
  const promise = new Promise<T>((resolve) => {
    resolvePromise = resolve;
  });
  return { promise, resolve: resolvePromise };
}

describe("SpatialCountryAlmanacPanel briefing parity", () => {
  function resultMock() {
    return {
      loading: false,
      currentAgent: null,
      error: null,
      run: vi.fn(),
      reset: vi.fn(),
      result: {
        query: "q",
        analysis: "Spatial Lagebericht",
        confidence: 0.8,
        threat_assessment: "HIGH",
        sources_used: [],
      },
    };
  }

  it("saves and opens a briefing only through the committed Spatial query", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response("missing", { status: 404 }));
    const briefing = await import("../../../../hooks/useSpatialCountryBriefing");
    vi.spyOn(briefing, "useSpatialCountryBriefing").mockReturnValue(resultMock() as never);
    const api = await import("../../../../services/api");
    const save = vi.spyOn(api, "saveSpatialCountryBriefing")
      .mockResolvedValue({ id: "spatial-r-001" } as never);
    const { SpatialCountryAlmanacPanel } = await import("../CountryAlmanacPanel");
    const token = spatialQuery("country:UKR");

    render(<SpatialCountryAlmanacPanel facts={spatialFacts("Ukraine")} query={token} />);
    fireEvent.click(screen.getByText(/HIGH · 80%/));
    fireEvent.click(screen.getByRole("button", { name: /speichern/i }));

    expect(save).toHaveBeenCalledWith(
      token,
      expect.objectContaining({ analysis: "Spatial Lagebericht" }),
      expect.any(AbortSignal),
    );
    expect(await screen.findByRole("link", { name: /öffnen/i })).toHaveAttribute(
      "href",
      "/briefing/spatial-r-001",
    );
  });

  it("cannot render selection A save state after switching to selection B", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response("missing", { status: 404 }));
    const briefing = await import("../../../../hooks/useSpatialCountryBriefing");
    vi.spyOn(briefing, "useSpatialCountryBriefing").mockReturnValue(resultMock() as never);
    const api = await import("../../../../services/api");
    const lateSave = deferred<Awaited<ReturnType<typeof api.saveSpatialCountryBriefing>>>();
    vi.spyOn(api, "saveSpatialCountryBriefing").mockReturnValue(lateSave.promise);
    const { SpatialCountryAlmanacPanel } = await import("../CountryAlmanacPanel");
    const ukraine = spatialQuery("country:UKR");
    const poland = spatialQuery("country:POL");

    const view = render(
      <SpatialCountryAlmanacPanel facts={spatialFacts("Ukraine")} query={ukraine} />,
    );
    fireEvent.click(screen.getByText(/HIGH · 80%/));
    fireEvent.click(screen.getByRole("button", { name: /speichern/i }));
    const saveSignal = vi.mocked(api.saveSpatialCountryBriefing).mock.calls[0]?.[2];

    view.rerender(
      <SpatialCountryAlmanacPanel facts={spatialFacts("Poland")} query={poland} />,
    );
    expect(saveSignal?.aborted).toBe(true);

    await act(async () => lateSave.resolve({ id: "stale-ukraine" } as never));
    expect(screen.queryByRole("link", { name: /öffnen/i })).toBeNull();
    expect(screen.queryByText(/✓ in Briefing Room/i)).toBeNull();
  });
});
