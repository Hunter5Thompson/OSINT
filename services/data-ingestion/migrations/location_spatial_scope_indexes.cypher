CREATE RANGE INDEX location_country_scope_derivation IF NOT EXISTS
FOR (l:Location) ON (l.country_scope_key, l.spatial_derivation_revision);

CREATE RANGE INDEX location_admin1_scope_derivation IF NOT EXISTS
FOR (l:Location) ON (l.admin1_scope_key, l.spatial_derivation_revision);

CREATE RANGE INDEX location_admin2_scope_derivation IF NOT EXISTS
FOR (l:Location) ON (l.admin2_scope_key, l.spatial_derivation_revision);

CREATE POINT INDEX location_geo IF NOT EXISTS
FOR (l:Location) ON (l.geo);
