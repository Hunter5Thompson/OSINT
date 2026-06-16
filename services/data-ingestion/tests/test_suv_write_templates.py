from suv_structured.write_templates import LINK_COMPANY_COUNTRY, UPSERT_COMPANY


def test_upsert_company_is_org_typed_and_alias_append_dedup():
    assert 'MERGE (c:Entity {name: $name, type: "ORGANIZATION"})' in UPSERT_COMPANY
    # aliases appended + de-duplicated, never overwritten
    assert "coalesce(c.aliases, [])" in UPSERT_COMPANY
    # nullable scalars preserved on null param (no blind clobber)
    assert "c.hq_country = coalesce($hq_country, c.hq_country)" in UPSERT_COMPANY
    assert 'c.sector = "defense"' in UPSERT_COMPANY


def test_link_company_country_is_match_only_for_location():
    # Bridge: HQ-country endpoint MATCHes the existing Entity{type:"LOCATION"} node,
    # never a COUNTRY node and never the separate :Location-label node.
    assert "[r:HEADQUARTERED_IN]" in LINK_COMPANY_COUNTRY
    assert 'MATCH (co:Entity {type: "LOCATION"})' in LINK_COMPANY_COUNTRY
    assert 'type: "COUNTRY"' not in LINK_COMPANY_COUNTRY      # no longer targets COUNTRY
    assert "(co:Location" not in LINK_COMPANY_COUNTRY          # never the :Location label node
    assert "MERGE (co" not in LINK_COMPANY_COUNTRY             # MATCH-only endpoint
    assert "MERGE (c)-[r:HEADQUARTERED_IN]->(co)" in LINK_COMPANY_COUNTRY


def test_upsert_products_uses_case_preservation():
    # empty product list must preserve existing (CASE), non-empty replaces
    assert "CASE WHEN size($products) > 0" in UPSERT_COMPANY


def test_link_company_endpoint_is_match_not_merge():
    # the COMPANY endpoint in LINK is MATCH-ed (never MERGE-d into existence here)
    assert 'MATCH (c:Entity {name: $name, type: "ORGANIZATION"})' in LINK_COMPANY_COUNTRY
    assert "MERGE (c:Entity" not in LINK_COMPANY_COUNTRY
    # relation gets a last_seen staleness stamp
    assert "r.last_seen = datetime()" in LINK_COMPANY_COUNTRY
