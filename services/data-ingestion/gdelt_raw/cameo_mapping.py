"""CAMEO EventRootCode → internal codebook_type mapping.

Why broader than the current allowlist: widening filter to root 14/17
later should be a pure config change, not a code change.
"""

from __future__ import annotations

CAMEO_ROOT_TO_CODEBOOK: dict[int, str] = {
    14: "civil.protest",            # not in default allowlist (analytics-only)
    15: "posture.military",         # Troop movements, mobilization   (active)
    17: "conflict.coercion",        # Sanctions, asset freezes         (future)
    18: "conflict.assault",         # Assaults, assassinations         (active)
    19: "conflict.armed",           # Firefights, artillery            (active)
    20: "conflict.mass_violence",   # Massacres, WMD, ethnic cleansing (active)
}


def map_cameo_root(root: int) -> str | None:
    """Return internal codebook_type for a CAMEO root code, or None."""
    return CAMEO_ROOT_TO_CODEBOOK.get(root)
