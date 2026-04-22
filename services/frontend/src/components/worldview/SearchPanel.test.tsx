import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { SearchPanel } from "./SearchPanel";

describe("SearchPanel", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("renders the input with search placeholder", () => {
    render(<SearchPanel viewer={null} />);
    const input = screen.getByPlaceholderText(/search entities/i);
    expect(input).toBeInTheDocument();
  });

  it("calls /api/v1/graph/search with typed query after debounce", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        nodes: [{ id: "ucdp:44821", name: "Sinjar ridge", type: "Location" }],
        total_count: 1,
      }),
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<SearchPanel viewer={null} />);
    fireEvent.change(screen.getByPlaceholderText(/search entities/i), {
      target: { value: "sinj" },
    });
    await waitFor(() => expect(screen.getByText(/Sinjar ridge/i)).toBeInTheDocument());
    const firstCallArgs = fetchMock.mock.calls[0];
    expect(firstCallArgs).toBeDefined();
    const calledUrl = firstCallArgs![0] as string;
    expect(calledUrl).toMatch(/\/api\/graph\/search\?q=sinj/);
  });

  it("renders node.type as an Eyebrow next to the name", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        nodes: [{ id: "loc:1", name: "Barents Sea", type: "Location" }],
        total_count: 1,
      }),
    }));
    render(<SearchPanel viewer={null} />);
    fireEvent.change(screen.getByPlaceholderText(/search entities/i), {
      target: { value: "bare" },
    });
    await waitFor(() => {
      expect(screen.getByText(/Barents Sea/i)).toBeInTheDocument();
      expect(screen.getByText(/Location/i)).toBeInTheDocument();
    });
  });

  it("shows no-matches placeholder when nodes is empty", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ nodes: [], total_count: 0 }),
    }));
    render(<SearchPanel viewer={null} />);
    fireEvent.change(screen.getByPlaceholderText(/search entities/i), {
      target: { value: "zzz" },
    });
    await waitFor(() => expect(screen.getByText(/— no matches —/i)).toBeInTheDocument());
  });

  it("resets loading when query drops below 2 chars while a fetch is in flight", async () => {
    // Leave fetch pending indefinitely so the component observes `loading: true`
    // at the moment the user deletes back below the debounce threshold.
    vi.stubGlobal(
      "fetch",
      vi.fn().mockReturnValue(new Promise(() => {})),
    );
    render(<SearchPanel viewer={null} />);
    const input = screen.getByPlaceholderText(/search entities/i);
    fireEvent.change(input, { target: { value: "sinj" } });
    // Wait for the 180ms debounce to elapse and loading to flip true.
    await waitFor(() => expect(screen.getByText(/§ searching…/i)).toBeInTheDocument());
    // Delete back to one character — regressed behaviour: "§ searching…" stays.
    fireEvent.change(input, { target: { value: "s" } });
    await waitFor(() => expect(screen.queryByText(/§ searching…/i)).not.toBeInTheDocument());
  });
});
