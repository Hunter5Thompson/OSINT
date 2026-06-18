import pytest

from suv_structured.system_types import SYSTEM_TYPES, classify_system_type


@pytest.mark.parametrize("type_raw, muster, expected", [
    # ground-infra precedence (rule 1, before satellite)
    ("satellitengestützte Kommunikationssystem", "SATCOMBw Bodensegment", "WEAPON_SYSTEM"),
    # satellite (rule 2)
    ("Kommunikations-satelliten", "COMSATBw", "SATELLITE"),
    # air (rule 3)
    ("Kampfflugzeug", "Eurofighter", "AIRCRAFT"),
    ("Tankflugzeug", "A330 MRTT", "AIRCRAFT"),          # 'tank' must NOT route to VESSEL
    ("Mittlerer Transporthubschrauber", "CH-53G", "AIRCRAFT"),
    ("Aufklärungsdrohne", "LUNA", "AIRCRAFT"),
    ("Seefernaufklärer", "P-8A Poseidon", "AIRCRAFT"),  # 'see' must NOT route to VESSEL
    ("Regierungsflieger", "A350", "AIRCRAFT"),
    # sea (rule 4)
    ("U-Jagd-Fregatte", "F123", "VESSEL"),
    ("Korvette", "K130", "VESSEL"),
    ("U-Boot", "U212A", "VESSEL"),
    ("Minenjagdboot", "MJ332C", "VESSEL"),
    ("Flottentanker", "A704", "VESSEL"),                # sea 'tanker'
    ("Large Unmanned Underwater Vehicle", "BlueWhale", "VESSEL"),
    # else (rule 5)
    ("Kampfpanzer", "Leopard 2", "WEAPON_SYSTEM"),
    ("Panzerhaubitze", "PzH 2000", "WEAPON_SYSTEM"),
    ("Flugabwehrsystem großer Reichweite", "Arrow", "WEAPON_SYSTEM"),
    (None, "Whatever", "WEAPON_SYSTEM"),
])
def test_classify(type_raw, muster, expected):
    assert classify_system_type(type_raw, muster) == expected


def test_returns_only_known_types():
    assert classify_system_type("Kampfpanzer", "Leopard 2") in SYSTEM_TYPES
