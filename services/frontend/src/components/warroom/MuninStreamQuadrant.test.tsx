import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { MuninStreamQuadrant } from "./MuninStreamQuadrant";

describe("MuninStreamQuadrant", () => {
  it("shows the working hypothesis when provided", () => {
    render(
      <MuninStreamQuadrant
        toolCalls={[
          { tplus: "T+00:01:08", tool: "qdrant.search", detail: "12 hits · 0.71" },
        ]}
        hypothesis="Cluster signature consistent with airstrike."
        onAsk={() => {}}
      />,
    );
    expect(screen.getByText(/Cluster signature/)).toBeInTheDocument();
    expect(screen.getByText("qdrant.search")).toBeInTheDocument();
  });

  it("invokes onAsk on Cmd+Enter", () => {
    const onAsk = vi.fn();
    render(
      <MuninStreamQuadrant toolCalls={[]} hypothesis="" onAsk={onAsk} />,
    );
    const input = screen.getByPlaceholderText(/ask munin/i) as HTMLInputElement;
    fireEvent.change(input, { target: { value: "what changed?" } });
    fireEvent.keyDown(input, { key: "Enter", metaKey: true });
    expect(onAsk).toHaveBeenCalledWith("what changed?");
  });
});
