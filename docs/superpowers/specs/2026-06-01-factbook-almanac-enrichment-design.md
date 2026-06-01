# CIA World Factbook Almanac Enrichment — Design Spec (rev. 2)

**Datum:** 2026-06-01
**Status:** Proposed
**Scope:** Den Country Almanac mit kuratiert-tiefen Daten aus dem CIA World Factbook befüllen, erzeugt von einem **deterministischen, offline rendernden** Builder, der den committeten statischen Seed produziert.

> **rev. 2** verarbeitet ein Review (8 Findings): 3er-Key-Kollision der Kartenentitäten, nicht erfüllbare Integrity-Assertions (Antarctica/Westsahara), Nicht-Determinismus (REST live + `generated_at`), GEC→Pfad-Auflösung, gepinnte Factbook-Revision, CLI-Konvention, Koordinaten-Plausibilität, HTML-Vielfalt.

## 1. Motivation

Der Almanac liefert pro Land nur ~4 dünne Felder (REST Countries). Economy und Security — für ein Lagebild zentral — sind faktisch leer. Das CIA World Factbook bietet pro Land ~30 Economy- und ~7 Military/Security-Felder. Dieser Spec deckt **nur die Daten-Anreicherung** ab (Teil 1 von 2; Teil 2 = Munin-Lagebericht, eigener Spec).

## 2. Non-Goals

- **Kein** Munin/Briefing-Generator (separater Folge-Spec).
- **Keine** Schema-Änderung am `facts: {profile,people,government,economy,security: [{label,value}]}`-Modell (additives Top-Level-`_meta` ausgenommen, §8).
- **Keine** Schema-/Store-Refactors. Die 3 Kartenstubs bekommen eindeutige Keys über das **bestehende** `id`-Feld (§3.3) — kein neues Modellfeld. Eine **minimale** Frontend-Anpassung kann nötig sein, falls die Country-Features dieser 3 einen anderen Key senden als der Seed führt; das wird beim Implementieren am echten Country-Layer verifiziert (kein Komponenten-Umbau).
- **Kein** Runtime-Netzzugriff.

## 3. Datenquellen — Refresh vs. Render getrennt (Determinismus)

Der Builder hat zwei Modi. **Refresh** (selten, mit Netz) holt die externen Quellen und schreibt **committete, normalisierte Snapshots**. **Render** (offline, deterministisch, CI-fähig) liest nur committete Inputs und schreibt den Seed. Render erzeugt **keine** Zeitstempel und macht **keine** Netzaufrufe.

### 3.1 CIA World Factbook (gepinnte Revision)
Das Factbook wurde am **2026-02-04 abgeschaltet** (CIA-Sunset); das `factbook/factbook.json`-Repo wird seither nur noch redaktionell gepflegt. Gepinnte Revision:
```
factbook_revision      = 8662a8b17a784841ab4528631b04090eb2f183eb
factbook_revision_date = 2026-05-17
cia_sunset_date        = 2026-02-04
```
**Refresh** holt das Tarball dieser Revision **einmal**, baut einen `gec → Dateipfad`-Index (Dateien liegen in Regionsordnern, z.B. `europe/gm.json` — ein bloßer GEC reicht nicht zum Lokalisieren), validiert die Eindeutigkeit der GEC-Dateinamen am gepinnten Snapshot, extrahiert die kuratierten Felder (§5) und schreibt einen normalisierten `services/data-ingestion/infra_atlas/data/factbook_snapshot.json` (committet). Public Domain.

### 3.2 REST Countries (vendored Snapshot)
Hauptstadt-Koordinaten + Fläche/Bevölkerung-Fallback. **Refresh** holt REST Countries einmal und schreibt ein normalisiertes, committetes `infra_atlas/data/restcountries_snapshot.json`. **Render zieht REST NICHT live** (sonst nicht-deterministisch). Refresh setzt zudem den expliziten `refreshed_at`-Wert (kein `Date.now()` im Render).

