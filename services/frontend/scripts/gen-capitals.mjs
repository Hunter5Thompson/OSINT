// services/frontend/scripts/gen-capitals.mjs
// Regenerates public/country-endonyms.json capital coverage from Natural Earth
// (public domain). Requires network. Run: node scripts/gen-capitals.mjs
// Preserves the 8 existing curated entries; only fills gaps.
import { readFileSync, writeFileSync } from "node:fs";

const NE = "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson";
const COUNTRIES_URL = `${NE}/ne_110m_admin_0_countries.geojson`;
const PLACES_URL = `${NE}/ne_10m_populated_places_simple.geojson`;

const OVERRIDES = {
  // Kosovo carries an explicit `name`: NE has no XKX row, so nameByIso3["XKX"] is
  // empty and the country name would otherwise fall back to the capital ("Pristina").
  Kosovo: { iso3: "XKX", name: "Kosovo", capital: { name: "Pristina", lat: 42.6727, lon: 21.1655 } },
  "732": { iso3: "ESH", capital: { name: "Laâyoune", lat: 27.1536, lon: -13.2033 } },
  "238": { iso3: "FLK", capital: { name: "Stanley", lat: -51.6938, lon: -57.8569 } },
  "304": { iso3: "GRL", capital: { name: "Nuuk", lat: 64.1836, lon: -51.6926 } },
  "540": { iso3: "NCL", capital: { name: "Nouméa", lat: -22.2758, lon: 166.458 } },
  "630": { iso3: "PRI", capital: { name: "San Juan", lat: 18.4655, lon: -66.1057 } },
  "275": { iso3: "PSE", capital: { name: "Ramallah", lat: 31.9038, lon: 35.2034 } },
  "260": { iso3: "ATF", capital: { name: "Port-aux-Français", lat: -49.3492, lon: 70.2197 } },
};

const endoPath = new URL("../public/country-endonyms.json", import.meta.url);
const endo = JSON.parse(readFileSync(endoPath, "utf8"));

const fetchJson = async (u) => (await fetch(u)).json();
const [countries, places] = await Promise.all([fetchJson(COUNTRIES_URL), fetchJson(PLACES_URL)]);

const pad3 = (v) => String(parseInt(String(v), 10)).padStart(3, "0");
const pickA3 = (p) =>
  [p.ISO_A3, p.iso_a3, p.ADM0_A3, p.adm0_a3].find((v) => v && v !== "-99");

const A3_TO_M49 = { FRA: "250", NOR: "578" };

const iso3ByM49 = {};
const nameByIso3 = {};
for (const f of countries.features) {
  const p = f.properties;
  const a3 = pickA3(p);
  if (!a3) continue;
  nameByIso3[a3] = p.NAME ?? p.name ?? p.ADMIN ?? p.admin ?? a3;
  let n3 = pad3(p.ISO_N3 ?? p.iso_n3);
  if (n3 === "-99" || n3 === "NaN") n3 = A3_TO_M49[a3] ?? null;
  if (n3) iso3ByM49[n3] = a3;
}

const capByIso3 = {};
const rank = (fcla) => (fcla === "Admin-0 capital" ? 0 : fcla?.startsWith("Admin-0 capital") ? 1 : 2);
for (const f of places.features) {
  const p = f.properties;
  if (!String(p.featurecla ?? "").startsWith("Admin-0 capital")) continue;
  const a3 = p.adm0_a3 ?? p.ADM0_A3;
  if (!a3 || a3 === "-99") continue;
  const lat = Number(p.latitude ?? p.LATITUDE ?? f.geometry?.coordinates?.[1]);
  const lon = Number(p.longitude ?? p.LONGITUDE ?? f.geometry?.coordinates?.[0]);
  const name = p.name ?? p.NAME;
  const cand = { name, lat, lon, _r: rank(p.featurecla) };
  if (!capByIso3[a3] || cand._r < capByIso3[a3]._r) capByIso3[a3] = cand;
}

let filled = 0;
for (const [m49, existing] of Object.entries(endo._topoIndex)) {
  if (existing) continue;
  let iso3 = iso3ByM49[m49] ?? null;
  let capital = iso3 ? capByIso3[iso3] : null;
  if (OVERRIDES[m49]) {
    iso3 = OVERRIDES[m49].iso3;
    capital = OVERRIDES[m49].capital;
  }
  if (iso3 && capital && Number.isFinite(capital.lat) && Number.isFinite(capital.lon)) {
    endo._topoIndex[m49] = iso3;
    const nm = OVERRIDES[m49]?.name ?? nameByIso3[iso3] ?? capital.name ?? iso3;
    endo.countries[iso3] = {
      iso3,
      m49: /^\d+$/.test(m49) ? m49 : (endo.countries[iso3]?.m49 ?? ""),
      names: { en: nm, official: nm, native: nm, endonyms: {} },
      capital: { name: capital.name, lat: capital.lat, lon: capital.lon },
    };
    filled++;
  }
}

writeFileSync(endoPath, JSON.stringify(endo, null, 2) + "\n");
console.log(`filled ${filled} countries; total countries=${Object.keys(endo.countries).length}`);
