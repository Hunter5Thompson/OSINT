# Fusion Core - Design Spec

**Date:** 2026-05-03
**Review Update:** 2026-05-04
**Status:** Review-ready
**Scope:** TASK-112 candidate: canonical observations, stable world objects,
spatiotemporal fusion, source lineage, and analyst triage

---

## 1. Motivation

WorldView already has a strong map, graph, RAG stack, and multiple data feeds. The
next step is not adding more raw layers. The next step is a fusion core that turns
source-specific records into traceable observations, links those observations to
stable world objects, and gives analysts a review loop before claims become
operational knowledge.

Today, data sources behave like parallel surfaces:

- AIS, ADS-B, TLE, FIRMS, GDELT, RSS, NotebookLM, and manual notes can describe the
  same real-world object or incident without a shared identity.
- Neo4j stores entities and events, but there is no explicit pre-graph observation
  layer with validity windows, source provenance, and match decisions.
- Agent answers can cite sources, but TASK-014 still leaves lineage, tool isolation,
  and write/read separation incomplete.
- Vision is planned as TASK-107, but without a fusion core it would become another
  special-case layer instead of a first-class sensor input.

The goal is to make every machine or analyst claim answer four questions:

```text
What was observed?
Who observed it?
When and where was it valid?
Why was it linked to this object or incident?
```

---

## 2. Decision

Introduce a new Fusion Core between ingestion/extraction and the analyst-facing
surfaces.

Canonical flow:

```text
Raw source record
  -> SourceRef
  -> Observation
  -> deterministic/fuzzy matcher
  -> WorldObject or IncidentCandidate
  -> FusionLink
  -> ReviewItem when confidence or conflict requires human judgment
  -> approved graph/timeline/globe representation
```

The write path remains deterministic. LLMs can extract structured data or propose
candidate links, but Neo4j writes use validated Pydantic models and Cypher templates
only.

Vision is explicitly downstream of this design. A future satellite or aerial image
detector writes `Observation(source_type="vision")` records into the same pipeline
used by GDELT, RSS, AIS, ADS-B, TLE, FIRMS, and analyst notes.

---

## 3. Goals

1. Create a source-agnostic observation model that all current and future feeds can
   produce.
2. Create stable `world_object_id` identities for durable objects such as vessels,
   aircraft, satellites, facilities, organizations, and named locations.
3. Create incident candidates for time-bounded phenomena such as explosions,
   conflict events, fires, disasters, sanctions, outages, and protests.
4. Preserve full source lineage from source record to observation to fused object or
   incident.
5. Add a review queue for ambiguous matches, conflicts, and high-value correlations.
6. Expose fused objects, incident candidates, source lineage, and review state to the
   backend API, Worldview Inspector, Graph Explorer, and future briefing flows.
7. Keep the first implementation small enough to ship without requiring TASK-107
   vision training.

---

## 4. Non-Goals

This spec does not train a vision model.

This spec does not replace existing feed collectors in one migration.

This spec does not make agent-generated Cypher legal on the write path.

This spec does not automate operational decisions. The system can recommend review
or escalation, but analyst approval is required before a fused claim is treated as
briefed or confirmed.

This spec does not require PostGIS or a new database. Phase 1 uses Neo4j plus Redis
and service-local logic. A later performance spec may introduce a spatial index or
columnar event store if needed.

This spec does not store full-rate AIS or ADS-B streams in Neo4j. Phase 1 stores
sampled observations and accepted fusion state only; high-volume track retention is a
follow-up Realtime Track Store concern.

---

## 5. Core Concepts

### 5.1 SourceRef

`SourceRef` describes where an observation came from.

Required fields:

```text
source_id: stable hash or provider id
source_type: gdelt | rss | notebooklm | ais | adsb | tle | firms | analyst | vision
provider: human-readable provider name
external_id: optional provider-native identifier
url: optional source URL
feed_id: optional feed/channel identifier
fetched_at: ingestion timestamp
published_at: optional source publication timestamp
credibility_score: 0.0-1.0
license: optional source/license note
excerpt: optional short supporting excerpt
payload_hash: hash of normalized raw payload
classification: public | internal | sensitive
```

Identity rule:

```text
source_id = sha256(normalization_version + source_type + provider + external_id
                   + url/feed_id + payload_hash)[:20]
```

