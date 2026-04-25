import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { LeaderCallout } from "./LeaderCallout";

describe("LeaderCallout", () => {
  it("renders eyebrow + value + optional sub", () => {
    render(
      <LeaderCallout
        eyebrow="Healthcare"
        value="23,560"
        sub="Bed availability"
        leader={{ from: "right", deltaPx: 80 }}
      />,
    );
    expect(screen.getByText(/Healthcare/)).toBeInTheDocument();
    expect(screen.getByText("23,560")).toBeInTheDocument();
    expect(screen.getByText("Bed availability")).toBeInTheDocument();
  });

  it("draws a leader line svg", () => {
    const { container } = render(
      <LeaderCallout
        eyebrow="x"
        value="1"
        leader={{ from: "left", deltaPx: 60 }}
      />,
    );
    expect(container.querySelector("svg[data-part='leader']")).not.toBeNull();
  });
});
