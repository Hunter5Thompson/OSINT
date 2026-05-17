import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { BandwidthGuard } from "../BandwidthGuard";

describe("BandwidthGuard", () => {
  afterEach(() => {
    Object.defineProperty(navigator, "connection", { value: undefined, configurable: true });
  });

  it("renders children AND fires onConfirm once on a fast connection", async () => {
    Object.defineProperty(navigator, "connection", {
      value: { effectiveType: "4g" }, configurable: true,
    });
    const onConfirm = vi.fn();
    render(
      <BandwidthGuard sizeBytes={200_000_000} onConfirm={onConfirm} onCancel={vi.fn()}>
        <div data-testid="child">child</div>
      </BandwidthGuard>
    );
    expect(screen.getByTestId("child")).toBeInTheDocument();
    await waitFor(() => expect(onConfirm).toHaveBeenCalledTimes(1));
  });

  it("shows confirm dialog on 3G and does NOT fire onConfirm yet", () => {
    Object.defineProperty(navigator, "connection", {
      value: { effectiveType: "3g" }, configurable: true,
    });
    const onConfirm = vi.fn();
    render(
      <BandwidthGuard sizeBytes={200_000_000} onConfirm={onConfirm} onCancel={vi.fn()}>
        <div data-testid="child">child</div>
      </BandwidthGuard>
    );
    expect(screen.queryByTestId("child")).toBeNull();
    expect(screen.getByRole("button", { name: /load anyway/i })).toBeInTheDocument();
    expect(screen.getByText(/190/)).toBeInTheDocument();
    expect(onConfirm).not.toHaveBeenCalled();
  });

  it("after Load anyway: renders children and fires onConfirm exactly once", async () => {
    Object.defineProperty(navigator, "connection", {
      value: { effectiveType: "3g" }, configurable: true,
    });
    const onConfirm = vi.fn();
    render(
      <BandwidthGuard sizeBytes={200_000_000} onConfirm={onConfirm} onCancel={vi.fn()}>
        <div data-testid="child">child</div>
      </BandwidthGuard>
    );
    fireEvent.click(screen.getByRole("button", { name: /load anyway/i }));
    await waitFor(() => expect(screen.getByTestId("child")).toBeInTheDocument());
    expect(onConfirm).toHaveBeenCalledTimes(1);
  });

  it("calls onCancel when cancel pressed on slow connection", () => {
    Object.defineProperty(navigator, "connection", {
      value: { effectiveType: "2g" }, configurable: true,
    });
    const onCancel = vi.fn();
    render(
      <BandwidthGuard sizeBytes={50_000_000} onConfirm={vi.fn()} onCancel={onCancel}>
        <div>x</div>
      </BandwidthGuard>
    );
    fireEvent.click(screen.getByRole("button", { name: /cancel/i }));
    expect(onCancel).toHaveBeenCalled();
  });
});
