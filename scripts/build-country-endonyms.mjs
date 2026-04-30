#!/usr/bin/env node
// Generates services/frontend/public/country-endonyms.json from
// Wikidata SPARQL keyed by M49 codes from countries-110m.json.
// Usage: node scripts/build-country-endonyms.mjs
//
// For S2 we ship a hand-curated seed; running this script regenerates
// the JSON from Wikidata. Network access required.

import { readFile, writeFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

const __dirname = dirname(fileURLToPath(import.meta.url));
const TOPO = resolve(__dirname, "../services/frontend/public/countries-110m.json");
const OUT  = resolve(__dirname, "../services/frontend/public/country-endonyms.json");

const SPARQL = `https://query.wikidata.org/sparql`;
const LANGS = ["en", "de", "fr", "es", "it", "ru", "zh", "ja", "ar", "tr"];

async function sparql(query) {
  const res = await fetch(`${SPARQL}?query=${encodeURIComponent(query)}&format=json`, {
    headers: { "User-Agent": "ODIN-Worldview-Build/1.0", "Accept": "application/json" },
  });
  if (!res.ok) throw new Error(`SPARQL ${res.status}`);
  return (await res.json()).results.bindings;
}

async function main() {
  const topo = JSON.parse(await readFile(TOPO, "utf8"));
  const features = topo.objects.countries.geometries;
  const m49s = features.map((f) => f.id);

  const _topoIndex = {};
  const countries = {};

  for (const m49 of m49s) {
    // Wikidata properties:
    //   P2082 = UN M.49 code (string, e.g. "300" for Greece)
    //   P298  = ISO 3166-1 alpha-3 (string, e.g. "GRC")
    //   P1448 = official name (multilingual string)
    //   P1705 = native label (multilingual string)
    //   P36   = capital (item)
    //   P625  = coordinate location (geo:wktLiteral, "Point(lon lat)")
    const q = `
      SELECT ?iso3 ?label ?official ?capital ?capitalLabel ?capitalCoord
      ${LANGS.map((l) => `?label_${l} ?endo_${l}`).join(" ")}
      WHERE {
        ?c wdt:P2082 "${m49}".
        OPTIONAL { ?c wdt:P298 ?iso3. }
        OPTIONAL { ?c wdt:P1448 ?official. FILTER(LANG(?official) = "en") }
        OPTIONAL { ?c wdt:P36 ?capital. ?capital wdt:P625 ?capitalCoord. }
        ${LANGS.map((l) => `OPTIONAL { ?c rdfs:label ?label_${l}. FILTER(LANG(?label_${l}) = "${l}") }`).join("\n")}
        ${LANGS.map((l) => `OPTIONAL { ?c wdt:P1705 ?endo_${l}. FILTER(LANG(?endo_${l}) = "${l}") }`).join("\n")}
        SERVICE wikibase:label { bd:serviceParam wikibase:language "en". }
      }
      LIMIT 1
    `;
    try {
      const rows = await sparql(q);
      const row = rows[0];
      if (!row || !row.iso3) {
        _topoIndex[m49] = null;
        continue;
      }
      const iso3 = row.iso3.value;
      _topoIndex[m49] = iso3;
      const endonyms = {};
      for (const l of LANGS) {
        const v = row[`endo_${l}`]?.value ?? row[`label_${l}`]?.value;
        if (v) endonyms[l] = v;
      }
      countries[iso3] = {
        iso3,
        m49,
        names: {
          en: row[`label_en`]?.value ?? "",
          official: row.official?.value ?? "",
          native: row[`endo_${LANGS[0]}`]?.value ?? "",
          endonyms,
        },
        capital: row.capitalCoord
          ? {
              name: row.capitalLabel?.value ?? "",
              ...parsePoint(row.capitalCoord.value),
            }
          : null,
      };
    } catch (e) {
      console.error(`M49 ${m49}: ${e.message}`);
      _topoIndex[m49] = null;
    }
    // Rate-limit politeness
    await new Promise((r) => setTimeout(r, 200));
  }

  await writeFile(OUT, JSON.stringify({ _topoIndex, countries }, null, 2));
  console.log(`Wrote ${OUT}: ${Object.keys(countries).length}/${m49s.length} mapped.`);
}

function parsePoint(wkt) {
  // "Point(23.7275 37.9838)"
  const m = /Point\(([-\d.]+)\s+([-\d.]+)\)/.exec(wkt);
  return m ? { lon: parseFloat(m[1]), lat: parseFloat(m[2]) } : { lon: 0, lat: 0 };
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
