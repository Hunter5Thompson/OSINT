# HANDOFF — Spatial Scope Plan 07A abgeschlossen → Plan 07B

**Datum:** 2026-08-10

**Nächster Chat:** Plan 07B — Munin Scope Enforcement, strikt testgetrieben

**Branch:** `feat/spatial-plan03`

**Repo:** `/home/deadpool-ultra/ODIN/OSINT`

**Plan-07A-Abschluss-HEAD vor diesem Handoff:** `48a72e5`

**Plan-07A-Review-Remediation:** `f41d43d`

**Remote:** `origin/feat/spatial-plan03` bei `bd3c10b`

**Divergenz vor diesem Handoff:** ahead 6, behind 0

**Status:** Plan 07A ist code-seitig abgeschlossen und vollständig service-lokal
verifiziert. Canonical Slice 7 bleibt offen, bis Plan 07B abgeschlossen ist. Es gab
keinen Push, keine Qdrant-Indexmutation, kein Re-Enrichment-Apply und keine
Exact-Promotion.

## Pflichtstart im nächsten Chat

Vor jeder Änderung vollständig lesen:

1. `AGENTS.md`
2. `CLAUDE.md`
3. dieses Handoff
4. [Implementation-Planindex](plans/2026-08-01-spatial-scope-implementation.md)
5. [Plan 07B](plans/2026-08-01-spatial-scope/07b-munin-scope-enforcement.md)
6. [Spec 10 — Munin Scope Enforcement](specs/2026-07-31-spatial-scope-drilldown/10-munin-scope-enforcement.md)
7. [Spec 09 §§16.3–16.4 — Qdrant-Filter/Coverage](specs/2026-07-31-spatial-scope-drilldown/09-qdrant-retrieval.md)
8. [Spec 12 §§20–22 — Fehler/Sicherheit/Observability](specs/2026-07-31-spatial-scope-drilldown/12-errors-security-and-observability.md)
9. [Spec 13 Slice 7](specs/2026-07-31-spatial-scope-drilldown/13-implementation-and-tdd-slices.md)
10. [Spec 14 §§26–27 — Rollout/Stop-Regeln](specs/2026-07-31-spatial-scope-drilldown/14-rollout-and-acceptance.md)
11. [Plan 06B](plans/2026-08-01-spatial-scope/06b-chronik-exact-scope.md)
12. [Plan 07A](plans/2026-08-01-spatial-scope/07a-qdrant-spatial-payload.md)
13. [Plan-06B-Review-Remediation](../reports/2026-08-09-spatial-plan06b-review-remediation.md)
14. [Plan-07A-Abschlussverifikation](../reports/2026-08-10-spatial-plan07a-verification.md)
15. [Plan-07A-Review-Remediation](../reports/2026-08-10-spatial-plan07a-review-remediation.md)

Dann Zustand neu prüfen:

```bash
git status --short --branch
git log -12 --oneline --decorate
git rev-list --left-right --count HEAD...origin/feat/spatial-plan03
```

Aktuell sind drei fremde Worktree-Einträge sichtbar. Nicht ändern, stagen,
zurücksetzen oder in einen Commit aufnehmen:

- `docs/CONTAINER-STATUS.md`
- `scripts/spark/odin-spark-vllm.sh`
- `docs/superpowers/plans/2026-08-10-task-104-phase2-qdrant-bm25-hybrid.md`

Kein PR, Push, Merge nach `main`, Live-/Staging-Index-Apply, Re-Enrichment-Apply oder
Exact-Activation ohne ausdrücklichen Auftrag.

## Abgenommene Plan-07A-Commits

```text
d186a40 docs(spatial): pair qdrant ancestor revisions
7d77237 build(qdrant): add spatial payload indexes
473b4c2 feat(qdrant): write relation-specific spatial payloads
24bc336 feat(intelligence): compile qdrant spatial filters
48a72e5 feat(qdrant): reenrich spatial payloads restartably
f41d43d fix(spatial): harden Plan 07A review gates
```

Der Plan-07A-Start-Handoff ist `a0f730a docs(spatial): hand off Plan 07A`.

