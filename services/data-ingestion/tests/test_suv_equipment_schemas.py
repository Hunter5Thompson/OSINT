import pytest

from suv_structured.equipment_schemas import WeaponSystemRow


def test_name_property_is_muster():
    row = WeaponSystemRow(muster="Leopard 2", page_slug="hauptwaffensysteme-des-heeres",
                          suv_url="https://suv.report/hauptwaffensysteme-des-heeres/")
    assert row.name == "Leopard 2"
    assert row.count is None and row.service_end is None


def test_blank_muster_rejected():
    with pytest.raises(ValueError):
        WeaponSystemRow(muster="   ", page_slug="p", suv_url="u")
