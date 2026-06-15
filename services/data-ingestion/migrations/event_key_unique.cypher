// Apply ONLY after backfill_event_key.py --apply has run and reports 0 duplicate keys.
// Unique constraints allow NULLs, so :GDELTEvent nodes (which keep event_id, no event_key)
// are unaffected.
CREATE CONSTRAINT event_key_unique IF NOT EXISTS
FOR (ev:Event) REQUIRE ev.event_key IS UNIQUE;
