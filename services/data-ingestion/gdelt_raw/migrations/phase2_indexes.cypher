CREATE INDEX event_source_date IF NOT EXISTS
  FOR (e:Event) ON (e.source, e.date_added);
CREATE INDEX event_cameo_root IF NOT EXISTS
  FOR (e:Event) ON (e.cameo_root);
CREATE INDEX event_codebook_type IF NOT EXISTS
  FOR (e:Event) ON (e.codebook_type);
CREATE INDEX doc_source_gdelt_date IF NOT EXISTS
  FOR (d:Document) ON (d.source, d.gdelt_date);
CREATE INDEX doc_url IF NOT EXISTS
  FOR (d:Document) ON (d.url);
CREATE INDEX entity_name_type IF NOT EXISTS
  FOR (e:Entity) ON (e.normalized_name, e.type);
CREATE POINT INDEX location_geo IF NOT EXISTS
  FOR (l:Location) ON (l.geo);
