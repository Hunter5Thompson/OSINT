import { describe, it, expect } from "vitest";
import { normalizeSeverity, severityRank, SEVERITY_ORDER } from "../severity";

describe("severity (frontend mirror)", () => {
  it("canonical order matches backend", () => {
    expect(SEVERITY_ORDER).toEqual(["unknown", "low", "medium", "high", "critical"]);
  });
  it("maps synonyms + null deterministically", () => {
    expect(normalizeSeverity("Elevated")).toBe("high");
    expect(normalizeSeverity("moderate")).toBe("medium");
    expect(normalizeSeverity(null)).toBe("unknown");
    expect(normalizeSeverity("banana")).toBe("unknown");
  });
  it("ranks unknown lowest", () => {
    expect(severityRank("unknown")).toBeLessThan(severityRank("critical"));
  });
});
