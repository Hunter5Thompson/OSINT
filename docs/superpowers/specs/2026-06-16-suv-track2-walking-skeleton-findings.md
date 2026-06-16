# SUV Track 2 — Walking-Skeleton Findings (Go/No-Go gate)

**Date:** 2026-06-16
**Decision:** **GO** — the source is reliably extractable; scope is simpler than the original design assumed.
**Method:** crawl4ai (`POST localhost:11235/md`, `f=fit`) against `https://suv.report/sicherheits-und-verteidigungsindustrie/`; deterministic regex parser probe (`scratch/parse_probe.py`); raw crawl saved as `scratch/suv_dir.json` (usable as a test fixture).

## What we verified
1. **No paywall.** Anonymous crawl4ai render returns the full directory — `success: true`, 84,936 chars of markdown, fresh ("Letzte Aktualisierung: 4. Juni 2026").
2. **Exactly 77 companies**, each a `### <Name>` heading (Aaronia AG … KNDS N.V.). Matches the design's "~77" precisely.
3. **All detail data is ON THE ONE directory page** — `**Hauptsitz:**` appears exactly 77× (one per company), alongside `**Gründung**`, `**Geschäftsführung**`, `**Mitarbeiterzahl**`, `**Umsatz**`, `**Beschreibung**`, `**Produktportfolio**`.
4. **Deterministic parse works — 100% field coverage:** the regex probe extracted Gründung/Hauptsitz/Geschäftsführung/Mitarbeiterzahl/Umsatz/Produktportfolio for **77/77** companies (Beschreibung 76/77); **0** companies missing a core field.

## Deltas vs the 2026-06-14 design (fold into the plan refresh IF we build)
- **extract.py can be DETERMINISTIC, not LLM.** The `**Label:**`-value structure is fully regular → a regex parser extracts the fields. This **removes** the vLLM 9B dependency, the LLM-context-pagination risk (design §10), and the hallucination rationale. Keep the committed `seeds/suv_companies.yaml` snapshot (reproducibility + human review gate + LLM-free write path) — but its producer is the parser, not an LLM.
- **fetch.py: one crawl, not 77 detail-page crawls.** Simplifies fetch; the §10 "only crawl detail pages" fallback is moot.
- **Schema:** confirmed fields = name, Gründung(founded), Hauptsitz(full address), Geschäftsführung(management), Mitarbeiterzahl(employees), Umsatz(revenue), Beschreibung(description), Produktportfolio(products). The design's `website` field is **absent** on the page (no `Webseite`) → drop or source elsewhere.
- **HQ→country normalization is the one real parsing task.** Hauptsitz is a full street address; the country must be derived from its tail. Probe heuristic got 67/77 directly; 10 had city+ZIP tails (Berlin/Hamburg/Bremen/Berne = all German cities; 1 genuine foreign HQ = KNDS → Niederlande). Needs a German-ZIP/city/state → Deutschland map + foreign-country handling (design §10 already flagged this). Unmatched → `HEADQUARTERED_IN` skipped + logged (per write-path rule).
- **Value normalization** (Umsatz multi-year "35,3 Mio (2023), 50+ Mio (2024)", Mitarbeiterzahl ">75" / "32.000 Weltweit") — keep as strings or light-normalize; LLM is OPTIONAL here, not required.

## T4 / Track-1 deltas already known (independent of the crawl)
- Track 1 (PR #41) **MERGED** → SUV read-side credibility 0.78 already wired.
- `location_loc_key_unique` constraint now LIVE (T4) — irrelevant to companies (they use `Entity`, not `Location`), no change.

## Net effect
The original 14-task plan **shrinks** (no LLM extract module, no pagination, no detail-page crawler) and **de-risks** (deterministic, GPU-free, reproducible). The remaining MANDATORY human checkpoint is unchanged and correct: the `--approved-matches` entity-resolution gate (company → existing `Entity` match curation).

**Recommendation:** proceed to SUV Track 2 as the next feature, with a refreshed (simpler) plan built off this finding.
