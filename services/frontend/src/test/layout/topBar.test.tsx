/**
 * TopBar tests (ODIN S1 · Task 7).
 *
 * Verifies the persistent top navigation bar:
 *  - Brand: Orrery (size s) + "Hlíðskjalf" wordmark.
 *  - Middle: HOME / WORLDVIEW / BRIEFING / WAR ROOM NavLinks.
 *  - Active tab gets an Amber dot prefix.
 *  - War Room (when not active) shows a static Sentinel dot (no animation).
 *  - Right side: UTC timestamp (DD·MMM·YY / HH:MMZ) + coarse location
 *    (UTC±HH offset or literal "LOCAL").
 *  - Timestamp region has aria-live="polite" and ticks at least every 60s.
 *  - No pulse / animation at S1 (reduced-motion sanity).
 */
import { describe, it, expect, afterEach, beforeEach, vi } from "vitest";
import { render, cleanup, screen, within, act } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { TopBar } from "../../components/hlidskjalf/TopBar";

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <TopBar />
    </MemoryRouter>,
  );
}

function getLink(name: RegExp) {
  return screen.getByRole("link", { name });
}

afterEach(() => {
  cleanup();
});

describe("<TopBar /> — brand + nav", () => {
  it("renders the Hlíðskjalf wordmark and an Orrery marker", () => {
    renderAt("/");
    expect(screen.getByText("Hlíðskjalf")).toBeInTheDocument();
    // Orrery marks itself with data-orrery="true" in its root <svg>.
    const orrery = document.querySelector('[data-orrery="true"]');
    expect(orrery).not.toBeNull();
  });

  it("renders the four navigation tabs", () => {
    renderAt("/");
    expect(getLink(/^home$/i)).toBeInTheDocument();
    expect(getLink(/^worldview$/i)).toBeInTheDocument();
    expect(getLink(/^briefing$/i)).toBeInTheDocument();
    expect(getLink(/^war room$/i)).toBeInTheDocument();
  });
});

describe("<TopBar /> — active tab indicator (amber dot)", () => {
  it("prefixes the active tab with an Amber dot", () => {
    renderAt("/worldview");
    const worldview = getLink(/^worldview$/i);
    const dot = worldview.querySelector('[data-tab-dot="active"]');
    expect(dot).not.toBeNull();
    const style = (dot as HTMLElement).getAttribute("style") ?? "";
    // Amber is referenced via CSS variable.
    expect(style.toLowerCase()).toMatch(/var\(--amber\)/);
  });

  it("does not prefix inactive tabs with an Amber active dot", () => {
    renderAt("/worldview");
    const home = getLink(/^home$/i);
    expect(home.querySelector('[data-tab-dot="active"]')).toBeNull();
  });
});

describe("<TopBar /> — War Room muted sentinel dot", () => {
  it("shows a static Sentinel dot on War Room when it is NOT the active route", () => {
    renderAt("/worldview");
    const warRoom = getLink(/^war room$/i);
    const sentinelDot = warRoom.querySelector('[data-tab-dot="sentinel"]');
    expect(sentinelDot).not.toBeNull();
    const style = (sentinelDot as HTMLElement).getAttribute("style") ?? "";
    expect(style.toLowerCase()).toMatch(/var\(--sentinel\)/);
    // Must be static — no CSS animation property.
    expect(style.toLowerCase()).not.toMatch(/animation/);
    // No pulse marker attribute either.
    expect((sentinelDot as HTMLElement).getAttribute("data-pulse")).toBeNull();
  });

  it("shows the Amber active dot (not Sentinel) when War Room IS the active route", () => {
    renderAt("/warroom");
    const warRoom = getLink(/^war room$/i);
    expect(warRoom.querySelector('[data-tab-dot="active"]')).not.toBeNull();
    expect(warRoom.querySelector('[data-tab-dot="sentinel"]')).toBeNull();
  });

  it("has no animation applied to any tab dot anywhere in the TopBar", () => {
    renderAt("/worldview");
    const dots = document.querySelectorAll('[data-tab-dot]');
    expect(dots.length).toBeGreaterThan(0);
    for (const dot of Array.from(dots)) {
      const style = (dot as HTMLElement).getAttribute("style") ?? "";
      expect(style.toLowerCase()).not.toMatch(/animation/);
    }
  });
});

describe("<TopBar /> — timestamp + coarse location", () => {
  it("renders a UTC timestamp in the shape DD·MMM·YY / HH:MMZ", () => {
    renderAt("/");
    const region = screen.getByTestId("topbar-clock");
    // Expected shape e.g.: 14·APR·26 / 16:42Z
    expect(region.textContent ?? "").toMatch(
      /\d{2}·[A-Z]{3}·\d{2}\s*\/\s*\d{2}:\d{2}Z/,
    );
  });

  it("renders a coarse location — UTC±HH offset or LOCAL fallback", () => {
    renderAt("/");
    const region = screen.getByTestId("topbar-clock");
    const txt = region.textContent ?? "";
    expect(txt).toMatch(/UTC[+-]\d{2}|LOCAL/);
  });

  it("marks the timestamp region with aria-live='polite'", () => {
    renderAt("/");
    const region = screen.getByTestId("topbar-clock");
    expect(region.getAttribute("aria-live")).toBe("polite");
  });
});

describe("<TopBar /> — timestamp ticks", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-04-14T16:42:00Z"));
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("updates the rendered timestamp after 65 seconds", async () => {
    renderAt("/");
    const region = screen.getByTestId("topbar-clock");
    const initial = region.textContent ?? "";
    expect(initial).toMatch(/16:42Z/);

    await act(async () => {
      vi.setSystemTime(new Date("2026-04-14T16:43:05Z"));
      await vi.advanceTimersByTimeAsync(65_000);
    });

    const updated = screen.getByTestId("topbar-clock").textContent ?? "";
    expect(updated).toMatch(/16:43Z/);
    expect(updated).not.toBe(initial);
  });
});

describe("<TopBar /> — no pulse animation anywhere", () => {
  it("has no element carrying inline CSS animation inside the TopBar", () => {
    renderAt("/worldview");
    const header = screen.getByRole("banner");
    const all = header.querySelectorAll("[style]");
    for (const el of Array.from(all)) {
      const style = (el as HTMLElement).getAttribute("style") ?? "";
      expect(style.toLowerCase()).not.toMatch(/animation\s*:/);
    }
    // Sanity: the sentinel dot should be discoverable under War Room link.
    const warRoom = within(header).getByRole("link", { name: /^war room$/i });
    expect(warRoom.querySelector('[data-tab-dot="sentinel"]')).not.toBeNull();
  });
});
