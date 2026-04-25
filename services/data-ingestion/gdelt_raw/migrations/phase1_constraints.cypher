CREATE CONSTRAINT gdelt_event_id_unique IF NOT EXISTS
  FOR (e:GDELTEvent) REQUIRE e.event_id IS UNIQUE;

CREATE CONSTRAINT gdelt_doc_id_unique IF NOT EXISTS
  FOR (d:GDELTDocument) REQUIRE d.doc_id IS UNIQUE;

CREATE CONSTRAINT source_name_unique IF NOT EXISTS
  FOR (s:Source) REQUIRE s.name IS UNIQUE;

CREATE CONSTRAINT theme_code_unique IF NOT EXISTS
  FOR (t:Theme) REQUIRE t.theme_code IS UNIQUE;