When a source has a canonical id, such as GDELT GKG id, AIS message id, or TLE NORAD
catalog number plus epoch, the source-specific id is stored in `external_id` and also
participates in the hash.

`[:20]` gives 80 bits of hash material. Phase 1 uses this length for SourceRef,
Observation, FusionLink, ReviewItem, and source-independent fingerprints so child ids
do not carry more entropy than their parent evidence ids.

### 5.2 Observation

`Observation` is the universal input into fusion. It is not yet truth. It is a
source-backed claim or sensor reading.

Required fields:

```text
observation_id: stable hash
source_id: SourceRef link
observed_at: when the described thing happened or was measured
ingested_at: when WorldView received it
valid_from: earliest validity timestamp
valid_until: latest validity timestamp
geometry: point | bbox | polygon | track_segment | none
lat: optional centroid latitude
lon: optional centroid longitude
object_type_hint: aircraft | vessel | satellite | facility | location | event | fire | unknown
entity_hints: normalized identifiers and names
confidence: 0.0-1.0
extraction_method: deterministic | llm | sensor | analyst | vision
payload: normalized source-specific details
claim_fingerprint: source-independent normalized claim fingerprint
normalization_version: schema/id normalization version
```

Observation identity:

```text
observation_id = sha256(normalization_version + source_id + observed_at
                        + object_type_hint + geometry_hash + entity_hint_hash)[:20]
```

This makes ingestion idempotent. Replaying the same feed slice updates the same
observation rather than creating a duplicate.

Two independent providers that emit the same real-world claim produce separate
Observations because `source_id` participates in `observation_id`. They share the same
`claim_fingerprint` when their normalized source-independent fields match. Fusion uses
that fingerprint for corroboration without losing per-source lineage.

### 5.2.1 Normalization Rules

All ids use `normalization_version = "fusion-v1"` in Phase 1.

Hash inputs are built from canonical JSON:

```text
UTF-8
sorted keys
no null-valued optional fields
trimmed strings
Unicode NFKC
case-folded identifier keys
ISO-8601 UTC timestamps truncated to seconds
```

`entity_hint_hash` includes only stable keys:

```text
identifiers: mmsi, imo, icao24, callsign, norad_id, wikidata_id, iso3, m49
names: canonical_name, aliases
object_type_hint
```

Adding a new hint field must not affect idempotency until the implementation bumps
`normalization_version`.

`geometry_hash` is source-type aware:

```text
point: lat/lon rounded to 5 decimals
bbox: min_lon,min_lat,max_lon,max_lat rounded to 5 decimals
polygon: WGS84 ring coordinates rounded to 5 decimals after canonical ring ordering
track_segment: start/end point rounded to 5 decimals plus start/end timestamps
none: literal "none"
```

`claim_fingerprint` excludes `source_id`, URL, provider, and fetched timestamp. It
includes `normalization_version`, observed time bucket, object type hint, stable entity
hints, and geometry hash. This is a corroboration key, not an authoritative id.

### 5.3 WorldObject

`WorldObject` is a durable real-world thing with stable identity.

Examples:

```text
vessel, aircraft, satellite, facility, pipeline, datacenter, refinery, organization,
person, location, military_unit, weapon_system
```

Required fields:

```text
world_object_id: stable id
canonical_name: display name
object_type: controlled enum
identifiers: provider identifiers such as mmsi, imo, icao24, callsign, norad_id,
             wikidata_id, iso3, m49, aliases
first_seen: timestamp
last_seen: timestamp
current_lat: optional latest fused latitude
current_lon: optional latest fused longitude
confidence: 0.0-1.0
status: active | inactive | stale | disputed | unknown
```

Identifier-first objects use deterministic identity:

```text
vessel: wo_vessel_mmsi_<mmsi>
aircraft: wo_aircraft_icao24_<icao24>
satellite: wo_satellite_norad_<norad_id>
country/location with M49: wo_location_m49_<m49>
wikidata-backed facility: wo_facility_wd_<qid>
```

Fallback objects use a canonical hash:

```text
wo_<object_type>_<sha256(normalized_name + primary_geo_bucket + source_namespace)[:12]>
```

### 5.4 IncidentCandidate

`IncidentCandidate` is a time-bounded cluster of observations that may describe the
same event.

Examples:

