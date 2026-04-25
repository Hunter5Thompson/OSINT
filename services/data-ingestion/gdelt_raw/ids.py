"""Deterministic ID generation for GDELT entities.

Stable contracts — changing these requires a data migration.
"""

from __future__ import annotations

import re
from uuid import NAMESPACE_URL, uuid5

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slug(s: str) -> str:
    return _SLUG_RE.sub("-", s.lower()).strip("-")


def build_event_id(global_event_id: int | str) -> str:
    """gdelt:event:<GlobalEventID>"""
    return f"gdelt:event:{global_event_id}"


def build_doc_id(gkg_record_id: str) -> str:
    """gdelt:gkg:<GKGRecordID>"""
    return f"gdelt:gkg:{gkg_record_id}"


def build_location_id(
    feature_id: str = "",
    country_code: str = "",
    name: str = "",
) -> str:
    """gdelt:loc:<feature_id>  OR  gdelt:loc:<cc>:<slugged_name> as fallback."""
    if feature_id:
        return f"gdelt:loc:{feature_id}"
    return f"gdelt:loc:{country_code.lower()}:{_slug(name)}"


def qdrant_point_id_for_doc(doc_id: str) -> str:
    """Deterministic UUIDv5 from canonical doc_id → Qdrant point-ID (str form)."""
    return str(uuid5(NAMESPACE_URL, doc_id))
