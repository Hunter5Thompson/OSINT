from pathlib import Path

import pytest

from suv_structured.operators import (
    OperatorEntry, load_operators, match_preflight_offenders, operators_by_slug,
)

SEED = Path(__file__).parent.parent / "suv_structured" / "seeds" / "suv_operators.yaml"


def test_committed_seed_loads_five_operators():
    ops = load_operators(SEED)
    assert len(ops) == 5
    slugs = {o.page_slug for o in ops}
    assert "hauptwaffensysteme-des-heeres" in slugs
    by_slug = operators_by_slug(ops)
    assert by_slug["hauptwaffensysteme-des-heeres"].target_type in ("MILITARY_UNIT", "ORGANIZATION")


def test_invalid_decision_rejected():
    with pytest.raises(ValueError):
        OperatorEntry(page_slug="p", page_label="L", decision="merge",
                      target_name="X", target_type="MILITARY_UNIT")


def test_invalid_target_type_rejected():
    with pytest.raises(ValueError):
        OperatorEntry(page_slug="p", page_label="L", decision="match",
                      target_name="X", target_type="LOCATION")


def test_preflight_flags_non_unique_match_targets():
    counts = {("Deutsches Heer", "MILITARY_UNIT"): 1, ("Luftwaffe", "MILITARY_UNIT"): 2,
              ("Marine", "MILITARY_UNIT"): 0}
    offenders = match_preflight_offenders(counts)
    assert any("Luftwaffe" in o for o in offenders)
    assert any("Marine" in o for o in offenders)
    assert not any("Deutsches Heer" in o for o in offenders)
