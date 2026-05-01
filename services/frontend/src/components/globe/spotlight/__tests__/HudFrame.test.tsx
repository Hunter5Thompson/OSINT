import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { HudFrame } from "../HudFrame";
import { SpotlightProvider } from "../SpotlightContext";

describe("HudFrame", () => {
  it("renders idle eyebrow when no focus", () => {
    render(<SpotlightProvider><HudFrame /></SpotlightProvider>);
    expect(screen.getByText(/§ worldview · idle/i)).toBeInTheDocument();
  });

  it("renders UTC clock", () => {
    render(<SpotlightProvider><HudFrame /></SpotlightProvider>);
    expect(screen.getByText(/utc/i)).toBeInTheDocument();
  });
});