```text
explosion near a port
thermal anomaly cluster
conflict escalation
earthquake/disaster
sanction announcement
major infrastructure outage
```

Required fields:

```text
incident_id: stable id
title: short generated or deterministic title
event_type: codebook-compatible event type
severity: low | medium | high | critical
time_window_start: timestamp
time_window_end: timestamp
centroid_lat: optional latitude
centroid_lon: optional longitude
geometry: optional cluster geometry
confidence: 0.0-1.0
status: new | correlated | needs_review | escalated | briefed | dismissed
```

The incident model should reuse the existing event codebook where possible. Unknown
or weakly classified records use `other.unclassified` until review or classifier
evidence improves the type.

### 5.5 FusionLink

`FusionLink` records why an observation was linked, rejected, or sent to review.

Required fields:

```text
fusion_link_id: stable hash
observation_id: linked observation
target_id: world_object_id or incident_id
target_kind: world_object | incident
match_score: 0.0-1.0
decision: auto_linked | needs_review | analyst_linked | rejected
match_reasons: list of reason codes
reason_detail: short human-readable explanation for audit review
created_at: timestamp
decided_by: system | server-bound analyst actor
review_item_id: optional ReviewItem link
```

Reason codes are explicit and testable:

```text
identifier_exact
alias_exact
name_similarity
geo_within_threshold
time_window_overlap
source_corroboration
track_continuity
type_compatible
llm_suggested
analyst_override
conflict_detected
```

`reason_detail` is required when `analyst_override`, `conflict_detected`, or
`llm_suggested` appears in `match_reasons`.

### 5.6 Confidence Semantics

Confidence values are comparable only within their entity class unless explicitly
derived by the formulas below.

`SourceRef.credibility_score`:

```text
provider trust score from configuration or source registry
0.90 official sensor/provider feed
0.75 established public dataset or institutional source
0.60 known media/feed source
0.50 unknown source default
0.30 low-quality or frequently duplicated source
```

`Observation.confidence`:

```text
clamp(source_credibility_score
      * extraction_method_weight
      * payload_quality_weight
      * time_quality_weight,
      0.0,
      1.0)
```

Weights:

```text
sensor/deterministic extraction: 1.00
analyst entry: 0.95
LLM extraction with schema validation: 0.80
vision detection: detector_confidence when implemented
payload has exact identifier: 1.00
payload has name+geo+time only: 0.85
payload missing observed_at and falls back to fetched_at: 0.70
payload missing geometry for spatial source: 0.60
```

`FusionLink.match_score` is the matcher score and is not a source confidence.

`WorldObject.confidence`:

```text
max(confirmed_identifier_score,
    weighted_mean(linked Observation.confidence by source uniqueness and recency))
```

Identifier-backed objects start at `0.90` when the identifier is valid and type
compatible. Analyst-confirmed objects can reach `1.00`.

`IncidentCandidate.confidence`:

```text
clamp(weighted_mean(observation.confidence)
      + corroboration_bonus
      - conflict_penalty,
      0.0,
      1.0)
```

Corroboration bonus is `+0.05` per independent source type after the first, capped at
`+0.20`. Conflict penalty is `-0.20` for material contradiction and forces
`needs_review`.

`ReviewItem.confidence` is the system confidence in the recommended action, not the
truth of the underlying claim.

---

## 6. Matching Strategy

### 6.1 Deterministic Matchers

Deterministic matchers run before fuzzy or LLM-assisted logic.

Rules:

```text
AIS MMSI -> WorldObject vessel
ADS-B icao24 -> WorldObject aircraft
TLE NORAD id -> WorldObject satellite
country M49/ISO3 -> WorldObject location
Wikidata QID -> WorldObject facility/location/organization
existing infrastructure source_url + normalized name + coordinate bucket -> facility
```

These matches can auto-link when the source identifier is valid and the object type is
compatible.

### 6.2 Spatiotemporal Matchers

Spatiotemporal matchers cluster observations by distance, time window, type
compatibility, and source corroboration.

Phase 1 deliberately does not perform fuzzy cross-gap track stitching for moving
objects. AIS/ADS-B/TLE moving-object observations auto-link only through exact
identifiers. Any continuity-based link without an exact identifier becomes
`needs_review` and belongs to the future Realtime Track Store if it needs automation.

Default incident thresholds for Phase 1:

