/**
 * Orrery + primitive tests (ODIN S1 · Task 3).
 *
 * Verifies:
 *  - `computeBodyPosition` pure function matches the spec physics (§2.5)
 *  - `<Orrery>` renders kernel, 3 tilted orbit rings, 3 body circles
 *  - Reduced-motion path (jsdom `[data-reduced-motion="true"]`) renders static
 *    and never calls `requestAnimationFrame`
 *  - A single rAF loop is shared across multiple mounted Orreries
 *  - Unmounting all Orreries releases the loop (no leaked frame)
 */
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { render, cleanup } from "@testing-library/react";
import {
  Orrery,
  computeBodyPosition,
  BODIES,
  __orreryEngine,
} from "../../components/hlidskjalf/Orrery";

function setReducedMotion(on: boolean) {
  if (on) {
    document.documentElement.setAttribute("data-reduced-motion", "true");
  } else {
    document.documentElement.removeAttribute("data-reduced-motion");
  }
}

describe("computeBodyPosition (pure physics)", () => {
  it("applies ellipse + tilt transform and depth at t=0, phi=0", () => {
    // θ = ω·0 + 0 = 0 → cos=1, sin=0 → (x0,y0) = (rx, 0)
    // tilt = -12° → x = rx·cos(-12°), y = rx·sin(-12°)
    const rx = 50;
    const ry = 18;
    const tilt = (-12 * Math.PI) / 180;
    const { x, y, opacity, scale } = computeBodyPosition(rx, ry, tilt, 0.35, 0, 0);
    expect(x).toBeCloseTo(rx * Math.cos(tilt), 5);
    expect(y).toBeCloseTo(rx * Math.sin(tilt), 5);
    // depth = (sin(0)+1)/2 = 0.5 → opacity 0.675, scale 0.95
    expect(opacity).toBeCloseTo(0.675, 5);
    expect(scale).toBeCloseTo(0.95, 5);
  });

  it("respects omega·t + phi for angle evolution", () => {
    // munin after 1s: θ = 0.35 rad
    const t = 1;
    const omega = 0.35;
    const phi = 0;
    const rx = 50;
    const ry = 18;
    const tilt = (-12 * Math.PI) / 180;
    const theta = omega * t + phi;
    const x0 = rx * Math.cos(theta);
    const y0 = ry * Math.sin(theta);
    const expectedX = x0 * Math.cos(tilt) - y0 * Math.sin(tilt);
    const expectedY = x0 * Math.sin(tilt) + y0 * Math.cos(tilt);
    const pos = computeBodyPosition(rx, ry, tilt, omega, phi, t);
    expect(pos.x).toBeCloseTo(expectedX, 5);
    expect(pos.y).toBeCloseTo(expectedY, 5);
  });
});

describe("BODIES spec", () => {
  it("includes munin, hugin, sentinel with correct orbital parameters", () => {
    const byName = Object.fromEntries(BODIES.map((b) => [b.name, b]));
    expect(byName.munin).toMatchObject({ rx: 50, ry: 18, omega: 0.35, phi: 0 });
    expect(byName.hugin).toMatchObject({ rx: 38, ry: 14, omega: -0.52, phi: 2.1 });
    expect(byName.sentinel).toMatchObject({ rx: 26, ry: 10, omega: 0.78, phi: 4.2 });
    // tilt stored as radians
    expect(byName.munin.tilt).toBeCloseTo((-12 * Math.PI) / 180, 5);
    expect(byName.hugin.tilt).toBeCloseTo((25 * Math.PI) / 180, 5);
    expect(byName.sentinel.tilt).toBeCloseTo((-4 * Math.PI) / 180, 5);
  });
});

