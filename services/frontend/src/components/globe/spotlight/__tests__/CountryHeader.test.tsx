import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { CountryHeader } from "../CountryHeader";

describe("CountryHeader", () => {
  it("renders name + capital + S2.5 placeholder", () => {
    render(<CountryHeader name="Greece" iso3="GRC" m49="300" capital={{ name: "Athens", coords: { lon: 23.7, lat: 37.9 } }} />);
    expect(screen.getByText(/Greece/)).toBeInTheDocument();
    expect(screen.getByText(/Athens/)).toBeInTheDocument();
    expect(screen.getByText(/S2\.5 coming soon/i)).toBeInTheDocument();
  });

  it("falls back gracefully without iso3 + capital", () => {
    render(<CountryHeader name="W. Sahara" iso3={null} m49="732" capital={null} />);
    expect(screen.getByText(/W\. Sahara/)).toBeInTheDocument();
    expect(screen.getByText(/m49 · 732/)).toBeInTheDocument();
  });
});