```text
same incident candidate:
  max_distance_km = 25 km for conflict/disaster/news observations
  max_time_gap = 24 hours for breaking events
  max_time_gap = 7 days for slow-burn political/economic events

thermal/news corroboration:
  FIRMS within 25 km and 12 hours of RSS/GDELT explosion/fire/conflict observation
  FIRMS match reason must be "thermal_corroboration", not exact location proof
```

Thresholds are constants in Phase 1 and configuration in Phase 2 after evaluation.
FIRMS coordinates are satellite pixel centers; they corroborate regional thermal
activity and do not prove exact facility-level location.

### 6.3 Fuzzy Entity Matching

Fuzzy matching applies only after deterministic identifiers fail.

Signals:

```text
normalized name similarity
alias overlap
same object type
same country or region
nearby coordinates
overlapping validity window
shared source references
graph neighborhood similarity
```

Phase 1 uses simple, testable scoring. LLMs may propose candidate aliases, but they do
not auto-merge objects. Any low-confidence or LLM-suggested merge creates a
`ReviewItem`.

### 6.4 Match Score Bands

```text
0.90-1.00: auto_linked when deterministic or strongly corroborated
0.65-0.89: needs_review
0.35-0.64: keep as unmatched candidate; show as low-confidence relation only in review
0.00-0.34: rejected or ignored for linking
```

Conflicts override score. A high score with contradictory type, impossible movement,
or incompatible identifiers becomes `needs_review`.

---

## 7. Review Workflow

Review is the human control point between source observations and accepted knowledge.

Review states:

```text
new
correlated
needs_review
escalated
briefed
dismissed
```

`ReviewItem` fields:

```text
review_item_id
kind: entity_match | incident_cluster | source_conflict | analyst_note
status
priority: low | medium | high | critical
summary
target_id
candidate_observation_ids
candidate_world_object_ids
candidate_incident_ids
recommended_action: link | split | dismiss | escalate | brief
confidence
created_at
updated_at
assigned_to
decision_log
```

The enum is intentionally closed for Phase 1. TASK-107 or a later Vision Producer
spec may add `vision_detection`.

Decision log entries:

```text
timestamp
actor: system | server-bound analyst actor
action
reason
before
after
```

Actions:

```text
approve link
reject link
merge objects
split incident
escalate
mark briefed
dismiss
attach analyst note
```

Every analyst action writes an auditable event and preserves the original
observations. Dismissal does not delete evidence; it changes review status and records
the reason.

---

## 8. Neo4j Graph Contract

Neo4j should store fusion entities with explicit labels and relationships.

Labels:

```text
:SourceRef
:Observation
:WorldObject
:IncidentCandidate
:FusionLink
:ReviewItem
```

Relationships:

```text
(:Observation)-[:FROM_SOURCE]->(:SourceRef)
(:Observation)-[:LINKED_TO {score, decision, reasons}]->(:WorldObject)
(:Observation)-[:PART_OF {score, decision, reasons}]->(:IncidentCandidate)
(:IncidentCandidate)-[:INVOLVES]->(:WorldObject)
(:ReviewItem)-[:REVIEWS]->(:FusionLink)
(:ReviewItem)-[:HAS_EVIDENCE]->(:Observation)
(:WorldObject)-[:PROJECTS_TO]->(:Entity)
(:IncidentCandidate)-[:PROJECTS_TO]->(:Event)
(:SourceRef)-[:PROJECTS_TO]->(:Source)
(:WorldObject)-[:ALIAS_OF | LOCATED_AT]->(...)
```

Existing `:Entity`, `:Event`, `:Location`, and `:Source` nodes remain supported.
Phase 1 should bridge accepted fusion objects into the existing graph shape rather
than replace it:

```text
accepted WorldObject -> :Entity projection
accepted IncidentCandidate -> :Event projection
SourceRef -> :Source projection
Observation geometry -> :Location when applicable
```

This protects current graph query tools and frontend Graph Explorer while the fusion
model matures.

Fusion nodes are canonical. `:Entity`, `:Event`, and `:Source` nodes are compatibility
projections. Projection writes must happen in the same Neo4j transaction as the
accepted fusion state change. Projection nodes carry back-reference properties:

```text
Entity.fusion_world_object_id
Event.fusion_incident_id
Source.fusion_source_id
```

