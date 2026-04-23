"""Read-only Cypher templates for Report + Message graph access."""

REPORT_NEXT_PARAGRAPH = (
    "MATCH (r:Report) "
    "RETURN coalesce(max(r.paragraph_num), 0) + 1 AS next_paragraph"
)

REPORT_LIST = (
    "MATCH (r:Report) "
    "RETURN "
    "  r.id AS id, "
    "  coalesce(r.paragraph_num, 0) AS paragraph_num, "
    "  coalesce(r.stamp, '') AS stamp, "
    "  coalesce(r.title, '') AS title, "
    "  coalesce(r.status, 'Draft') AS status, "
    "  coalesce(r.confidence, 0.0) AS confidence, "
    "  coalesce(r.location, '') AS location, "
    "  coalesce(r.coords, '') AS coords, "
    "  coalesce(r.findings, []) AS findings, "
    "  coalesce(r.metrics_json, '[]') AS metrics_json, "
    "  coalesce(r.context, '') AS context, "
    "  coalesce(r.body_title, '') AS body_title, "
    "  coalesce(r.body_paragraphs, []) AS body_paragraphs, "
    "  coalesce(r.margin_json, '[]') AS margin_json, "
    "  coalesce(r.sources, []) AS sources, "
    "  toString(r.created_at) AS created_at, "
    "  toString(r.updated_at) AS updated_at "
    "ORDER BY coalesce(r.paragraph_num, 0) DESC "
    "LIMIT $limit"
)

REPORT_BY_ID = (
    "MATCH (r:Report {id: $report_id}) "
    "RETURN "
    "  r.id AS id, "
    "  coalesce(r.paragraph_num, 0) AS paragraph_num, "
    "  coalesce(r.stamp, '') AS stamp, "
    "  coalesce(r.title, '') AS title, "
    "  coalesce(r.status, 'Draft') AS status, "
    "  coalesce(r.confidence, 0.0) AS confidence, "
    "  coalesce(r.location, '') AS location, "
    "  coalesce(r.coords, '') AS coords, "
    "  coalesce(r.findings, []) AS findings, "
    "  coalesce(r.metrics_json, '[]') AS metrics_json, "
    "  coalesce(r.context, '') AS context, "
    "  coalesce(r.body_title, '') AS body_title, "
    "  coalesce(r.body_paragraphs, []) AS body_paragraphs, "
    "  coalesce(r.margin_json, '[]') AS margin_json, "
    "  coalesce(r.sources, []) AS sources, "
    "  toString(r.created_at) AS created_at, "
    "  toString(r.updated_at) AS updated_at"
)

REPORT_MESSAGES_BY_REPORT_ID = (
    "MATCH (r:Report {id: $report_id})-[rel:HAS_MESSAGE]->(m:Message) "
    "RETURN "
    "  m.id AS id, "
    "  coalesce(m.role, 'system') AS role, "
    "  coalesce(m.text, '') AS text, "
    "  toString(m.ts) AS ts, "
    "  coalesce(m.refs, []) AS refs, "
    "  coalesce(rel.ordering, 0) AS ordering "
    "ORDER BY rel.ordering ASC "
    "LIMIT $limit"
)

REPORT_COUNT = "MATCH (r:Report) RETURN count(r) AS count"
