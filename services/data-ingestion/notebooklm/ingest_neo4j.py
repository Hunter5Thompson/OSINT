from __future__ import annotations

import base64

import httpx
import structlog

from notebooklm.schemas import Extraction, claim_hash
from notebooklm.write_templates import (
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


def _build_statements(extraction: Extraction, source_name: str) -> list[dict]:
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
            "type": "notebooklm_podcast",
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

    # 4. Upsert Entities
    for entity in extraction.entities:
        statements.append({
            "statement": UPSERT_ENTITY,
            "parameters": {
                "name": entity.name,
                "type": entity.type,
                "aliases": entity.aliases,
                "confidence": entity.confidence,
            },
        })

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
            },
        })

        # 7. Link Claim → Entities
        for entity_name in claim.entities_involved:
            statements.append({
                "statement": LINK_CLAIM_ENTITY,
                "parameters": {
                    "statement_hash": stmt_hash,
                    "entity_name": entity_name,
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
) -> None:
    """Write extraction results to Neo4j via HTTP transactional API. Raises on error."""
    statements = _build_statements(extraction, source_name)

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
