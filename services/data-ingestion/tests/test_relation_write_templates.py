from nlm_ingest.write_templates import CANONICAL_RELATION_TEMPLATES
from nlm_ingest.relation_rules import RELATION_ROLE_RULES


def test_template_dict_only_canonical_types():
    canonical = {k for k, v in RELATION_ROLE_RULES.items() if v.mode == "canonical"}
    assert set(CANONICAL_RELATION_TEMPLATES) == canonical


def test_targets_has_no_template():
    assert "TARGETS" not in CANONICAL_RELATION_TEMPLATES


def test_templates_match_name_and_type_and_never_write_data_source():
    for t in CANONICAL_RELATION_TEMPLATES.values():
        assert "name:$source, type:$source_type" in t
        assert "name:$target, type:$target_type" in t
        assert "data_source" not in t            # SUV-safety
        assert "+ [$prov_key]" in t              # list-concat form
        assert "r.support_count = size(coalesce(r.provenance_keys,[]))" in t


def test_no_dynamic_label_in_keys():
    from nlm_ingest.schemas import RelationType
    from typing import get_args
    assert set(CANONICAL_RELATION_TEMPLATES) <= set(get_args(RelationType))
