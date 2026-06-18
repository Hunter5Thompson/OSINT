"""Deterministic classifier: SUV Hauptwaffensysteme Typ/muster -> EntityType.

Ordered first-match rules (see the design spec §2). Ground-infrastructure is
checked BEFORE the satellite rule so 'SATCOMBw Bodensegment' (a ground segment,
not the satellite) types as WEAPON_SYSTEM; air is checked before sea so
'Tankflugzeug'/'Seefernaufklärer' don't fall to the 'tanker'/sea rules."""
from __future__ import annotations

SYSTEM_TYPES: tuple[str, ...] = ("WEAPON_SYSTEM", "AIRCRAFT", "VESSEL", "SATELLITE")

_GROUND_INFRA = ("bodensegment", "ground segment", "terminal", "station")
_SATELLITE = ("satellit", "satellite")
_AIR = ("flugzeug", "hubschrauber", "drohne", "flieger", "seefernaufklärer")
_SEA = ("fregatte", "korvette", "u-boot", "boot", "tender", "tanker", "underwater")


def classify_system_type(type_raw: str | None, muster: str = "") -> str:
    """Return the EntityType for a SUV equipment row. Pure; no LLM."""
    combined = f"{muster} {type_raw or ''}".lower()
    if any(k in combined for k in _GROUND_INFRA):
        return "WEAPON_SYSTEM"
    if any(k in combined for k in _SATELLITE):
        return "SATELLITE"
    t = (type_raw or "").lower()
    if any(k in t for k in _AIR):
        return "AIRCRAFT"
    if any(k in t for k in _SEA):
        return "VESSEL"
    return "WEAPON_SYSTEM"
