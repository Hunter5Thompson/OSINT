# SUV Track 2b procurement load — reversal recipe (additive load, 2026-06-18)
Load is purely additive: +30 PROCUREMENT_PROGRAM nodes (data_source="suv.report"), +30 PROCURES,
+6 CONTRACTED_TO, +12 CONCERNS_SYSTEM edges (all data_source="suv.report"), +30 Qdrant points
(point-id uuid5(SUV_QDRANT_NAMESPACE,"suv_procurement_program|"+title)). NO existing node/edge mutated.
Reverse (Neo4j):
  MATCH (p:Entity {type:"PROCUREMENT_PROGRAM", data_source:"suv.report"}) DETACH DELETE p;
  // (deletes the 30 program nodes + their PROCURES/CONTRACTED_TO/CONCERNS_SYSTEM edges in one go)
Reverse (Qdrant): delete points whose payload.source="suv_structured" AND payload.source_type="dataset"
  AND payload.program_status IS NOT NULL  (i.e. the per-program profiles), or by the namespaced point-ids.