The projection relationship makes disagreements diagnosable: if a projection is
missing, readers can show the canonical fusion node and flag projection status instead
of silently disagreeing.

---

## 9. Qdrant Contract

Qdrant stores retrieval documents for analyst and agent context, not authoritative
identity.

Documents to index:

```text
observation narrative
incident candidate summary
world object dossier summary
review decision summary
source excerpt
```

Every Qdrant payload must include:

```text
doc_kind
source_ids
observation_ids
world_object_ids
incident_ids
review_item_ids
observed_at
valid_from
valid_until
lat
lon
confidence
```

Agents retrieving Qdrant context must be able to surface the lineage ids in final
answers. This directly closes the TASK-014 lineage gap.

Payload policy:

```text
Qdrant payloads store public lineage ids and short public excerpts only.
No PII, crew rosters, private contact fields, access tokens, or raw analyst-sensitive
payloads are embedded for agent retrieval.
Sensitive raw payloads remain in the source system or Neo4j properties marked
classification="sensitive" and are excluded from RAG indexing.
```

---

## 10. Backend API Contract

Phase 1 endpoints:

```text
GET  /api/v1/fusion/objects
GET  /api/v1/fusion/objects/{world_object_id}
GET  /api/v1/fusion/objects/{world_object_id}/timeline
GET  /api/v1/fusion/incidents
GET  /api/v1/fusion/incidents/{incident_id}
GET  /api/v1/fusion/incidents/{incident_id}/timeline
GET  /api/v1/fusion/review
POST /api/v1/fusion/review/{review_item_id}/decision
GET  /api/v1/fusion/observations/{observation_id}/lineage
```

Internal ingestion endpoints:

```text
POST /internal/fusion/source-refs
POST /internal/fusion/observations
POST /internal/fusion/observations/batch
```

The internal endpoints are service-to-service only and validate payloads with
Pydantic. They do not accept arbitrary Cypher or raw LLM output.

Internal endpoint enforcement:

```text
Every /internal/fusion request must include:
  X-ODIN-Service: service name
  X-ODIN-Timestamp: unix seconds
  X-ODIN-Signature: hex HMAC-SHA256(timestamp + "." + raw_body)

The backend verifies the signature with FUSION_INTERNAL_HMAC_SECRET, rejects requests
older than 300 seconds, rejects missing service names, and logs the service actor.
```

These endpoints are still mounted on the backend service, but path prefix alone is
not trusted. If `FUSION_INTERNAL_HMAC_SECRET` is unset, internal write endpoints refuse
requests at startup or return 503 in local development.

Review endpoint actor binding:

```text
POST /api/v1/fusion/review/{review_item_id}/decision requires:
  Authorization: Bearer <FUSION_REVIEW_TOKEN>

The request body may include action and reason but must not include actor.
The backend derives actor from FUSION_REVIEW_ACTOR after token validation.
```

This matches the current single-user/no-auth posture without letting callers forge
`decided_by`.

---

## 11. Frontend Contract

Worldview should add fusion-aware surfaces without replacing existing layers.

New UI surfaces:

```text
Fusion Review panel
WorldObject detail branch in InspectorPanel
IncidentCandidate detail branch in InspectorPanel
Source Lineage drawer or section
Timeline strip for selected object/incident
```

Layer behavior:

```text
raw observations: optional low-emphasis layer for debugging and analyst review
fused objects: canonical object markers/tracks
incident candidates: cluster/event markers with status color
review-needed: distinct review glyph and filter
```

Inspector must show:

```text
canonical name/title
status
confidence
last seen / observed time
source count
top source refs
match reasons
review status
timeline affordance
```

The UI must make source lineage easier to inspect, not hide it behind agent prose.

---

## 12. Ingestion Migration Strategy

Migration is incremental. Existing collectors continue to work while they learn to
emit observations.

Phase 1 producers:

```text
ADS-B / flights -> aircraft observations with icao24
AIS / vessels -> vessel observations with mmsi
TLE / satellites -> satellite observations with norad_id and epoch
FIRMS -> fire/thermal observations with point geometry
GDELT raw -> event/news observations with time, location, codebook type
RSS/NotebookLM -> extracted event/entity observations with SourceRef lineage
Analyst notes -> analyst observations attached to objects or incidents
```

