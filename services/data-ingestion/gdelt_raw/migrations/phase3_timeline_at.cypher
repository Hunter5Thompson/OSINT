// Phase 3: canonical timeline anchor for existing GDELT events.
// Idempotent (timeline_at IS NULL guard), batched (CALL {} IN TRANSACTIONS),
// resumable. Run as a documented operational one-shot, NOT from the scheduler.
CREATE INDEX event_timeline_at IF NOT EXISTS
  FOR (e:Event) ON (e.timeline_at);
MATCH (e:GDELTEvent)
WHERE e.timeline_at IS NULL AND e.date_added IS NOT NULL
CALL { WITH e
  SET e.timeline_at = e.date_added, e.time_basis = 'indexed'
} IN TRANSACTIONS OF 10000 ROWS;
