// Re-base Events whose timeline_at lies in the future (LLM read a *planned* date as
// occurred_at, e.g. "Kenya's 2027 elections"). New writes are guarded in
// pipeline._resolve_timeline; this repairs the legacy rows.
//
// Reversible: the claimed date is kept in ev.claimed_future_at. Revert with
//   MATCH (ev:Event) WHERE ev.claimed_future_at IS NOT NULL
//   SET ev.timeline_at = ev.claimed_future_at, ev.time_basis = 'occurred'
//   REMOVE ev.claimed_future_at;
//
// The describing Documents carry no published/ingested time, only updated_at (last
// re-merge), so that is the honest upper bound of ingestion -> time_basis 'ingested'.
//
// Dry run first:
//   MATCH (ev:Event) WHERE ev.timeline_at > datetime() + duration('P1D')
//   RETURN count(ev);

MATCH (ev:Event)
WHERE ev.timeline_at > datetime() + duration('P1D')
OPTIONAL MATCH (d:Document)-[:DESCRIBES]->(ev)
WITH ev, min(d.updated_at) AS doc_seen
WHERE doc_seen IS NOT NULL  // never fabricate a time; orphans stay for manual review
SET ev.claimed_future_at = ev.timeline_at,
    ev.timeline_at = doc_seen,
    ev.time_basis = 'ingested'
RETURN count(ev) AS rebased;
