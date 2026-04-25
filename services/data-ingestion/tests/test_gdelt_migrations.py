from gdelt_raw.migrations.apply import (
    read_cypher_file, SOURCE_DUP_PREFLIGHT_QUERY,
)


def test_phase1_file_contains_expected_constraints():
    text = read_cypher_file("phase1_constraints.cypher")
    assert "gdelt_event_id_unique" in text
    assert "gdelt_doc_id_unique" in text
    assert "source_name_unique" in text
    assert "theme_code_unique" in text
    assert "GDELTEvent" in text
    assert "GDELTDocument" in text


def test_phase2_file_contains_indexes():
    text = read_cypher_file("phase2_indexes.cypher")
    assert "event_source_date" in text
    assert "event_cameo_root" in text
    assert "location_geo" in text


def test_source_preflight_query_is_parameterless():
    assert "name, count" in SOURCE_DUP_PREFLIGHT_QUERY or \
           "count(*)" in SOURCE_DUP_PREFLIGHT_QUERY
