"""Entity name/type canonicalization for the Neo4j write-path.

Pure, deterministic, no I/O. Sits BEFORE the Neo4j write in both ingest paths
(``pipeline.py`` and ``nlm_ingest/ingest_neo4j.py``). Mirrors the curated
entity-resolution policy applied to the live graph: only national-qualified
aliases collapse to a canonical ``(name, type)``; generic names pass through
unchanged ("Name != Identity").

Scope is deliberately tight:
  * trim / case / punctuation normalization for *matching*
  * a curated alias map (national-qualified military service names)
  * ORG <-> MILITARY_UNIT type-conflict resolution for *known* aliases
  * the original name is preserved as provenance (``raw_name`` + ``aliases``)

Out of scope (by design): fuzzy/semantic/LLM matching. Unknown names are
returned trimmed-but-otherwise-unchanged, with the emitted type untouched.

The alias map is the single source of truth that keeps the ingest write-path
consistent with the one-off Neo4j merges — without it the pipeline would
regenerate the same duplicates on the next run.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class CanonicalEntity:
    """Result of canonicalizing one extracted entity.

    ``name``/``type`` are what should be written to Neo4j; ``raw_name``/
    ``raw_type`` are the extractor's original emission (provenance); ``aliases``
    holds the curated spellings plus the raw name (empty for unmapped names).
    """

    name: str
    type: str
    raw_name: str
    raw_type: str
    aliases: tuple[str, ...]


# canonical name -> (canonical type, extra alias spellings that do NOT
# normalize onto the canonical, e.g. acronyms and "United States ..." forms).
# Case- and "US"/"U.S."-variants are handled by _normalize(), so they need not
# be listed here. Generic names (Navy, Army, Air Force, ...) are intentionally
# absent so they pass through unchanged.
_ALIAS_GROUPS: dict[str, tuple[str, tuple[str, ...]]] = {
    "U.S. Navy": ("MILITARY_UNIT", ("United States Navy",)),
    "U.S. Air Force": ("MILITARY_UNIT", ("United States Air Force", "USAF")),
    "U.S. Army": ("MILITARY_UNIT", ("United States Army",)),
    "U.S. Marine Corps": ("MILITARY_UNIT", ("United States Marine Corps", "USMC")),
    "IRGC": ("MILITARY_UNIT", ()),
    "Islamic Revolutionary Guard Corps": ("MILITARY_UNIT", ()),
    "Bundeswehr": ("MILITARY_UNIT", ()),
    "Deutsche Marine": ("MILITARY_UNIT", ()),
    "Nigerian Army": ("MILITARY_UNIT", ()),
    "French Navy": ("MILITARY_UNIT", ()),
    "Royal Navy": ("MILITARY_UNIT", ()),
    "Royal Air Force": ("MILITARY_UNIT", ()),
    "Ukrainian Air Force": ("MILITARY_UNIT", ()),
    "People's Liberation Army": ("MILITARY_UNIT", ()),
    "Iran’s Navy": ("MILITARY_UNIT", ()),
    "Sri Lankan Navy": ("MILITARY_UNIT", ()),
    "Swedish Coast Guard": ("ORGANIZATION", ()),
    "Chinese Coast Guard": ("ORGANIZATION", ()),
    "District of Columbia National Guard": (
        "MILITARY_UNIT",
        ("DC National Guard", "D.C. National Guard"),
    ),
    "Alaska Army National Guard": ("MILITARY_UNIT", ()),
}


def _normalize(name: str) -> str:
    """Lowercase, drop punctuation, and fold single-letter runs.

    ``"U.S. Navy"`` and ``"US Navy"`` both fold to ``"us navy"`` so the alias
    map needs only one entry per real entity.
    """
    s = name.lower()
    s = re.sub(r"[._,'’\"\-/]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    # collapse runs of single letters: "u s navy" -> "us navy"
    return re.sub(
        r"\b(?:[a-z] )+[a-z]\b", lambda m: m.group(0).replace(" ", ""), s
    )


# normalized alias -> canonical name (built once at import).
_LOOKUP: dict[str, str] = {}
for _canon, (_ctype, _extra) in _ALIAS_GROUPS.items():
    for _spelling in (_canon, *_extra):
        _LOOKUP[_normalize(_spelling)] = _canon


def canonicalize_entity(name: str, entity_type: str) -> CanonicalEntity:
    """Resolve ``(name, entity_type)`` to its canonical form via the alias map.

    Unmapped names are returned trimmed with the type unchanged. Mapped names
    return the canonical name + canonical type, with the original spelling
    retained in ``aliases`` for provenance.
    """
    canon = _LOOKUP.get(_normalize(name))
    if canon is None:
        return CanonicalEntity(
            name=name.strip(),
            type=entity_type,
            raw_name=name,
            raw_type=entity_type,
            aliases=(),
        )
    ctype, extra = _ALIAS_GROUPS[canon]
    aliases = tuple(sorted({canon, *extra, name.strip()}))
    return CanonicalEntity(
        name=canon,
        type=ctype,
        raw_name=name,
        raw_type=entity_type,
        aliases=aliases,
    )
