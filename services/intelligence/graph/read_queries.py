"""
LLM generiert Cypher für Read-Queries.
Safety: Keyword-Blocklist + Semicolon-Check + Neo4j READ_ACCESS enforcement.
"""

import re


def validate_cypher_readonly(cypher: str) -> bool:
    """Reject write/admin operations in LLM-generated Cypher.

    Defense-in-depth layer 1 (application-level).
    Layer 2 is Neo4j session with default_access_mode=READ_ACCESS.

    Returns True only if the query looks safe to execute read-only.
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
    if re.search(write_keywords, stripped, re.IGNORECASE):
        return False

    return True


def _strip_string_literals(cypher: str) -> str:
    """Replace string literals with empty strings to prevent false positives.

    Handles both single-quoted and double-quoted strings.
    """
    return re.sub(r"'[^']*'|\"[^\"]*\"", "''", cypher)