### 3.3 Vendorter Crosswalk (einziger Join-Key, mit eindeutigen Map-Keys)
`infra_atlas/data/crosswalk.json` — kanonische Länderliste, die für **jeden** der **genau 177** Einträge folgende Schlüssel explizit zusammenführt:
```json
{ "name": "Germany", "topo_id": "DEU", "m49": "276", "iso3": "DEU", "gec": "gm" }
```
- `topo_id` = der stabile Identifier, mit dem das Frontend die Karten-Polygone auflöst (beim Implementieren aus den Country-Feature-Properties bestimmt). Er ist **kein neues Seed-/Modellfeld**: im generierten Seed wird er über das **bestehende** `id`-Feld realisiert (der Store keyt bereits nach `id`/`m49`/`iso3`). Falls die Features dieser 3 einen abweichenden Key senden, wird das am Country-Layer verifiziert (§2).
- **Behebt die 3er-Kollision:** im aktuellen Seed haben **Kosovo, N. Cyprus, Somaliland** alle `id = "undefined"` → der Store löst nur einen auf (zuletzt geladenen). Der Crosswalk gibt jedem einen **eindeutigen** Key:
  - **Kosovo:** `topo_id: "Kosovo"`, `iso3: "XKX"`, `gec: "kv"`, `m49: "Kosovo"` (nicht-numerischer String-Platzhalter, nie `null` — sonst bricht `_norm_id(country.m49)`).
  - **N. Cyprus:** `topo_id: "N. Cyprus"`, `iso3: null`, `gec: ""`, `m49: "N. Cyprus"`.
  - **Somaliland:** `topo_id: "Somaliland"`, `iso3: null`, `gec: ""`, `m49: "Somaliland"`.
- `m49` ist im Seed/Store **stets ein String** (nie `null`); Einträge ohne echten M49 tragen ihren Namen als Platzhalter.

## 4. Builder

**Erweiterung des bestehenden infra_atlas-CLI** (Korrektur 6): es gibt **kein** `odin-build-*`-Skript; das Muster ist `services/data-ingestion/infra_atlas/cli.py` → `odin-infra-atlas <subcommand>`. Neuer Subcommand **`odin-infra-atlas almanac`** (Render) und **`odin-infra-atlas almanac --refresh`** (Refresh). Neues Modul `infra_atlas/build_country_almanac.py`. `pyproject.toml` Package-Data um `infra_atlas/data/*.json` ergänzen (aktuell nur `seeds/*.{yaml,json}`).

**Render — Kern-Invariante:** reine Funktion aus `{crosswalk.json, factbook_snapshot.json, restcountries_snapshot.json, country_almanac_overrides.json}`. Liest **niemals** den eigenen Output (`country_almanac.json`). Keine Netz-/Zeit-Aufrufe. Jeder Lauf regeneriert vollständig → kein Kleben veralteter Werte.

Render-Pipeline:
1. Crosswalk laden → 177 kanonische Einträge.
2. Pro Eintrag: Factbook-Felder aus `factbook_snapshot.json` (via `gec`), bereinigt (§5).
3. Hauptstadt-Coords aus `restcountries_snapshot.json` (via `iso3`), mit **Plausibilitätscheck** (§5).
4. Facts pro Sektion (§5).
5. **Overrides zuletzt** anwenden (§6).
6. `_meta` setzen (§8), Seed deterministisch schreiben (`ensure_ascii=False`, `indent=2`, sortierte Komposit-Teile).

## 5. Kuratiertes Feld-Mapping + Bereinigung

Sektionen (jedes Subfeld → ein `{label, value}`; ~40-50 Facts/Land):
- **profile:** Background (gekürzt), Area, Climate, Natural resources
- **people:** Population, Median age, Population growth rate, Urbanization, Life expectancy, Ethnic groups, Religions, Languages, Literacy
- **government:** Government type, Capital, Independence, Chief of state, Head of government, Legislative branch, Suffrage
- **economy:** Real GDP (PPP), Real GDP per capita, Real GDP growth rate, Inflation, GDP composition by sector, Industries, Labor force, Unemployment rate, Youth unemployment, Public debt, Exports (+ partners, + commodities), Imports (+ partners), Exchange rates
- **security:** Military expenditures (neuestes Jahr, ggf. + Vorjahr), Military and security forces, Personnel strengths, Service age/obligation, Deployments, Military - note

