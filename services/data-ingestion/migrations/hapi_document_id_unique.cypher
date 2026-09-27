// Operator-run prerequisite for HAPI scoped Document writes.
// Run the preflight below first and resolve any results before applying the
// constraint. Apply this before enabling parallel HAPI writers.
// MATCH (d:HAPIDocument)
// WITH d.doc_id AS doc_id, count(*) AS copies
// WHERE copies > 1
// RETURN doc_id, copies

CREATE CONSTRAINT hapi_document_id_unique IF NOT EXISTS
FOR (d:HAPIDocument) REQUIRE d.doc_id IS UNIQUE;
