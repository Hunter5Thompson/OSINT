"""Constants + curated Factbook→Almanac field mapping (single source of truth)."""
from __future__ import annotations

FACTBOOK_REVISION = "8662a8b17a784841ab4528631b04090eb2f183eb"
FACTBOOK_REVISION_DATE = "2026-05-17"
CIA_SUNSET_DATE = "2026-02-04"
FACTBOOK_TARBALL_URL = (
    f"https://codeload.github.com/factbook/factbook.json/tar.gz/{FACTBOOK_REVISION}"
)
RESTCOUNTRIES_URL = (
    "https://restcountries.com/v3.1/all"
    "?fields=cca3,ccn3,name,capital,capitalInfo,region,subregion,"
    "population,area,currencies,languages,latlng"
)
MAX_CAPITAL_CENTROID_DISTANCE_KM = 5000.0

# REST-fallback (no usable single Factbook profile) — keep economy/security optional.
REST_FALLBACK_ISO3 = {"ESH", "PSE"}
# Partial Factbook (deliberately empty economy) — security ok, economy optional.
PARTIAL_FACTBOOK_ISO3 = {"ATA"}
# Map stubs (no ISO/Factbook data) — resolvable-only.
MAP_STUB_TOPO_IDS = {"N. Cyprus", "Somaliland"}

# label -> Factbook section + key path (list = nested lookup). One entry per fact.
# Section "profile"/"people"/"government"/"economy"/"security".
FIELD_MAP: list[dict] = [
    {"section": "profile", "label": "Area", "fb": ["Geography", "Area", "total "]},
    {"section": "profile", "label": "Climate", "fb": ["Geography", "Climate"]},
    {
        "section": "profile",
        "label": "Natural resources",
        "fb": ["Geography", "Natural resources"],
    },
    {
        "section": "people",
        "label": "Population",
        "fb": ["People and Society", "Population", "total"],
    },
    {
        "section": "people",
        "label": "Median age",
        "fb": ["People and Society", "Median age", "total"],
    },
    {
        "section": "people",
        "label": "Population growth rate",
        "fb": ["People and Society", "Population growth rate"],
    },
    {
        "section": "people",
        "label": "Urbanization",
        "fb": ["People and Society", "Urbanization", "urban population"],
    },
    {
        "section": "people",
        "label": "Life expectancy",
        "fb": ["People and Society", "Life expectancy at birth", "total population"],
    },
    {
        "section": "people",
        "label": "Ethnic groups",
        "fb": ["People and Society", "Ethnic groups"],
    },
    {
        "section": "people",
        "label": "Religions",
        "fb": ["People and Society", "Religions"],
    },
    {
        "section": "people",
        "label": "Languages",
        "fb": ["People and Society", "Languages", "Languages"],
    },
    {
        "section": "people",
        "label": "Literacy",
        "fb": ["People and Society", "Literacy", "total population"],
    },
    {
        "section": "government",
        "label": "Government type",
        "fb": ["Government", "Government type"],
    },
    {
        "section": "government",
        "label": "Independence",
        "fb": ["Government", "Independence"],
    },
    {
        "section": "government",
        "label": "Chief of state",
        "fb": ["Government", "Executive branch", "chief of state"],
    },
    {
        "section": "government",
        "label": "Head of government",
        "fb": ["Government", "Executive branch", "head of government"],
    },
    {"section": "government", "label": "Suffrage", "fb": ["Government", "Suffrage"]},
    {
        "section": "economy",
        "label": "Real GDP (PPP)",
        "fb": ["Economy", "Real GDP (purchasing power parity)"],
        "multiyear": True,
    },
    {
        "section": "economy",
        "label": "Real GDP per capita",
        "fb": ["Economy", "Real GDP per capita"],
        "multiyear": True,
    },
    {
        "section": "economy",
        "label": "Real GDP growth rate",
        "fb": ["Economy", "Real GDP growth rate"],
        "multiyear": True,
    },
    {
        "section": "economy",
        "label": "Inflation",
        "fb": ["Economy", "Inflation rate (consumer prices)"],
        "multiyear": True,
    },
    {
        "section": "economy",
        "label": "GDP by sector",
        "fb": ["Economy", "GDP - composition, by sector of origin"],
        "composite": ["agriculture", "industry", "services"],
    },
    {"section": "economy", "label": "Industries", "fb": ["Economy", "Industries"]},
    {"section": "economy", "label": "Labor force", "fb": ["Economy", "Labor force"]},
    {
        "section": "economy",
        "label": "Unemployment rate",
        "fb": ["Economy", "Unemployment rate"],
        "multiyear": True,
    },
    {
        "section": "economy",
        "label": "Youth unemployment",
        "fb": ["Economy", "Youth unemployment rate (ages 15-24)", "total"],
    },
    {
        "section": "economy",
        "label": "Public debt",
        "fb": ["Economy", "Public debt"],
        "multiyear": True,
    },
    {
        "section": "economy",
        "label": "Exports",
        "fb": ["Economy", "Exports"],
        "multiyear": True,
    },
    {
        "section": "economy",
        "label": "Exports - partners",
        "fb": ["Economy", "Exports - partners"],
    },
    {
        "section": "economy",
        "label": "Imports - partners",
        "fb": ["Economy", "Imports - partners"],
    },
    {
        "section": "economy",
        "label": "Exchange rates",
        "fb": ["Economy", "Exchange rates"],
    },
    {
        "section": "security",
        "label": "Military expenditures",
        "fb": ["Military and Security", "Military expenditures"],
        "multiyear": True,
    },
    {
        "section": "security",
        "label": "Military and security forces",
        "fb": ["Military and Security", "Military and security forces"],
    },
    {
        "section": "security",
        "label": "Personnel strengths",
        "fb": [
            "Military and Security",
            "Military and security service personnel strengths",
        ],
    },
    {
        "section": "security",
        "label": "Service age/obligation",
        "fb": ["Military and Security", "Military service age and obligation"],
    },
    {
        "section": "security",
        "label": "Military deployments",
        "fb": ["Military and Security", "Military deployments"],
    },
    {
        "section": "security",
        "label": "Military note",
        "fb": ["Military and Security", "Military - note"],
    },
]
