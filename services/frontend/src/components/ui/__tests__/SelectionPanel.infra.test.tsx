import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { SelectionPanel } from "../SelectionPanel";
import type { DatacenterProperties, RefineryProperties } from "../../../types";

describe("SelectionPanel — datacenter selection", () => {
  const dcProps: DatacenterProperties = {
    name: "AWS Ashburn",
    operator: "Amazon Web Services",
    tier: "hyperscaler",
    capacity_mw: 600,
    country: "US",
    city: "Ashburn",
  };

  it("renders datacenter header and all fields", () => {
    render(
      <SelectionPanel
        selected={{ type: "datacenter", data: dcProps }}
        onClose={vi.fn()}
        viewer={null}
      />,
    );
    expect(screen.getByText("DATACENTER")).toBeDefined();
    expect(screen.getByText("AWS Ashburn")).toBeDefined();
    expect(screen.getByText("Amazon Web Services")).toBeDefined();
    expect(screen.getByText("HYPERSCALER")).toBeDefined();
    expect(screen.getByText("600 MW")).toBeDefined();
    expect(screen.getByText("US")).toBeDefined();
    expect(screen.getByText("Ashburn")).toBeDefined();
  });

  it("renders dash for null capacity", () => {
    render(
      <SelectionPanel
        selected={{ type: "datacenter", data: { ...dcProps, capacity_mw: null } }}
        onClose={vi.fn()}
        viewer={null}
      />,
    );
    // The em-dash character for null capacity
    const allText = document.body.textContent || "";
    expect(allText).toContain("—");
  });
});

describe("SelectionPanel — refinery selection", () => {
  const rfProps: RefineryProperties = {
    name: "Jamnagar Refinery",
    operator: "Reliance Industries",
    capacity_bpd: 1240000,
    country: "IN",
    status: "active",
  };

  it("renders refinery header and all fields", () => {
    render(
      <SelectionPanel
        selected={{ type: "refinery", data: rfProps }}
        onClose={vi.fn()}
        viewer={null}
      />,
    );
    expect(screen.getByText("OIL REFINERY")).toBeDefined();
    expect(screen.getByText("Jamnagar Refinery")).toBeDefined();
    expect(screen.getByText("Reliance Industries")).toBeDefined();
    expect(screen.getByText("1.24M bbl/day")).toBeDefined();
    expect(screen.getByText("IN")).toBeDefined();
    expect(screen.getByText("ACTIVE")).toBeDefined();
  });

  it("formats sub-million capacity in K", () => {
    render(
      <SelectionPanel
        selected={{ type: "refinery", data: { ...rfProps, capacity_bpd: 550000 } }}
        onClose={vi.fn()}
        viewer={null}
      />,
    );
    expect(screen.getByText("550K bbl/day")).toBeDefined();
  });
});
