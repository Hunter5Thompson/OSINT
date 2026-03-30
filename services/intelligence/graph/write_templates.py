"""
Deterministic Cypher templates for graph writes.

The LLM extracts DATA (JSON) → Pydantic validates → these templates write.
NO LLM-generated Cypher on the write path.
"""

UPSERT_ENTITY = """
MERGE (e:Entity {name: $name, type: $type})
SET e.aliases = $aliases,
    e.confidence = $confidence,
    e.last_seen = datetime()
ON CREATE SET e.id = $id, e.first_seen = datetime()
RETURN e.id
"""

CREATE_EVENT = """
CREATE (ev:Event {
  id: $id, title: $title, summary: $summary,
  timestamp: datetime($timestamp),
  codebook_type: $codebook_type,
  severity: $severity, confidence: $confidence
})
RETURN ev.id
"""

LINK_ENTITY_EVENT = """
MATCH (e:Entity {name: $entity_name})
MATCH (ev:Event {id: $event_id})
MERGE (ev)-[:INVOLVES]->(e)
"""

LINK_EVENT_SOURCE = """
MERGE (s:Source {url: $url})
SET s.name = $source_name, s.last_fetched = datetime()
WITH s
MATCH (ev:Event {id: $event_id})
MERGE (ev)-[:REPORTED_BY]->(s)
"""

UPSERT_DOCUMENT = """
MERGE (d:Document {url: $url})
SET d.title = $title, d.source = $source, d.updated_at = datetime()
RETURN d
"""

UPSERT_ENTITY_WITH_MENTION = """
MERGE (e:Entity {name: $name, type: $type})
SET e.last_seen = datetime()
WITH e
MATCH (d:Document {url: $url})
MERGE (d)-[r:MENTIONS]->(e)
SET r.mention = $mention, r.context = $context
"""

LINK_EVENT_LOCATION = """
MERGE (l:Location {name: $location_name})
SET l.country = $country, l.lat = $lat, l.lon = $lon
WITH l
MATCH (ev:Event {id: $event_id})
MERGE (ev)-[:OCCURRED_AT]->(l)
"""
