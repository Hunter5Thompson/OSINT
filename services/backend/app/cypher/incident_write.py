"""Write Cypher templates for Incident persistence. Parametrised — no LLM."""

INCIDENT_UPSERT = (
    "MERGE (i:Incident {id: $incident_id}) "
    "ON CREATE SET "
    "  i.created_at = datetime($now), "
    "  i.ordinal = $ordinal, "
    "  i.trigger_ts = datetime($trigger_ts) "
    "SET "
    "  i.kind = $kind, "
    "  i.title = $title, "
    "  i.severity = $severity, "
    "  i.lat = $lat, "
    "  i.lon = $lon, "
    "  i.location = $location, "
    "  i.status = $status, "
    "  i.closed_ts = CASE WHEN $closed_ts IS NULL THEN null ELSE datetime($closed_ts) END, "
    "  i.sources = $sources, "
    "  i.layer_hints = $layer_hints, "
    "  i.timeline_json = $timeline_json, "
    "  i.updated_at = datetime($now) "
    "RETURN "
    "  i.id AS id, i.kind AS kind, i.title AS title, i.severity AS severity, "
    "  i.lat AS lat, i.lon AS lon, i.location AS location, i.status AS status, "
    "  toString(i.trigger_ts) AS trigger_ts, "
    "  toString(i.closed_ts) AS closed_ts, "
    "  i.sources AS sources, i.layer_hints AS layer_hints, "
    "  i.timeline_json AS timeline_json"
)

INCIDENT_DELETE = "MATCH (i:Incident {id: $incident_id}) DETACH DELETE i"

INCIDENT_ID_UNIQUE_CONSTRAINT = (
    "CREATE CONSTRAINT incident_id_unique IF NOT EXISTS "
    "FOR (i:Incident) REQUIRE i.id IS UNIQUE"
)
