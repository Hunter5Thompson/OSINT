from __future__ import annotations

import base64

import httpx
import structlog

from canonicalize import canonicalize_entity
from nlm_ingest.schemas import Extraction, claim_hash
from nlm_ingest.write_templates import (
    CANONICAL_RELATION_TEMPLATES,
    LINK_CLAIM_DOCUMENT,
    LINK_CLAIM_ENTITY,
    LINK_DOCUMENT_SOURCE,
    UPSERT_CLAIM,
    UPSERT_DOCUMENT,
    UPSERT_ENTITY,
    UPSERT_SOURCE_WITH_TIER,
    get_source_tier,
)

log = structlog.get_logger()


def _canonical_name(name: str) -> str:
    """Canonical entity name only (type-independent), for name-based MATCHes."""
    return canonicalize_entity(name, "").name


def _build_relation_statements(canonical) -> list[dict]:
    """Statement+params per pre-validated CanonicalRelation (support-set MERGE).

    Endpoints (c.source/c.target) are already _canonical_name-normalized and
    symmetric-sorted by the validator — passed through as-is. candidate_only
    types never reach here; the None guard is purely defensive.
    """
    out: list[dict] = []
    for c in canonical:
        template = CANONICAL_RELATION_TEMPLATES.get(c.rel_type)
        if template is None:  # defensive: candidate_only types never reach here
            continue
        out.append({
            "statement": template,
            "parameters": {
                "source": c.source,
                "source_type": c.source_type,
                "target": c.target,
                "target_type": c.target_type,
                "confidence": c.confidence,
                "evidence": c.evidence,
                "prov_key": c.provenance_key,
                "notebook_id": c.notebook_id,
            },
        })
    return out


def _build_statements(
    extraction: Extraction, source_name: str, canonical_relations
) -> list[dict]:
    statements: list[dict] = []

    # 1. Upsert Source with quality tier
    statements.append({
        "statement": UPSERT_SOURCE_WITH_TIER,
        "parameters": {
            "source_name": source_name,
            "quality_tier": get_source_tier(source_name),
        },
    })

    # 2. Upsert Document
    statements.append({
        "statement": UPSERT_DOCUMENT,
        "parameters": {
            "notebook_id": extraction.notebook_id,
            "title": f"NLM: {source_name}",
            "source": source_name,
            "type": "notebooklm",
        },
    })

    # 3. Link Document → Source
    statements.append({
        "statement": LINK_DOCUMENT_SOURCE,
        "parameters": {
            "notebook_id": extraction.notebook_id,
            "source_name": source_name,
        },
    })

    # 4. Upsert Entities (canonicalize known aliases before the write; the
    #    same map drives relations/claim links below so endpoints stay matched)
    for entity in extraction.entities:
        canon = canonicalize_entity(entity.name, entity.type)
        aliases = (
            sorted({*entity.aliases, *canon.aliases})
            if canon.aliases
            else entity.aliases
        )
        statements.append({
            "statement": UPSERT_ENTITY,
            "parameters": {
                "name": canon.name,
                "type": canon.type,
                "aliases": aliases,
                "confidence": entity.confidence,
            },
        })

    # 4b. Upsert pre-validated canonical relations between entities (canonical
    #     support-set templates only). Endpoints are MATCH-ed (name+type), so
    #     the entity upsert step 4 above must precede this block.
    statements += _build_relation_statements(canonical_relations)

    # 5. Upsert Claims with provenance (skip rejected)
    for claim in extraction.claims:
        if claim.confidence <= 0.0:
            continue
        stmt_hash = claim_hash(claim.statement)
        statements.append({
            "statement": UPSERT_CLAIM,
            "parameters": {
                "statement_hash": stmt_hash,
                "statement": claim.statement,
                "type": claim.type,
                "polarity": claim.polarity,
                "confidence": claim.confidence,
                "temporal_scope": claim.temporal_scope,
                "model": extraction.extraction_model,
                "prompt_version": extraction.prompt_version,
            },
        })

        # 6. Link Claim → Document
        statements.append({
            "statement": LINK_CLAIM_DOCUMENT,
            "parameters": {
                "statement_hash": stmt_hash,
                "notebook_id": extraction.notebook_id,
                "source_kind": extraction.source_kind,
                "source_id": extraction.source_id,
            },
        })

        # 7. Link Claim → Entities
        for entity_name in claim.entities_involved:
            statements.append({
                "statement": LINK_CLAIM_ENTITY,
                "parameters": {
                    "statement_hash": stmt_hash,
                    "entity_name": _canonical_name(entity_name),
                },
            })

    return statements


async def ingest_extraction(
    extraction: Extraction,
    source_name: str,
    client: httpx.AsyncClient,
    neo4j_url: str,
    neo4j_user: str,
    neo4j_password: str,
    canonical_relations=(),
) -> None:
    """Write extraction results to Neo4j via HTTP transactional API. Raises on error.

    ``canonical_relations`` is the pre-validated set (Relation v2); the empty
    default writes the backbone with no relations — the correct interim for any
    caller not yet migrated (the CLI is migrated in Task 9).
    """
    statements = _build_statements(extraction, source_name, canonical_relations)

    auth_str = base64.b64encode(f"{neo4j_user}:{neo4j_password}".encode()).decode()
    headers = {
        "Authorization": f"Basic {auth_str}",
        "Content-Type": "application/json",
    }

    payload = {"statements": statements}

    response = await client.post(
        f"{neo4j_url}/db/neo4j/tx/commit",
        json=payload,
        headers=headers,
        timeout=30.0,
    )
    response.raise_for_status()
    data = response.json()
    errors = data.get("errors", [])
    if errors:
        log.warning("neo4j_errors", errors=errors, notebook_id=extraction.notebook_id)
        raise RuntimeError(f"Neo4j returned {len(errors)} error(s): {errors[0].get('message', '')}")
    log.info(
        "neo4j_ingest_ok",
        notebook_id=extraction.notebook_id,
        statements=len(statements),
    )
