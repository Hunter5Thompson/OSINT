import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import { renderCartouche } from "../SpotlightCartouche";

describe("renderCartouche", () => {
  it("idle → renders nothing", () => {
    expect(renderCartouche(null)).toBeNull();
  });

  it("circle → renders coordinate cartouche", () => {
    const r = renderCartouche({
      kind: "circle", trigger: "pin",
      center: { lon: 41.87, lat: 36.34 }, radius: 1, altitude: 312_000,
      label: "Sinjar Ridge",
    });
    const { container } = render(<>{r}</>);
    expect(container.textContent).toContain("Sinjar Ridge");
    expect(container.textContent).toMatch(/36\.34/);
  });

  it("country GRC with endonyms → renders Greece title + cartouche stack", () => {
    const r = renderCartouche(
      {
        kind: "country", trigger: "country",
        m49: "300", iso3: "GRC",
        polygon: { type: "Polygon", coordinates: [[[0,0],[1,0],[1,1],[0,1],[0,0]]] },
        name: "Greece",
        capital: { name: "Athens", coords: { lon: 23.7275, lat: 37.9838 } },
      },
      {
        countries: {
          GRC: { iso3: "GRC", names: { en: "Greece", official: "Hellenic Republic", native: "Ελληνική Δημοκρατία", endonyms: { el: "Ελλάδα", de: "Griechenland", ru: "Греция" } } },
        },
      }
    );
    const { container } = render(<>{r}</>);
    expect(container.textContent).toContain("Greece");
  });

  it("country fallback (iso3 = null) → renders display name only", () => {
    const r = renderCartouche({
      kind: "country", trigger: "country",
      m49: "732", iso3: null,
      polygon: { type: "Polygon", coordinates: [[[0,0],[1,0],[1,1],[0,1],[0,0]]] },
      name: "W. Sahara", capital: null,
    });
    const { container } = render(<>{r}</>);
    expect(container.textContent).toContain("W. Sahara");
  });
});
