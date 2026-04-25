from uuid import UUID

from gdelt_raw.ids import (
    build_event_id, build_doc_id, build_location_id,
    qdrant_point_id_for_doc,
)


def test_event_id_format():
    assert build_event_id(1300904663) == "gdelt:event:1300904663"
    assert build_event_id("1300904664") == "gdelt:event:1300904664"


def test_doc_id_format():
    assert build_doc_id("20260425121500-42") == "gdelt:gkg:20260425121500-42"


def test_location_id_with_feature():
    assert build_location_id(feature_id="-3365797") == "gdelt:loc:-3365797"


def test_location_id_fallback_without_feature():
    # Country-only (no feature_id): use a slugged fallback
    lid = build_location_id(feature_id="", country_code="UA", name="Kyiv")
    assert lid == "gdelt:loc:ua:kyiv"


def test_qdrant_point_id_is_deterministic_uuid5():
    doc_id = "gdelt:gkg:20260425121500-42"
    pid_a = qdrant_point_id_for_doc(doc_id)
    pid_b = qdrant_point_id_for_doc(doc_id)
    assert pid_a == pid_b
    # RFC-4122 Version 5
    parsed = UUID(pid_a)
    assert parsed.version == 5
