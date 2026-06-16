from suv_structured.parse import (
    derive_hq,
    parse_companies,
    parse_employees,
    parse_founded,
    parse_products,
    parse_revenue_eur,
)

_FIXTURE = """# Directory preamble
### Aaronia AG
**Gründung:** 2003
**Hauptsitz:** Aaronia Weg 1, 54597 Strickscheid, Rheinland-Pfalz
**Geschäftsführung:** Rüdiger Chmielus (Vorsitz), Stefan Chmielus
**Mitarbeiterzahl:** >75
**Umsatz:** 35,3 Millionen Euro (2023), 50+ Millionen Euro (2024)
**Beschreibung:** Mess-, Ortungs- und Überwachungstechnik.
**Produktportfolio:** Spektrumanalysatoren, Antennen, PCs
### KNDS N.V.
**Gründung:** 2015 durch die Fusion von KMW und Nexter
**Hauptsitz:** Gustav Mahlerlaan 1017, 1082 MK Amsterdam, Niederlande / Deutscher Sitz: München
**Geschäftsführung:** Jean-Paul Alary (CEO)
**Mitarbeiterzahl:** >11.000
**Umsatz:** 4,4 Milliarden Euro (2025)
**Produktportfolio:** Kampfpanzer (Leopard 2), Radfahrzeuge
###
"""


def test_parse_companies_splits_blocks_and_skips_empty_name():
    cs = parse_companies(_FIXTURE)
    assert [c.name for c in cs] == ["Aaronia AG", "KNDS N.V."]  # blank-name block dropped


def test_parse_companies_populates_fields():
    cs = parse_companies(_FIXTURE)
    a = cs[0]
    assert a.founded == 2003
    assert a.employees == 75
    assert a.revenue_eur == 35_300_000.0
    assert a.hq_country == "Deutschland"
    assert "Spektrumanalysatoren" in a.products
    assert a.description and "Mess" in a.description


def test_parse_employees():
    assert parse_employees(">75") == 75
    assert parse_employees("34000") == 34000
    assert parse_employees("32.000 Weltweit, davon 14.100 in Deutschland") == 32000
    assert parse_employees("") is None
    assert parse_employees("k.A.") is None


def test_parse_revenue_eur():
    assert parse_revenue_eur("4,4 Milliarden Euro (2025)") == 4_400_000_000.0
    assert parse_revenue_eur("35,3 Millionen Euro (2023), 50+ Millionen Euro (2024)") == 35_300_000.0  # noqa: E501
    assert parse_revenue_eur("k.A.") is None
    assert parse_revenue_eur("") is None


def test_parse_founded():
    assert parse_founded("2003") == 2003
    assert parse_founded("2015 durch die Fusion von KMW und Nexter") == 2015
    assert parse_founded("—") is None


def test_parse_products():
    assert parse_products("A, B; C") == ["A", "B", "C"]
    assert parse_products("") == []


def test_derive_hq():
    city, country = derive_hq("Aaronia Weg 1, 54597 Strickscheid, Rheinland-Pfalz")
    assert country == "Deutschland"
    city2, country2 = derive_hq("Hauptstr. 1, 13055 Berlin")
    assert country2 == "Deutschland" and city2 == "Berlin"
    city3, country3 = derive_hq("Gustav Mahlerlaan 1017, 1082 MK Amsterdam, Niederlande / Deutscher Sitz: München")  # noqa: E501
    assert country3 == "Niederlande"
    assert derive_hq(None) == (None, None)
