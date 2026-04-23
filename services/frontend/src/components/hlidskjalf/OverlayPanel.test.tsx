import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { OverlayPanel } from "./OverlayPanel";

describe("OverlayPanel", () => {
  it("renders section title and children when expanded", () => {
    render(
      <OverlayPanel paragraph="I" label="Layers" variant="expanded">
        <p>body</p>
      </OverlayPanel>,
    );

    expect(screen.getByText(/§ I · Layers/i)).toBeInTheDocument();
    expect(screen.getByText("body")).toBeInTheDocument();
  });

  it("renders tab affordance when collapsed", () => {
    render(
      <OverlayPanel paragraph="II" label="Search" variant="collapsed">
        <p>body</p>
      </OverlayPanel>,
    );

    expect(screen.getByRole("button", { name: /expand Search/i })).toBeInTheDocument();
    expect(screen.queryByText("body")).not.toBeInTheDocument();
  });

  it("does not render when hidden", () => {
    const { container } = render(
      <OverlayPanel paragraph="III" label="Inspector" variant="hidden">
        <p>body</p>
      </OverlayPanel>,
    );

    expect(container).toBeEmptyDOMElement();
  });

  it("calls onClose from close button", () => {
    const onClose = vi.fn();
    render(
      <OverlayPanel paragraph="III" label="Inspector" variant="expanded" onClose={onClose}>
        <p>body</p>
      </OverlayPanel>,
    );

    fireEvent.click(screen.getByRole("button", { name: /close Inspector/i }));
    expect(onClose).toHaveBeenCalledOnce();
  });

  it("calls onExpand when tab is clicked", () => {
    const onExpand = vi.fn();
    render(
      <OverlayPanel paragraph="II" label="Search" variant="collapsed" onExpand={onExpand}>
        <p>body</p>
      </OverlayPanel>,
    );

    fireEvent.click(screen.getByRole("button", { name: /expand Search/i }));
    expect(onExpand).toHaveBeenCalledOnce();
  });
});
