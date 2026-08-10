"""Shared spatial payload-index contract tests for intelligence."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from qdrant_client.models import PayloadIndexInfo, PayloadSchemaType

CONTRACT_PATH = (
    Path(__file__).resolve().parents[3] / "contracts" / "qdrant-spatial-payload-v1.json"
)


def _contract_indexes() -> dict[str, str]:
    payload = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    return {item["field"]: item["schema"] for item in payload["payload_indexes"]}


def _index(schema: str) -> PayloadIndexInfo:
    return PayloadIndexInfo(data_type=PayloadSchemaType(schema), points=1)


def test_local_index_contract_matches_shared_vector_exactly() -> None:
    from rag.qdrant_schema import PAYLOAD_INDEXES

    expected = _contract_indexes()

    assert expected == PAYLOAD_INDEXES
    assert len(PAYLOAD_INDEXES) == 17
    assert sum(field.startswith("spatial_") or field == "geo" for field in expected) == 8
    contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    assert {"spatial_conflict", "spatial_conflict_scope_keys"} <= set(
        contract["unindexed_audit_fields"]
    )
    assert not set(contract["unindexed_audit_fields"]) & set(PAYLOAD_INDEXES)


def test_payload_validator_reports_missing_indexes_without_writing() -> None:
    from rag.qdrant_schema import PAYLOAD_INDEXES, validate_payload_index_schema

    info = SimpleNamespace(payload_schema={"source": _index("keyword")})

    assert set(validate_payload_index_schema(info)) == set(PAYLOAD_INDEXES) - {"source"}


def test_payload_validator_rejects_existing_wrong_type() -> None:
    from rag.qdrant_schema import QdrantSchemaMismatch, validate_payload_index_schema

    info = SimpleNamespace(
        payload_schema={
            "source": _index("keyword"),
            "geo": _index("keyword"),
        }
    )

    with pytest.raises(QdrantSchemaMismatch, match="geo.*keyword.*geo"):
        validate_payload_index_schema(info)


async def test_authorized_migration_rejects_wrong_type_before_any_write() -> None:
    from rag.qdrant_schema import QdrantSchemaMismatch
    from scripts.ensure_payload_indexes import ensure_indexes

    client = SimpleNamespace(
        get_collection=AsyncMock(
            return_value=SimpleNamespace(
                payload_schema={"geo": _index("keyword")}
            )
        ),
        create_payload_index=AsyncMock(),
    )

    with pytest.raises(QdrantSchemaMismatch, match="geo"):
        await ensure_indexes(client=client, collection="odin_intel")

    client.create_payload_index.assert_not_awaited()
