// services/frontend/src/components/globe/__tests__/capitalCoverage.test.ts
import { describe, it, expect } from "vitest";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

// Genuinely capital-less / unmappable features, intentionally left unmapped:
//  - 'Somaliland', 'N. Cyprus' (name-keyed, no clean ISO3 / no NE admin-0 capital)
//  - '010' Antarctica (resolves to ATA but has no capital — only research stations)
// Kosovo is NOT excepted — it is covered via the generator's OVERRIDES['Kosovo']
// (-> XKX/Pristina); the explicit assertion below enforces that coupling.
const CAPITAL_EXCEPTIONS = new Set<string>(["Somaliland", "N. Cyprus", "010"]);

function load(rel: string) {
  // NOTE: string concat (not a template literal) is intentional — Vite 6 rewrites
  // `new URL(`...${expr}`, import.meta.url)` as a dynamic-asset URL, which collapses
  // the path to `/public/...` under vitest. Concatenation bypasses that transform.
  const p = fileURLToPath(new URL("../../../../public/" + rel, import.meta.url));
  return JSON.parse(readFileSync(p, "utf8"));
}

describe("capital coverage", () => {
  it("every real countries-110m feature resolves to a capital or is an explicit exception", () => {
    const topo = load("countries-110m.json");
    const endo = load("country-endonyms.json");
    const topoIndex: Record<string, string | null> = endo._topoIndex;
    const countries: Record<string, { capital: { name: string; lat: number; lon: number } | null }> =
      endo.countries;

    const geometries: Array<{ id?: string | number; properties?: { name?: string } }> =
      topo.objects.countries.geometries;
    const keys = geometries.map((g) =>
      g.id != null ? String(g.id) : (g.properties?.name ?? ""),
    );

    const missing: string[] = [];
    for (const key of keys) {
      if (CAPITAL_EXCEPTIONS.has(key)) continue;
      const iso3 = topoIndex[key] ?? null;
      const cap = iso3 ? countries[iso3]?.capital : null;
      const ok =
        !!cap &&
        typeof cap.name === "string" &&
        cap.name.length > 0 &&
        Number.isFinite(cap.lat) &&
        Math.abs(cap.lat) <= 90 &&
        Number.isFinite(cap.lon) &&
        Math.abs(cap.lon) <= 180;
      if (!ok) missing.push(key);
    }
    expect(missing).toEqual([]);
    expect(topoIndex["Kosovo"]).toBe("XKX");
  });
});
