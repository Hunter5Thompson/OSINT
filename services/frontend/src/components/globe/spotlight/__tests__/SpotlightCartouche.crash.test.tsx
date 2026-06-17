import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import { renderCartouche } from "../SpotlightCartouche";

describe("renderCartouche for a generated country", () => {
  it("does not throw when the endonym datum has no full `names` object", () => {
    const target = {
      kind: "country", trigger: "country", m49: "250", iso3: "FRA",
      polygon: { type: "Polygon", coordinates: [] }, name: "France", capital: null,
    } as unknown as Parameters<typeof renderCartouche>[0];
    const endo = { countries: { FRA: { iso3: "FRA", m49: "250" } } } as never;
    expect(() => render(<>{renderCartouche(target, endo)}</>)).not.toThrow();
  });
});
