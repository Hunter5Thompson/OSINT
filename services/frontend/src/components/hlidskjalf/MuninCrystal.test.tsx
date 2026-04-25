import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import { MuninCrystal } from "./MuninCrystal";

describe("MuninCrystal", () => {
  it("renders three rhombi", () => {
    const { container } = render(<MuninCrystal size={64} />);
    expect(container.querySelectorAll("svg [data-rhombus]")).toHaveLength(3);
  });

  it("respects size prop", () => {
    const { container } = render(<MuninCrystal size={120} />);
    const svg = container.querySelector("svg");
    expect(svg).toHaveAttribute("width", "120");
  });
});
