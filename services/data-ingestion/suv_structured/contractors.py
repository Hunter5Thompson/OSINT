"""Split a SUV Auftragnehmer string into individual contractor parties.

Consortia appear as 'A & B', 'A, B', or 'Konsortium … (A & B)'. Empty markers
('/', 'N/A') yield no parties. NOTE: a genuine single company with '&' in its name
(e.g. 'Rohde & Schwarz' as a standalone value) would be over-split; in the observed
data such names only appear inside comma-lists, so we split on '&' too — the match
gate (no auto-create) is the backstop for any over-split party that doesn't match."""
from __future__ import annotations

import re

_EMPTY = {"/", "n/a", "na", "", "-"}


def split_contractors(raw: str | None) -> list[str]:
    if not raw:
        return []
    s = raw.strip()
    if s.lower() in _EMPTY:
        return []
    # extract the inside of a 'Konsortium NAME (A & B)' paren group if present
    m = re.search(r"\(([^)]+)\)", s)
    if m and ("&" in m.group(1) or "," in m.group(1)):
        s = m.group(1)
    # Split strategy: comma/semicolon takes precedence; fall back to '&' only.
    # Never split on bare 'und' — it appears in company names and inside '&'-joined pairs.
    parts = re.split(r"\s*[,;]\s*", s) if re.search(r"[,;]", s) else re.split(r"\s*&\s*", s)
    out: list[str] = []
    for p in parts:
        p = p.strip(" .")
        if not p or p.lower() in _EMPTY or p.lower() == "etc":
            continue
        out.append(p)
    return out
