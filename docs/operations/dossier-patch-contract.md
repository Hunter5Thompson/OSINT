# Dossier updates and empty drafts

Updates use one fixed, parameter-bound Cypher `MATCH`/`SET +=` statement. The
validated `ReportUpdateRequest` is the property allowlist. Only supplied fields
are written, so concurrent edits to disjoint fields survive and an update cannot
recreate a report deleted before its write. Conflicting edits to the same field
still follow database write order; this is not an optimistic versioning API.

An empty patch, or a patch containing only ordinary nulls, performs a read without
changing `updated_at`. Explicit null clears confidence and optional assessment,
verification, evidence, coverage and spatial-application metadata. Null title,
findings and other ordinary fields remain no-ops. Zero, empty strings and empty
lists remain actual supplied values. Report identity, scope and creation time
are never part of the update allowlist.

New drafts have unknown confidence, empty findings/metrics/margin/sources and no
body. Editor guidance is rendered by the frontend and never stored as evidence.
Previously stored historical values are preserved; no bulk data migration runs.

Five regressions reproduced against an isolated, marked Neo4j 5.26.23 instance
before the correction. The full 18-case metadata/concurrency integration then
passed, including save/read/list/scope projections and null/zero semantics. The
frontend create/reload test checks empty-state guidance without fabricated scores
or sources. Evidence: `/data/odin-reliability-20261106/p3/`.