## Verbindlicher 07A-Retrievalvertrag für 07B

### Backend-resolved Token

Backend besitzt bereits den strikten Vertrag in `app/models/spatial.py`:

```text
SpatialScopeTokenV1
  schema_version
  scope_key
  kind
  catalog_revision
  derivation_revision
  boundary_policy
  compatible_derivation_revisions[]
```

Die Compatibility-Menge kommt ausschließlich aus dem serverseitig geladenen,
reviewten Katalog. Der Browser darf weder den vollständigen Token noch kompatible
Revisionen liefern. `world` bleibt ein echter Token im Run-State, erzeugt im
Qdrant-Compiler aber keinen Spatial-Filter.

Backend besitzt mit `SpatialCatalogLoader` und der Token-Erzeugung in
`app/services/spatial_filters.py` bereits die geprüften Scope-/Revision-Primitiven.
Work Order 1 soll diese Resolver-Eigentümerschaft wiederverwenden und keinen zweiten
Alias-/Katalogpfad erfinden.

### Qdrant Pair-Tokens

Scope-Kompatibilität wird ausschließlich über zwei relation-spezifische Felder
ausgedrückt:

```text
spatial_about_scope_revision_tokens[]
spatial_occurrence_scope_revision_tokens[]

sr1|<canonical non-global ScopeKey>|<DerivationRevision dieses Scopes>
```

Es gibt keinen Qdrant-Scalar `spatial_derivation_revision`. Der Request-
`catalog_revision` wird nicht mit Record-Provenance verglichen.
`spatial_projection_revision` steuert Jobs/Coverage und ist kein Scope-
Kompatibilitätsprädikat.

### Intelligence API

`services/intelligence/spatial.py` stellt bereit:

```text
SpatialScopeTokenV1
RetrievalSpatialRelation  # about | occurrence | either
compile_qdrant_scope_filter(token, relation)
compile_qdrant_aoi_filter(boxes)
combine_filters(base, spatial)
SpatialCoverageSnapshotV1
SpatialLaneCoverageV1
```

Die Compiler liefern qdrant-client-`models.Filter`, keine freien Dictionaries.
`either` ist ein geschachteltes `should`. Pair-Tokens sind die alleinige positive
Retrieval-Berechtigung; der Compiler liest kein recordweites Conflict-Boolean.
Conflict-only-Points besitzen keine Tokens, Mixed-Points behalten ausschließlich die
vom Projector je Relation und Scope zugelassenen Tokens. `combine_filters`
verschachtelt die bestehende Analysis-/Realtime-Corpus-Policy als eigenes `must` und
mutiert oder flacht deren `should`/`must_not` nicht ab.

`rag.retriever.enhanced_search` akzeptiert bereits `query_filter` und
`coverage_snapshot`. Serialisierung erfolgt erst am HTTP-Seam. Ein Empty Result macht
genau einen Search-Call und löst keinen ungefilterten Retry aus.

### Coverage und partielle Lanes

Der V1-Snapshot ist an genau eine `target_projection_revision` gekoppelt und weist
pro Lane `total`, `filterable`, `conflict`, `stale`, `unsupported`, `unprojected` und
`audit_only` aus. Die sechs Statuszähler ergeben exakt `total`; es gibt keinen
unbenannten Rest. `unavailable` Legacy-Points zählen als unsupported. Der wirksame
Promotions-Stale-Gap ist `(stale + unprojected) / total`; über 1 % blockiert.
Fehlend, partial, stale, no-hit und Qdrant-Ausfall dürfen niemals einen globalen
Retry auslösen.

Der aktive Projektionsfingerprint lautet
`spatial-projection-v1-47fec701a2a2` mit `spatial-deriver-v2`. Die gemeinsame
Definition liegt in:

- `contracts/qdrant-spatial-payload-v1.json`
- `contracts/qdrant-spatial-writer-lanes-v1.json`
- `contracts/spatial-batch-file-formats-v1.json`

Der Payload-Vertrag umfasst 17 Indizes: neun Corpus-/Fulltext- und acht Spatial-
Indizes. `spatial_conflict` und `spatial_conflict_scope_keys` bleiben unindizierte
Auditfelder.

