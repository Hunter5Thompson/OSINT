# Spatial Plan 07A — Qdrant Filter-Compiler

**Datum:** 2026-08-10

**Scope:** Work Order 3; reine Filterkonstruktion und Retrieval-Komposition, keine
Live-Mutation

## Ergebnis

`services/intelligence/spatial.py` besitzt nun den service-lokalen strikten
`SpatialScopeTokenV1`-Vertrag sowie ausschließlich allowlist-basierte Compiler für
Scope-Pair-Tokens und explizite ein-/zweiteilige AOI-Boxen.

- `world` kompiliert zu `None`.
- `about` und `occurrence` lesen getrennte Pair-Token-Felder.
- `either` kapselt beide Bedingungen in einem `should`-Unterfilter.
- Pair-Tokens sind die positive Retrieval-Berechtigung; ein recordweites
  Conflict-Boolean wird nicht gelesen. Conflict-only-Points besitzen keine Tokens,
  Mixed-Points behalten nur die vom Projector zugelassenen Scope-/Relationspaare.
- Jede Compatibility-Revision wird mit dem angefragten Scope-Key neu gepaart;
  Cross-Pair- und stale Payloads matchen nicht.
- AOI-Felder sind fest auf `geo` begrenzt. Ein Dateline-AOI kommt als zwei bereits
  nicht-wrappende Boxen und wird als gekapseltes `should` kompiliert.

Analysis- und Realtime-Corpus-Policies liefern jetzt `qdrant-client`-Modelle.
`combine_filters` erzeugt `Filter(must=[base, spatial])`, mutiert den Base-Filter
nicht und flacht dessen `should`/`must_not` nicht ab. Der Retriever serialisiert erst
am HTTP-Seam mit `model_dump(mode="json", exclude_none=True)`. Eine leere Antwort
erzeugt keinen ungefilterten Retry.

Der Retriever akzeptiert außerdem einen strikten
`SpatialCoverageSnapshotV1(target_projection_revision, lanes)` mit den Zählern
`total`, `filterable`, `conflict`, `stale`, `unsupported`, `unprojected` und
`audit_only`. Work Order 4 erzeugt und persistiert diese Snapshots; Work Order 3
verändert keine Corpus-Daten.

## TDD-Nachweis

Der erste Lauf scheiterte in zwölf Tests an den absichtlich noch fehlenden
Compiler-, AOI-, Kompositions- und Coverage-Typen. Nach der Implementation wurden
die räumlichen Tests, beide Corpus-Lanes, Retriever-/Tool-Regressionen und der
read-only Schema-Preflight gemeinsam verifiziert:

```text
85 passed
Ruff: All checks passed
```

Es wurden weder Live-Qdrant-Abfragen noch Index- oder Payload-Schreiboperationen
ausgeführt; der Cross-Pair-Nachweis verwendet ausschließlich Qdrant `:memory:`.
