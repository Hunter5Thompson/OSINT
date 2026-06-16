// Apply ONLY after rekey_incident_locations.run(apply) has run and
// verify_no_duplicate_loc_keys(client) returns []. Neo4j 5 Community supports
// single-property uniqueness constraints. Unique constraints allow NULLs, so
// any Location without a loc_key is unaffected.
CREATE CONSTRAINT location_loc_key_unique IF NOT EXISTS
FOR (l:Location) REQUIRE l.loc_key IS UNIQUE;