describe("<Orrery />", () => {
  let rafSpy: ReturnType<typeof vi.spyOn>;
  let cafSpy: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    __orreryEngine.reset();
    rafSpy = vi.spyOn(window, "requestAnimationFrame");
    cafSpy = vi.spyOn(window, "cancelAnimationFrame");
  });

  afterEach(() => {
    cleanup();
    __orreryEngine.reset();
    setReducedMotion(false);
    rafSpy.mockRestore();
    cafSpy.mockRestore();
  });

  it("renders kernel, three orbit rings, three bodies", () => {
    setReducedMotion(true); // static, deterministic
    const { container } = render(<Orrery size="m" />);
    const svg = container.querySelector("svg");
    expect(svg).not.toBeNull();
    expect(container.querySelector('[data-part="kernel"]')).not.toBeNull();
    expect(container.querySelectorAll('[data-part="orbit"]').length).toBe(3);
    expect(container.querySelector('[data-body="munin"]')).not.toBeNull();
    expect(container.querySelector('[data-body="hugin"]')).not.toBeNull();
    expect(container.querySelector('[data-body="sentinel"]')).not.toBeNull();
  });

  it("renders a deterministic static SVG under reduced-motion", () => {
    setReducedMotion(true);
    const { container } = render(<Orrery size="m" />);
    // Snapshot stability: reduced-motion always uses θ=π/3 — serialize and assert.
    const svg = container.querySelector("svg");
    expect(svg?.outerHTML).toMatchInlineSnapshot(
      `"<svg xmlns="http://www.w3.org/2000/svg" viewBox="-60 -60 120 120" width="110" height="110" data-orrery="true" data-reduced="true" aria-hidden="true"><circle data-part="kernel" cx="0" cy="0" r="4" fill="var(--amber)"></circle><ellipse data-part="orbit" data-body="munin" cx="0" cy="0" rx="50" ry="18" fill="none" stroke="var(--granite)" stroke-width="0.5" transform="rotate(-12)"></ellipse><ellipse data-part="orbit" data-body="hugin" cx="0" cy="0" rx="38" ry="14" fill="none" stroke="var(--granite)" stroke-width="0.5" transform="rotate(25)"></ellipse><ellipse data-part="orbit" data-body="sentinel" cx="0" cy="0" rx="26" ry="10" fill="none" stroke="var(--granite)" stroke-width="0.5" transform="rotate(-4)"></ellipse><circle data-body="munin" cx="22.335221459030964" cy="16.070347728595566" r="2.4330127018922196" fill="var(--amber)" opacity="0.9991025731825897"></circle><circle data-body="hugin" cx="-5.817787448263943" cy="-10.21480868423283" r="2.069988636871097" fill="var(--sage)" opacity="0.8464525111999335"></circle><circle data-body="sentinel" cx="13.544475985511937" cy="3.575543526820923" r="1.2133883476483184" fill="var(--sentinel)" opacity="0.4405212943654226"></circle></svg>"`,
    );
  });

  it("does not call requestAnimationFrame under reduced-motion", () => {
    setReducedMotion(true);
    render(<Orrery size="s" />);
    render(<Orrery size="m" />);
    expect(rafSpy).not.toHaveBeenCalled();
  });

  it("shares a single rAF loop across multiple mounted orreries", () => {
    setReducedMotion(false);
    const { unmount: u1 } = render(<Orrery size="s" />);
    const callsAfter1 = rafSpy.mock.calls.length;
    expect(callsAfter1).toBe(1);
    const { unmount: u2 } = render(<Orrery size="m" />);
    const { unmount: u3 } = render(<Orrery size="l" />);
    // Additional mounts should NOT schedule additional rAFs until the loop ticks.
    expect(rafSpy.mock.calls.length).toBe(1);
    expect(__orreryEngine.subscriberCount()).toBe(3);
    u1();
    u2();
    u3();
    expect(__orreryEngine.subscriberCount()).toBe(0);
  });

  it("releases the rAF loop when the last subscriber unmounts", () => {
    setReducedMotion(false);
    const { unmount } = render(<Orrery size="s" />);
    expect(rafSpy).toHaveBeenCalledTimes(1);
    unmount();
    expect(cafSpy).toHaveBeenCalled();
    expect(__orreryEngine.isRunning()).toBe(false);
  });
});
