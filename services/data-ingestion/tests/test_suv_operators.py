from pathlib import Path

import pytest

from suv_structured.operators import (
    OperatorEntry, load_operators, match_preflight_offenders, operators_by_slug,
)

SEED = Path(__file__).parent.parent / "suv_structured" / "seeds" / "suv_operators.yaml"


def test_committed_seed_loads_five_operators():
    ops = load_operators(SEED)
    assert len(ops) == 5
    by_slug = operators_by_slug(ops)

    heer = by_slug["hauptwaffensysteme-des-heeres"]
    assert heer.decision == "match"
    assert heer.target_name == "Deutsches Heer"
    assert heer.target_type == "MILITARY_UNIT"

    lw = by_slug["hauptwaffensysteme-der-luftwaffe"]
    assert lw.decision == "match"
    assert lw.target_name == "Deutsche Luftwaffe"
    assert lw.target_type == "MILITARY_UNIT"

    marine = by_slug["hauptwaffensysteme-der-marine"]
    assert marine.decision == "match"
    assert marine.target_name == "Deutsche Marine"
    assert marine.target_type == "MILITARY_UNIT"

    cir = by_slug["hauptwaffensysteme-des-cyber-und-informationsraums"]
    assert cir.decision == "create"
    assert cir.target_name == "Cyber- und Informationsraum"
    assert cir.target_type == "MILITARY_UNIT"
    assert cir.create_properties == {"aliases": ["CIR"]}

    unt = by_slug["hauptwaffensysteme-des-unterstuetzungsbereichs"]
    assert unt.decision == "match"
    assert unt.target_name == "Unterstützungsbereich"
    assert unt.target_type == "ORGANIZATION"


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
