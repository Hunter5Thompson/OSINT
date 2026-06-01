# CIA World Factbook Almanac Enrichment — Design Spec

**Datum:** 2026-06-01
**Status:** Proposed
**Scope:** Den Country Almanac mit kuratiert-tiefen Daten aus dem CIA World Factbook befüllen, erzeugt von einem re-runnable, deterministischen Builder, der den committeten statischen Seed produziert.

## 1. Motivation

Der Almanac liefert pro Land nur ~4 dünne Felder (REST Countries: Fläche, Bevölkerung, Sprachen, Währung). Economy und Security — die für ein Lagebild zentralen Sektionen — sind faktisch leer. Das CIA World Factbook bietet pro Land ~30 Economy- und ~7 Military/Security-Felder. Dieser Spec deckt **nur die Daten-Anreicherung** ab; sie ist die erste Hälfte eines zweiteiligen Vorhabens (Teil 2 = Munin-Lagebericht pro Land, eigener Spec).

## 2. Non-Goals

- **Kein** Munin/Briefing-Generator (separater Folge-Spec).
- **Keine** Schema-Änderung: das flache `facts: {profile,people,government,economy,security: [{label,value}]}` bleibt — die Factbook-Tiefe passt als zusätzliche `{label,value}`-Einträge. Panel rendert beliebig viele Facts pro Tab bereits.
- **Keine** Frontend-Änderung.
- **Kein** Runtime-Netzzugriff: Anreicherung passiert zur Build-Zeit; Runtime serviert nur den statischen Seed.

## 3. Datenquellen

### 3.1 CIA World Factbook (gepinnter Snapshot)
Das CIA World Factbook wurde am **2026-02-04 abgeschaltet** (Sunset); `factbook.json` ist damit **kein wöchentlicher Feed mehr**, sondern ein eingefrorener Datenstand. Der Builder pinnt daher eine **explizite Revision** (Commit-SHA des `factbook/factbook.json`-Repos, zum Implementierungszeitpunkt festgelegt) und holt die Länder-JSONs ausschließlich von dieser Revision. Die Revision (SHA + Datum) wird festgehalten:
- als `_meta` Block am Kopf des generierten Seed (`{ "_meta": { "factbook_revision": "<sha>", "factbook_snapshot_date": "<date>", "generated_at": "<date>", "builder": "odin-build-almanac" } }`),
- und als Konstante im Builder.

**Refresh** = die gepinnte Revision manuell bumpen + Builder neu laufen + committen (dokumentiert im `_meta`). Public Domain (US-Gov), uneingeschränkt nutzbar.

### 3.2 Hauptstadt-Koordinaten + Strukturfelder
Factbook-Koordinaten sind unsauber. Hauptstadt `{name, lat, lon}` kommt weiterhin aus **REST Countries v3.1** (Build-Zeit-Abruf), Fläche/Bevölkerung als Fallback, falls Factbook für einen Eintrag fehlt.

### 3.3 Vendorter Crosswalk (einziger Join-Key)
`services/data-ingestion/infra_atlas/data/crosswalk_m49_iso3_gec.json` — eine vendored, reviewbare Tabelle, die für **jeden** Almanac-Eintrag `m49`, `iso3` und `gec` explizit zusammenführt. **Keine impliziten Code-Ableitungen mehr** (kein pycountry-zur-Laufzeit, keine ad-hoc GEC-Heuristik). Die Tabelle ist die kanonische Länderliste des Builders und enthält:
- alle 177 bisherigen Einträge,
- **Kosovo** (`iso3: XKX`, `gec: kv`; Kosovo hat keinen numerischen M49 → der bestehende nicht-numerische `m49`-Platzhalter des Seeds bleibt erhalten, damit das Store-Keying `_norm_id(country.m49)` nicht auf `None` bricht),
- die Karten-Stubs **N. Cyprus** und **Somaliland** (mit den Codes, die existieren; `gec` leer-String wo Factbook sie nicht führt → behalten Minimal-Stub).

Der `m49`-Wert ist im Seed/Store stets ein String (nie `null`) — Einträge ohne echten M49 behalten ihren bestehenden Platzhalter.

Format pro Eintrag:
```json
{ "name": "Germany", "m49": "276", "iso3": "DEU", "gec": "gm" }
```

## 4. Builder

**Neu:** `services/data-ingestion/infra_atlas/build_country_almanac.py` — Console-Script `odin-build-almanac` (analog zu den bestehenden infra_atlas-Buildern `odin-build-datacenters`/`-refineries`).

**Kern-Invariante (Korrektur 4):** Der Builder ist eine **reine Funktion** aus `{Crosswalk, gepinnter Factbook-Snapshot, REST-Countries-Coords, Overrides-Datei}`. Er liest **niemals** seinen eigenen vorherigen Output (`country_almanac.json`) wieder ein. Damit regeneriert jeder Lauf den Seed vollständig — kein dauerhaftes Kleben veralteter Werte.