Each producer owns only normalization into `SourceRef` and `Observation`. The backend
fusion service owns matching, deterministic fusion writes, review generation, and
review-decision writes.

NotebookLM migration:

```text
Slice D makes nlm_ingest emit Observations in parallel with its existing graph writes.
nlm_ingest/write_templates.py remains a compatibility shim during Phase 1.
Phase 2 retires direct NLM graph writes after fusion projections cover the same
Entity/Event/Source read surface.
```

Phase 1 volume caps:

```text
AIS observations: at most one observation per MMSI per 5 minutes
ADS-B observations: at most one observation per icao24 per 5 minutes
TLE observations: one observation per NORAD id per new TLE epoch
FIRMS observations: one observation per hotspot record after existing dedupe
GDELT/RSS/NLM observations: only records passing existing codebook/source filters
Raw high-volume track points: not stored in Neo4j Phase 1
```

Retention:

```text
WorldObject, IncidentCandidate, FusionLink, ReviewItem, and SourceRef nodes persist.
High-volume raw Observations from AIS/ADS-B keep 90 days in Neo4j Phase 1.
Text-source, FIRMS, TLE, and analyst Observations persist until an explicit retention
job is designed.
```

---

## 13. Service Ownership

Phase 1 follows the existing write/read separation:

```text
packages/odin-fusion-models/
  Owns shared Pydantic models, enums, id builders, normalization helpers,
  confidence helpers, and match reason constants.
  Is imported by backend, data-ingestion, intelligence, and tests via path dependency.

services/data-ingestion/fusion/
  Owns feed-specific Observation producer adapters.
  Does not own Neo4j fusion write templates.
  Sends signed internal requests to backend fusion endpoints.

services/intelligence/fusion/
  Owns match scoring, incident clustering, review recommendation, and agent-facing
  read helpers.
  Does not perform raw feed collection.
  Does not write arbitrary Cypher.

services/backend/app/routers/fusion.py
  Owns external REST endpoints for fused objects, incidents, review queue, and
  lineage.
  Reads Neo4j through parameterized query helpers.
  Verifies service HMACs for internal ingestion writes.
  Sends review decisions through backend deterministic write helpers only.

services/backend/app/services/fusion_write.py
  Owns deterministic Cypher templates for SourceRef, Observation, FusionLink,
  ReviewItem, WorldObject, IncidentCandidate, and projection writes.
  Owns review-decision write transactions and audit-log persistence.

services/frontend/src/components/fusion/
  Owns Review panel, lineage display, and timeline UI components.
  Existing Worldview components import these surfaces rather than embedding all
  fusion UI into WorldviewPage.
```

Cross-service model drift is controlled by the shared package. Contract tests still
verify that each service depends on the same `odin-fusion-models` version or path.
Text-based drift tests are fallback only where Docker build contexts temporarily make
imports impossible during migration.

---

## 14. Agent Contract

Agents may read fusion context and propose candidate actions, but they do not perform
unreviewed writes that alter accepted identity.

Allowed:

```text
query object timeline
query source lineage
summarize review item evidence
propose match reasons
classify observation text into codebook type
```

Not allowed:

```text
merge WorldObjects without review
mark an incident briefed without analyst action
write Cypher directly
delete observations or sources
```

For any answer involving fused claims, agents must include source-backed references
from `SourceRef` or review decision summaries.

---

## 15. Error Handling and Conflict Rules

Ingestion errors:

```text
invalid SourceRef -> reject source record with validation error
invalid Observation -> reject observation and keep collector state retryable
duplicate Observation -> idempotent update
missing geometry -> allowed only for non-spatial observations
missing observed_at -> fallback to published_at, then fetched_at, with lower confidence
internal request missing/invalid HMAC -> reject with 401 and do not parse body further
review request missing/invalid operator token -> reject with 401 and no decision log write
```

Fusion conflicts:

```text
same identifier, incompatible object type -> needs_review
same moving object, impossible speed -> needs_review
same incident cluster, contradictory source claims -> needs_review
low-credibility source contradicts high-credibility source -> needs_review with priority based on severity
```

Confidence is never only the model score. It combines source credibility, extraction
method, match score, recency, and corroboration count.

---

## 16. Testing Strategy

Backend and fusion service tests:

