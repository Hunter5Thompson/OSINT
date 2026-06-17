import { describe, it, expect, vi } from "vitest";
import { render } from "@testing-library/react";
import { MuninStreamQuadrant } from "../MuninStreamQuadrant";

describe("Munin hypothesis readability (P7)", () => {
  it("renders the hypothesis upright and at >= 15px", () => {
    const { container } = render(
      <MuninStreamQuadrant toolCalls={[]} hypothesis="Test working hypothesis" onAsk={vi.fn()} />,
    );
    const node = container.querySelector('[data-part="hypothesis"]') as HTMLElement;
    expect(node).toBeTruthy();
    expect(node.style.fontStyle).not.toBe("italic");
    expect(parseFloat(node.style.fontSize)).toBeGreaterThanOrEqual(15);
  });
});
