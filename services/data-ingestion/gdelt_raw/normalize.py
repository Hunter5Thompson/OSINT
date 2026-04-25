"""Entity name normalization for MERGE keys.

Rule: lowercase + collapse whitespace + replace non-alphanumeric with space.
NEVER drops tokens — that would be entity resolution, not normalization.
"""

from __future__ import annotations

import re
import unicodedata

_NON_ALNUM_RE = re.compile(r"[^\w\s]+", flags=re.UNICODE)
_WS_RE = re.compile(r"\s+", flags=re.UNICODE)


def normalize_entity_name(raw: str) -> str:
    if not raw:
        return ""
    s = unicodedata.normalize("NFKC", raw).lower()
    s = _NON_ALNUM_RE.sub(" ", s)
    s = _WS_RE.sub(" ", s).strip()
    return s