**Bereinigung (Korrektur 8):** Werte mit einem **HTML-Parser** säubern (nicht nur `<b>` strippen) — die Quelle enthält auch `<strong>`, `<br>`, `<em>` und HTML-Entities. Tags entfernen, `<br>` → Leerzeichen, Entities unescapen, Whitespace kollabieren, Jahres-Suffix („(2024 est.)") behalten. Mehrjahres-Felder → neuestes Jahr. Komposit (GDP by sector) → `"agriculture 0.8% · industry 25.8% · services 63.9%"`.

**Koordinaten-Plausibilität (Korrektur 7):** REST liefert teils unplausible/vertauschte Coords (im aktuellen Seed: El Aaiún `lat=-13.28, lon=27.14` — vertauscht). Render prüft jede Hauptstadt-Coord gegen das Länder-Bounding/Centroid; bei Implausibilität → Override (§6) oder weglassen, nicht blind übernehmen. ESH bekommt einen expliziten Coord-Override.

## 6. Overrides (einzige Quelle manueller Fakten)

`services/backend/data/country_almanac_overrides.json` — **einzige** Quelle manueller Fakten/Korrekturen, zuletzt angewandt, label-dedupliziert (Override gewinnt), keyed nach `topo_id`/`iso3`:
```json
{ "ESH": { "capital": { "name": "El Aaiún", "lat": 27.15, "lon": -13.20 } },
  "USA": { "facts": { "security": [{ "label": "ODIN note", "value": "..." }] } } }
```
Wird **nicht** aus dem alten Seed zurückgelesen. Da Factbook government/military für jedes Land liefert, hält das File initial nur ODIN-Editorials + Coord-Fixes (z.B. ESH).

## 7. Baseline + Reihenfolge

PR #29 (Packaging `COPY data/`, iso3-Backfill, Seed-Integrity-Test) **und** PR #30 (Satellite-Fix) sind **bereits in `main` gemergt** (Merges `5f07911`, `24798c2`). Die Packaging-/iso3-/Integrity-Baseline ist also vorhanden; der Implementierungs-Branch wird auf aktuellem `main` basiert. Der Builder **ersetzt** die manuelle REST-Countries-Anreicherung aus #29 (REST bleibt nur als vendored Coords/Fallback-Quelle).

## 8. Schema + `_meta`

Modell unverändert. Additives Top-Level-`_meta` im Seed:
```json
"_meta": { "factbook_revision": "8662a8b…", "factbook_revision_date": "2026-05-17",
           "cia_sunset_date": "2026-02-04", "refreshed_at": "<explizit, kein Date.now()>",
           "builder": "odin-infra-atlas almanac" }
```
Der Loader liest nur `raw.get("countries", [])` → `_meta` wird ignoriert, keine Modell-Änderung.

## 9. Tests / Guardrails

**Builder-Unit** (`services/data-ingestion/tests/test_build_country_almanac.py`):
- HTML-Cleaner: `<b>`, `<strong>`, `<br>`, `<em>` + Entities → sauberer Text; Jahres-Suffix bleibt.
- Mehrjahres-Selektor (neuestes Jahr); Komposit-Formatter.
- gec→Pfad-Index am Snapshot eindeutig; Resolver für Majors + Kosovo.
- Crosswalk: **exakt 177 Einträge, keine doppelten `topo_id`/`id`/Fallback-Keys**; alle 3 Karten-Topo-IDs (Kosovo/N. Cyprus/Somaliland) auflösbar.
- Coord-Plausibilität: vertauschte/außerhalb-Bounding Coords werden erkannt; ESH-Override greift.
- Overrides zuletzt + Label-Dedup; Render ignoriert vorhandenes `country_almanac.json`.
- **Determinismus:** zweimaliges Render auf identischen Inputs → byte-identischer Output.

**Seed-Integrity** (`services/backend/tests/test_almanac_seed_integrity.py`, erweitert — **erfüllbar** gemacht, Korrektur 2):
- **Source-Coverage statt „jedes ISO-Land":** jedes Land **mit Factbook-Profil** hat economy- UND security-Facts. Begründete **Allowlist** für Einträge ohne (Teil-)Factbook-Daten: **Antarctica (ATA)** (Factbook führt bewusst keine Economy), **Western Sahara (ESH)** (seit 2020 nicht mehr im Factbook), Kosovo/N. Cyprus/Somaliland (Karten-Stubs). Fehlende Profile → **REST-Fallback-Stub** (nicht übersprungen).
- **kein rohes HTML** (`<`) in irgendeinem `value`.
- **exakt 177 Einträge, keine Key-Kollisionen** (id/topo_id eindeutig).
- bestehende Guardrails (iso3-Coverage, Population+Capital, Dockerfile packt `data/`) bleiben; `_meta.factbook_revision` gesetzt.

**Backend-Suite** grün (Baseline 269); ruff sauber.

## 10. Risiken

- **Crosswalk/topo_id-Vollständigkeit:** vendored + reviewt; die `topo_id`s müssen zu den echten Frontend-Feature-Properties passen (beim Implementieren verifizieren). Fehlender Code → Stub (geloggt), kein Crash.
- **Eingefrorener Snapshot:** fixer Stand (Revision `8662a8b…`, 2026-05-17); `_meta` dokumentiert es offen. Refresh = SHA bumpen + `--refresh` + committen.
- **Antarctica/Westsahara:** keine vollständigen Factbook-Profile → Allowlist + REST-Stub, kein erzwungenes economy/security.
- **Determinismus:** durch committete Snapshots + expliziten `refreshed_at` garantiert; Render byte-stabil (Test).

## 11. Offene Folge-Arbeit (außerhalb dieses Specs)

- **Teil 2:** Munin-Lagebericht pro Land (Almanac-Facts + gematchte Live-Signale `/almanac/countries/{id}/signals` + RAG/Graph → Synthese). Eigener Spec.
