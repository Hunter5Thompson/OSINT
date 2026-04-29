import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { AgentStreamLine } from "./AgentStreamLine";

describe("AgentStreamLine", () => {
  it("renders timestamp, tool, and detail in mono", () => {
    render(
      <AgentStreamLine
        tplus="T+02:14:08"
        tool="qdrant.search"
        detail="12 hits · 0.71"
      />
    );
    expect(screen.getByText("T+02:14:08")).toBeInTheDocument();
    expect(screen.getByText("qdrant.search")).toBeInTheDocument();
    expect(screen.getByText(/12 hits/)).toBeInTheDocument();
  });

  it("colour-codes by tone", () => {
    const { container } = render(
      <AgentStreamLine tplus="T+00:00:01" tool="x" detail="y" tone="amber" />
    );
    expect(container.firstChild).toHaveAttribute("data-tone", "amber");
  });
});