Pipeline:
1. Crosswalk laden → kanonische Länderliste (m49/iso3/gec).
2. Pro Land: Factbook-JSON (gepinnte Revision, via `gec`) holen → kuratierte Felder extrahieren.
3. Werte **bereinigen**: HTML strippen (`<b>note:</b>` etc.), Whitespace kollabieren, Jahres-Suffix behalten („(2024 est.)"). Mehrjahres-Felder → **neuestes Jahr**. Komposite (GDP by sector) → `"agriculture 0.8% · industry 25.8% · services 63.9%"`.
4. Hauptstadt-Coords aus REST Countries (via `iso3`).
5. Facts pro Sektion aus dem kuratierten Mapping (§5) bauen.
6. **Overrides zuletzt anwenden** (§6).
7. `services/backend/data/country_almanac.json` schreiben (deterministisch: `ensure_ascii=False`, `indent=2`, sortierte Komposit-Teile).

## 5. Kuratiertes Feld-Mapping (Factbook → Sektionen)

- **profile:** Background (gekürzt, 1-2 Sätze), Area, Climate, Natural resources
- **people:** Population, Median age, Population growth rate, Urbanization, Life expectancy at birth, Ethnic groups, Religions, Languages, Literacy
- **government:** Government type, Capital, Independence, Chief of state, Head of government, Legislative branch, Suffrage
- **economy:** Real GDP (PPP), Real GDP per capita, Real GDP growth rate, Inflation, GDP composition by sector, Industries, Labor force, Unemployment rate, Youth unemployment, Public debt, Exports (+ partners, + commodities), Imports (+ partners), Exchange rates
- **security:** Military expenditures (neuestes Jahr; ggf. + Vorjahr), Military and security forces, Personnel strengths, Military service age and obligation, Military deployments, Military - note

Jedes Subfeld → ein `{label, value}`. Pro Land ~40-50 Facts (statt aktuell ~4).

## 6. Overrides (Korrektur 4 + offene Entscheidung → Variante A)

**Neu:** `services/backend/data/country_almanac_overrides.json` — die **einzige** Quelle manueller Fakten. Zuletzt angewandt, label-dedupliziert (Override gewinnt). Schema:
```json
{ "USA": { "facts": { "security": [{ "label": "ODIN note", "value": "..." }] } } }
```
Anwendung: für jeden iso3-Key im Overrides-File werden `region`/`subregion`/`capital`/`facts[section]`-Einträge in den generierten Eintrag gemerged; bei gleichem `label` in einer Sektion gewinnt der Override.

Da Factbook government/military für **jedes** Land liefert, werden die bisherigen hand-kuratierten USA/GRC-Fakten größtenteils durch reichere Factbook-Daten ersetzt. Das Overrides-File startet daher minimal und hält nur noch **ODIN-spezifische Editorials**, die Factbook nicht hat (z.B. eine eigene Threat-Einordnung). Es wird **nicht** aus dem alten Seed zurückgelesen.

## 7. Packaging + Baseline (Korrektur 3)

Der Backend-Docker-Fix `COPY data/ data/`, der Compose-Mount `./services/backend/data:/app/data` und der Seed-Integrity-Test liegen aktuell in **PR #29**, **nicht** in HEAD (`main`). Dieser Spec setzt sie voraus:
- **Empfohlen:** den Implementierungs-Branch auf PR #29 basieren (zuerst #29 mergen) — dann sind Packaging + iso3-Baseline + Integrity-Test vorhanden, und der Builder regeneriert den Seed darüber.
- **Falls #29 nicht zuerst landet:** der Factbook-PR enthält Dockerfile `COPY data/ data/`, den Compose-Mount und den Seed-Integrity-Test selbst (self-contained), um Regressionen zu vermeiden.

Da der Builder den Seed regeneriert, **ersetzt** er die manuelle REST-Countries-Anreicherung aus #29; REST Countries bleibt nur als Coords/Fallback-Quelle im Builder.

## 8. Schema

Unverändert (`app/models/almanac.py`). Optionales additives `_meta`-Feld am Top-Level des Seed-JSON für Provenienz (§3.1) — wird vom Loader ignoriert (`raw.get("countries", [])` liest nur `countries`), also keine Modell-Änderung nötig.

## 9. Tests

**Builder-Unit-Tests** (`services/data-ingestion/tests/test_build_country_almanac.py`):
- HTML-Cleaner: strippt `<b>…</b>`, behält Jahres-Suffix.
- Mehrjahres-Selektor: wählt neuestes Jahr.
- Komposit-Formatter: `{agriculture,industry,services}` → erwarteter String.
- Crosswalk-Resolver: Majors (USA/DEU/CHN) + Kosovo lösen auf; unbekannter Code → übersprungen, geloggt.
- Overrides: werden zuletzt angewandt, Label-Dedup (Override gewinnt); generierter Output wird NICHT als Input gelesen (Builder ignoriert ein vorhandenes `country_almanac.json`).

**Seed-Integrity** (`services/backend/tests/test_almanac_seed_integrity.py`, erweitert; aus #29 mitgeführt falls #29 nicht zuerst merged):
- jedes ISO-Land hat **economy- UND security-Facts** (die Schmerzpunkte),
- **kein rohes HTML** (`<`) in irgendeinem `value`,
- ≥ N Facts/Land (z.B. ≥ 20 für ISO-Länder),
- `_meta.factbook_revision` ist gesetzt.
- bestehende Guardrails (iso3-Coverage, Population+Capital, Dockerfile packt `data/`) bleiben.

**Backend-Suite:** 269/269 grün halten; ruff sauber.

## 10. Risiken

- **Crosswalk-Vollständigkeit:** vendored + reviewt; fehlende GEC-Codes → Land bleibt Stub (geloggt), kein Crash.
- **Factbook-Prosa:** Werte sind Fließtext mit HTML/Noten — Cleaner muss robust sein (Tests).
- **Eingefrorener Snapshot:** Daten sind ein fixer Stand (2026-02-04-nah); `_meta` dokumentiert das offen. Keine automatische Aktualität — bewusst akzeptiert.
- **Reihenfolge mit #29:** Seed-Datei überlappt → Branch auf #29 basieren, um Konflikte zu vermeiden.

## 11. Offene Folge-Arbeit (außerhalb dieses Specs)

- **Teil 2:** Munin-Lagebericht pro Land (Almanac-Facts + bereits gematchte Live-Signale `/almanac/countries/{id}/signals` + RAG/Graph → Synthese). Eigener Spec.