### Approval-Gate für spätere Operatorpfade

`preview_spatial_reenrichment(...)` besitzt keine Mutationsfähigkeit.
`apply_spatial_reenrichment(..., approved_report=...)` verlangt strukturell einen
genehmigten vollständigen Dry-run, validiert vor dem ersten Write einen frischen
Vollscan und bindet dessen Fingerprint für jeden Resume im dauerhaften Checkpoint.
Es gibt keine öffentliche Apply-API mit frei wählbarem Mode-Flag. Plan 07B oder ein
späterer Operator-Einstiegspunkt darf ausschließlich diese Funktion verwenden.

Der unabhängige read-only Review-Snapshot vom 2026-08-10 zählte 1.025.197 Points,
nur die neun Corpus-/Fulltext-Indizes und keine Spatial-Payloads. Scoped Retrieval
bleibt daher bis zum autorisierten Re-Enrichment korrekt leer/fail-closed.

## Konkreter Ist-Zustand, den 07B ablösen muss

- `agents/tools/qdrant_search.py` exponiert derzeit noch modellseitig `region` und
  reicht diesen Legacy-String in beide Lanes weiter. 07B entfernt dieses Argument;
  der Scope kommt nur aus `ToolRuntime`/gepinntem State.
- `agents/tools/graph_query.py` besitzt für globale Runs einen Free-Cypher-Fallback.
  Für nicht-globale Runs muss jeder Pfad ausschließlich über vollständige statische
  `(template_id, scope_kind)`-Templates laufen; unsupported Intent führt zu null
  Queries.
- `agents/tools/vision.py` nimmt derzeit noch eine Bild-URL als Tool-Argument. Scoped
  Vision darf nur das bereits angehängte Bild aus State lesen.
- `graph/state.py` enthält noch keinen gepinnten Spatial-Token und keine Relation.
- Der bestehende ReAct-Prompt erwähnt `region=""`; Enforcement darf nach 07B nicht
  mehr von Prompttext abhängen.
- Der lifecycle-owned `ToolNode` kann alle Tools kennen, aber die tatsächlich an das
  Modell gebundene Capability-Menge muss aus dem unveränderlichen Run-State kommen.

## TDD-Reihenfolge für Plan 07B

Plan 07B hat fünf Commitgrenzen und ist in dieser Reihenfolge auszuführen:

1. Backend löst Caller-Ref serverseitig zu Token und default `either` auf.
2. Intelligence pinnt Token/Relation unveränderlich in `AgentState`; modellseitige
   Tool-Schemas exponieren keine Scope-, Region- oder Image-Override-Felder.
3. Qdrant und Graph lesen nur Runtime-State und failen für nicht-globale Runs closed.
4. Capability-Matrix bindet scoped nur erlaubte Tools und blockiert direkte Bypässe
   vor HTTP/Neo4j.
5. Trusted `[SPATIAL_APPLICATION]`-Codec propagiert tatsächliche Anwendung durch
   Intelligence, Backend-SSE/Report-Persistenz und Frontend ohne Relabeling.

Für jeden Work Order zuerst den benannten RED-Nachweis aus dem Plan erzeugen, dann
minimal GREEN, Refactor, service-lokal verifizieren und separat committen.

## Plan-07A-Verifikation

```text
services/intelligence
395 passed
ruff check .: green

services/data-ingestion
1366 passed, 1 skipped, 17 deselected
ruff check .: green
```

Die 17 standardmäßig deselecteten Tests sind `live`; der vorhandene GDELT-
Integrationstest wurde ohne laufende Dev-Compose-Services übersprungen.

## Offenes operatives Gate

Plan 07B darf testgetrieben implementiert werden. Eine tatsächliche Exact-Promotion
bleibt dennoch blockiert, bis für Qdrant in Staging die Payload-Indizes erstellt,
ein vollständiger Dry-run reviewed, das Apply autorisiert und reale
Analysis-/Realtime-Coverage-/Stale-Snapshots erfasst wurden. Stale über 1 % blockiert
die Promotion. Kein Unit-Test- oder In-Memory-Snapshot ersetzt diese Evidenz.