```text
SourceRef id is stable for equivalent normalized payloads
Observation id is stable across replay
Observation id changes when source_id changes but claim_fingerprint stays stable for mirrored claims
AIS MMSI creates or links the same vessel WorldObject
ADS-B icao24 creates or links the same aircraft WorldObject
TLE NORAD id creates or links the same satellite WorldObject
FIRMS plus GDELT within threshold creates IncidentCandidate
FIRMS corroboration does not claim exact facility-level location
ambiguous fuzzy match creates ReviewItem
conflicting identifiers create ReviewItem
approved review decision updates FusionLink decision
rejected review decision preserves Observation and writes decision log
lineage endpoint returns SourceRef -> Observation -> FusionLink -> target chain
internal fusion endpoints reject missing/invalid HMAC
review decision endpoint derives actor server-side and ignores body actor
Neo4j write templates use parameter binding only
graph read endpoints reject write operations
accepted fusion state and compatibility projection commit atomically
```

Frontend tests:

```text
Review panel lists items by status and priority
review decision action calls backend with explicit action and reason
Inspector renders WorldObject source lineage
Inspector renders IncidentCandidate timeline summary
LayersPanel includes fusion/review layer toggles if enabled
Worldview selection can open a fused object without breaking existing layer selections
```

Integration smoke:

```text
ingest two source records about the same vessel
verify one WorldObject, two Observations, two SourceRefs, two FusionLinks
verify timeline returns both observations in order
verify review queue is empty for deterministic identifier match
ingest ambiguous GDELT/RSS/FIRMS cluster
verify IncidentCandidate plus ReviewItem
```

---

## 17. Acceptance Criteria

The feature is accepted when:

1. At least AIS, ADS-B, TLE, FIRMS, and one text source can emit SourceRefs and
   Observations.
2. Deterministic matchers create stable WorldObjects for vessel MMSI, aircraft
   icao24, and satellite NORAD id.
3. At least one spatiotemporal incident matcher creates IncidentCandidates from
   multiple observations.
4. Ambiguous or conflicting links create ReviewItems instead of silently merging.
5. Review decisions are persisted with a decision log.
6. Source lineage can be retrieved for any fused object or incident.
7. Accepted WorldObjects and IncidentCandidates are projected into the existing graph
   shape so current graph search and Graph Explorer do not regress.
8. Worldview can display fused object/incident details with source lineage in the
   Inspector.
9. Tests prove idempotent replay, deterministic identity, parameter-bound graph
   writes, and review-state transitions.
10. Vision can be added later by writing observations; no fusion model changes are
    required for basic vision detections.
11. Internal fusion writes require HMAC and review decisions derive actor server-side.
12. Phase 1 sensor observations respect the 5-minute AIS/ADS-B cadence cap and do not
    store full-rate track streams in Neo4j.

---

## 18. Delivery Slices

Recommended implementation slices:

```text
Slice A: Models and deterministic ids
  packages/odin-fusion-models with SourceRef, Observation, WorldObject,
  IncidentCandidate, FusionLink, ReviewItem, ids, normalization, confidence

Slice B: Neo4j write templates and read queries
  backend-owned parameter-bound writes, projection transactions, timeline reads,
  lineage reads, HMAC-protected internal endpoints

Slice C: Deterministic matchers
  AIS MMSI, ADS-B icao24, TLE NORAD id

Slice D: Observation producers
  adapt selected existing collectors and nlm_ingest to emit observations in parallel
  with old writes

Slice E: Incident clustering
  FIRMS + GDELT/RSS spatiotemporal correlation

Slice F: Review queue API
  list, filter, decide, server-bound actor, decision log

Slice G: Frontend review and lineage
  Review panel, Inspector branches, timeline/source lineage display

Slice H: Agent and RAG lineage
  SourceRef propagation through retrieval and answer synthesis
```

Each slice should be independently testable and should not require the vision
pipeline.

---

## 19. Out-of-Scope Until Follow-Up Specs

Follow-up specs should cover:

```text
TASK-107 Vision Producer: image detections -> observations
Fusion Evaluation Harness: labeled scenarios and precision/recall metrics
Hybrid Qdrant v2 migration: dense+sparse retrieval for fusion documents
Realtime Track Store: high-volume AIS/ADS-B track interpolation and retention
Analyst Briefing Workflow: promoted incidents -> reports/dossiers
```
