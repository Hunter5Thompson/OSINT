import pytest
from pydantic import ValidationError

from suv_structured.schemas import Company, profile_text


def test_company_minimal_requires_name_and_url():
    c = Company(name="Rheinmetall AG", suv_url="https://suv.report/rheinmetall/")
    assert c.name == "Rheinmetall AG"
    assert c.products == [] and c.aliases == []


def test_company_rejects_missing_name():
    with pytest.raises(ValidationError):
        Company(suv_url="https://suv.report/x/")


def test_company_rejects_blank_name():
    with pytest.raises(ValidationError):
        Company(name="   ", suv_url="u")


def test_company_coerces_numeric_strings():
    c = Company(name="X", suv_url="u", employees="34000", revenue_eur="9900000000", founded="1889")
    assert c.employees == 34000
    assert c.revenue_eur == 9_900_000_000.0
    assert c.founded == 1889


def test_profile_text_includes_key_fields():
    c = Company(name="Hensoldt", suv_url="u", hq_country="Deutschland",
                hq_city="Taufkirchen", employees=6500, products=["TRML-4D", "Spexer"])
    t = profile_text(c)
    assert "Hensoldt" in t and "Deutschland" in t and "TRML-4D" in t and "6500" in t
