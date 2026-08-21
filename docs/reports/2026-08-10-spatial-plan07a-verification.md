# Spatial Scope Plan 07A — Abschlussverifikation

**Datum:** 2026-08-10

**Branch:** `feat/spatial-plan03`

**Implementierungs-HEAD:** `48a72e5`

**Review-Remediation-HEAD:** `c8571ba`

**Status:** Plan 07A code-seitig abgeschlossen; operative Qdrant-Promotion offen

## Abgenommenes Ergebnis

Plan 07A liefert den Retrieval-Teil von Canonical Slice 7:

1. einen atomaren Scope-/Revisionsvertrag pro Relation und Ancestor,
2. den vollständigen Qdrant-Payload-Indexvertrag mit genau einem autorisierten
   Migrationswriter,
3. deterministische Projektion aus strukturierter/reviewter Evidenz,
4. einen reinen, fail-closed Qdrant-Filter-Compiler zusätzlich zur Corpus-Policy,
5. restartbares, per Point atomares Re-Enrichment mit Coverage und Stale-Accounting.

Der anfängliche Design-Blocker ist aufgelöst. About und Occurrence besitzen getrennte
Keyword-Arrays; jedes Element ist ein injektives Compound-Token:

```text
sr1|<canonical non-global ScopeKey>|<DerivationRevision genau dieses Scopes>
```

Damit kann ein Admin-1-Point sowohl über die eigene Admin-1-Revision als auch über
die separate Country-Revision des materialisierten Ancestors gefunden werden. Einen
Qdrant-weiten Scalar `spatial_derivation_revision` gibt es nicht.

## Verträge und Eigentümer

### Payload und Indizes

`contracts/qdrant-spatial-payload-v1.json` pinnt Pair-Token, aktiven UA-14-Vektor,
Projektionsfingerprint und alle 17 Payload-Indizes: neun bestehende Corpus-/Fulltext-
Indizes plus acht Spatial-Indizes. `spatial_conflict` und
`spatial_conflict_scope_keys` bleiben unindizierte Auditfelder. Falsche Qdrant-Typen
failen. Nur
`services/intelligence/scripts/ensure_payload_indexes.py` darf fehlende Indizes
erstellen; Search und Writer validieren beziehungsweise melden ausschließlich.

### Writer und Projektion

`contracts/qdrant-spatial-writer-lanes-v1.json` inventarisiert die unterstützten und
explizit nicht unterstützten Writer-Lanes. Filterbare Projektion entsteht nur aus:

- GDELT `linked_event_ids` → exakter Join auf strukturierte Event-ActionGeo-Felder
  für `occurrence`;
- NotebookLM Claim-Entity-Referenz → genau eine typisierte extrahierte Geo-Entität →
  genau ein reviewter Country-Label-Crosswalk oberhalb des versionierten Gates für
  `about`.

Titel-, Theme-, Querytext-, Ortsnamen- oder Substring-Raten ist ausgeschlossen.
Conflict-Evidenz publiziert selbst keine filterbaren Pair-Tokens oder Geo. Sie
unterdrückt nur denselben Scope derselben Relation; valide unabhängige Evidenz
bleibt auffindbar. Nicht migrierte Lanes markieren die Ableitung explizit als
`unavailable`.

Der aktive vollständige 204-Scope-Katalog ergibt deterministisch
`spatial-projection-v1-47fec701a2a2`. Der Fingerprint enthält Pair-Token-Version,
Deriver-Version, About-Gate und die vollständige sortierte
Scope→Derivationsrevision-Menge, nicht die Katalogprovenance.

### Retrieval

`services/intelligence/spatial.py` kompiliert ausschließlich qdrant-client-Modelle:

- `world` → kein Spatial-Filter;
- `about`/`occurrence` → exakter Match auf das jeweilige Pair-Token-Feld;
- `either` → geschachteltes `should` über beide Relationen;
- jeder nicht-globale Scope ausschließlich über vom Projector zugelassene positive
  Pair-Tokens; kein recordweites Conflict-Prädikat;
