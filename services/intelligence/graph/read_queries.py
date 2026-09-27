"""Lightweight prefilter for Cypher writes and multi-statement queries.

Neo4j READ_ACCESS is a routing preference, not an authorization boundary.
Callers must not treat this keyword scan as a complete Cypher security check.
"""

import re


def validate_cypher_readonly(cypher: str) -> bool:
    """Reject obvious write/admin operations in a Cypher string.

    This is a lightweight application prefilter, not a complete security boundary.
    Neo4j READ_ACCESS selects a read route; database permissions must enforce access.

    Returns True when this limited scan finds no known write keyword or semicolon;
    that result does not prove the query is safe or read-only.
    """
    # Block multi-statement injection via semicolons
    if ";" in cypher:
        return False

    # Strip string literals to avoid false positives on keywords inside quotes
    stripped = _strip_string_literals(cypher)

    # Block all known write/admin keywords
    write_keywords = (
        r"\b("
        r"CREATE|MERGE|DELETE|DETACH|SET|REMOVE|DROP"
        r"|CALL|LOAD\s+CSV|FOREACH"
        r")\b"
    )
    return not re.search(write_keywords, stripped, re.IGNORECASE)


def _strip_string_literals(cypher: str) -> str:
    """Replace string literals with empty strings to prevent false positives.

    Handles both single-quoted and double-quoted strings.
    """
    return re.sub(r"'[^']*'|\"[^\"]*\"", "''", cypher)
