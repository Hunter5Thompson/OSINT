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
});
