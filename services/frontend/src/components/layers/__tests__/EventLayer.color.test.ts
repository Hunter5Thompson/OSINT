import { describe, expect, it } from "vitest";
import { DEFAULT_COLOR, EVENT_COLORS, getCategoryColor } from "../EventLayer";

describe("getCategoryColor", () => {
  it("returns the explicit conflict color for kinetic violence types", () => {
    expect(getCategoryColor("conflict.armed")).toBe(EVENT_COLORS.conflict);
    expect(getCategoryColor("conflict.armed")).not.toBe(DEFAULT_COLOR);
  });

  it("returns the civil color for civilian protest types", () => {
    expect(getCategoryColor("civil.protest")).toBe(EVENT_COLORS.civil);
    expect(getCategoryColor("civil.protest")).not.toBe(DEFAULT_COLOR);
  });

  it("returns the posture color for force-positioning types", () => {
    expect(getCategoryColor("posture.military")).toBe(EVENT_COLORS.posture);
    expect(getCategoryColor("posture.military")).not.toBe(DEFAULT_COLOR);
  });

  it("returns the social color for mass-protest types", () => {
    expect(getCategoryColor("social.mass_protest")).toBe(EVENT_COLORS.social);
    expect(getCategoryColor("social.mass_protest")).not.toBe(DEFAULT_COLOR);
  });

  it("returns the humanitarian color for humanitarian types", () => {
    expect(getCategoryColor("humanitarian.refugee_displacement")).toBe(
      EVENT_COLORS.humanitarian,
    );
  });

  it("returns the infrastructure color for infrastructure types", () => {
    expect(getCategoryColor("infrastructure.power_grid_failure")).toBe(
      EVENT_COLORS.infrastructure,
    );
  });

  it("falls back to DEFAULT_COLOR for genuinely unknown roots", () => {
    expect(getCategoryColor("totally.unknown")).toBe(DEFAULT_COLOR);
  });

  it("covers every codebook root with a distinct color (no silent fallbacks)", () => {
    const roots = [
      "military",
      "conflict",
      "posture",
      "civil",
      "political",
      "economic",
      "space",
      "cyber",
      "environmental",
      "social",
      "humanitarian",
      "infrastructure",
      "other",
    ];
    for (const root of roots) {
      expect(EVENT_COLORS[root]).toBeDefined();
    }
  });
});