- AOI nur über ein oder zwei vorsegmentierte, finite Bounding Boxes auf `geo`.

Analysis-/Realtime-Corpus-Policy bleibt als unverändertes äußeres Filterobjekt
erhalten. Der HTTP-Retriever serialisiert erst am Transport-Seam. Leere Ergebnisse
oder Fehler lösen keinen ungefilterten Retry aus. Der Search-Seam kann den an die
Zielprojektion gebundenen `SpatialCoverageSnapshotV1` mitführen.

### Re-Enrichment

`contracts/spatial-batch-file-formats-v1.json` und
`services/intelligence/rag/spatial_reenrich.py` definieren:

- vollständige Previews ohne Writes oder Checkpoint-Mutation;
- Apply nur mit genehmigtem vollständigem Dry-run als Pflichtargument;
- Apply-Checkpoint `lane|target_projection_revision` plus genehmigtem
  Report-Fingerprint nach bestätigtem Batch;
- Cursor-Resume und idempotente Completed-Jobs;
- vollständigen Point-Upsert mit erhaltenem Vektor/Non-Spatial-Payload;
- Entfernung aller alten `spatial_*`-, `geo`- und Raw-Code-Projektionsfelder;
- exakte per-Lane Coverage vor und nach Projektion inklusive benanntem
  Unprojected-/Audit-only-/Inconsistent-Anteil und wirksamem Stale-Gap;
- kanonischen Report-Fingerprint und Driftprüfung eines reviewten Dry-runs;
- Scheduling nur bei verändertem Projektionsfingerprint; Catalog-Carry-forward mit
  unveränderter Scope→Revisionsmenge ist ein No-op.

## Lokale Commits

```text
d186a40 docs(spatial): pair qdrant ancestor revisions
7d77237 build(qdrant): add spatial payload indexes
473b4c2 feat(qdrant): write relation-specific spatial payloads
24bc336 feat(intelligence): compile qdrant spatial filters
48a72e5 feat(qdrant): reenrich spatial payloads restartably
f41d43d fix(spatial): harden Plan 07A review gates
c8571ba fix(spatial): close Plan 07A re-review gaps
```

Der vorausgehende Handoff-Commit ist
`a0f730a docs(spatial): hand off Plan 07A`.

## Verifikation

```text
cd services/intelligence
uv sync
uv run pytest
398 passed
uv run ruff check .
All checks passed

cd services/data-ingestion
uv sync
uv run pytest
1368 passed, 1 skipped, 17 deselected
uv run ruff check .
All checks passed
```

Data-Ingestion deselected standardmäßig die 17 als `live` markierten Tests über
`-m "not live"`. Der vorhandene GDELT-Integrationstest wurde mangels laufender
Dev-Compose-Services übersprungen. Es wurden keine Tests still ergänzt oder
deaktiviert.

## Bewusst nicht ausgeführte Operationen

- kein Push und kein PR;
- keine Qdrant-Payload-Index-Mutation;
- kein Staging-/Live-Re-Enrichment-Apply;
- keine reale Analysis-/Realtime-Coverage behauptet;
- keine Exact-Capability aktiviert.

Vor einer Qdrant-Promotion bleiben Payload-Index-Erstellung in Staging,
Full-Lane-Dry-run, Review, Apply und reale Coverage-/Stale-Snapshots ausdrücklich
genehmigungspflichtig. Ein Stale-Anteil über 1 % blockiert die Promotion.

## Übergang zu Plan 07B

Plan 07A und der bereits abgenommene Plan 06B erfüllen die Code-Abhängigkeiten für
Plan 07B. Canonical Slice 7 bleibt dennoch offen, bis Munin Scope Enforcement den
serverseitig aufgelösten Token unveränderlich in den Run pinnt, Tool-Capabilities
bindet, Qdrant- und Graph-Zugriffe fail-closed scoped und die tatsächliche räumliche
Anwendung durch alle Response-/Persistenz-Seams propagiert.
