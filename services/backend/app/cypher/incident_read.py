"""Read Cypher templates for Incident retrieval. READ-ONLY (project rule)."""

INCIDENT_LIST_OPEN = (
    "MATCH (i:Incident) "
    "WHERE i.status IN ['open', 'promoted'] "
    "RETURN "
    "  i.id AS id, i.kind AS kind, i.title AS title, i.severity AS severity, "
    "  i.lat AS lat, i.lon AS lon, i.location AS location, i.status AS status, "
    "  toString(i.trigger_ts) AS trigger_ts, "
    "  toString(i.closed_ts) AS closed_ts, "
    "  i.sources AS sources, i.layer_hints AS layer_hints, "
    "  i.timeline_json AS timeline_json "
    "ORDER BY i.trigger_ts DESC "
    "LIMIT $limit"
)

INCIDENT_BY_ID = (
    "MATCH (i:Incident {id: $incident_id}) "
    "RETURN "
    "  i.id AS id, i.kind AS kind, i.title AS title, i.severity AS severity, "
    "  i.lat AS lat, i.lon AS lon, i.location AS location, i.status AS status, "
    "  toString(i.trigger_ts) AS trigger_ts, "
    "  toString(i.closed_ts) AS closed_ts, "
    "  i.sources AS sources, i.layer_hints AS layer_hints, "
    "  i.timeline_json AS timeline_json"
)

