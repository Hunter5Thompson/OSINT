import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { OverlayPanel } from "./OverlayPanel";

describe("OverlayPanel", () => {
  it("renders § number and label when expanded", () => {
    render(
      <OverlayPanel paragraph="I" label="Layers" variant="expanded">
        <p>body</p>
      </OverlayPanel>,
    );
    expect(screen.getByText(/§ I · Layers/i)).toBeInTheDocument();
    expect(screen.getByText("body")).toBeInTheDocument();
  });

  it("hides body when variant is 'collapsed' and shows tab affordance", () => {
    render(
      <OverlayPanel paragraph="II" label="Search" variant="collapsed">
        <p data-testid="body">body</p>
      </OverlayPanel>,
    );
    expect(screen.queryByTestId("body")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /expand Search/i })).toBeInTheDocument();
  });

  it("does not render at all when variant is 'hidden'", () => {
    const { container } = render(
      <OverlayPanel paragraph="III" label="Inspector" variant="hidden">
        <p>body</p>
      </OverlayPanel>,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("calls onClose when close button is clicked", () => {
    const onClose = vi.fn();
    render(
      <OverlayPanel paragraph="I" label="Layers" variant="expanded" onClose={onClose}>
        <p>body</p>
      </OverlayPanel>,
    );
    fireEvent.click(screen.getByRole("button", { name: /close Layers/i }));
    expect(onClose).toHaveBeenCalledOnce();
  });

  it("calls onExpand when tab is clicked in collapsed variant", () => {
    const onExpand = vi.fn();
    render(
      <OverlayPanel paragraph="II" label="Search" variant="collapsed" onExpand={onExpand}>
        <p>body</p>
      </OverlayPanel>,
    );
    fireEvent.click(screen.getByRole("button", { name: /expand Search/i }));
    expect(onExpand).toHaveBeenCalledOnce();
  });

  it("applies panel bg + border + blur from CSS tokens", () => {
    render(
      <OverlayPanel paragraph="I" label="Layers" variant="expanded">
        <p>body</p>
      </OverlayPanel>,
    );
    const panel = screen.getByRole("region");
    const inline = panel.getAttribute("style") ?? "";
    expect(inline).toContain("var(--hl-panel-bg)");
    expect(inline).toContain("var(--hl-panel-border)");
    expect(inline).toContain("var(--hl-panel-blur)");
  });
});
