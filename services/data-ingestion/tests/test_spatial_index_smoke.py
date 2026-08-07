from unittest.mock import AsyncMock

import pytest

from graph_integrity.spatial_index_smoke import (
    SPATIAL_INDEX_SMOKES,
    collect_spatial_index_plan_evidence,
)


def test_explain_queries_cover_each_exact_composite_index_without_interpolation() -> None:
    assert {
        smoke.scope_kind: (smoke.scope_property, smoke.index_name)
        for smoke in SPATIAL_INDEX_SMOKES
    } == {
        "country": ("country_scope_key", "location_country_scope_derivation"),
        "admin1": ("admin1_scope_key", "location_admin1_scope_derivation"),
        "admin2": ("admin2_scope_key", "location_admin2_scope_derivation"),
    }
    for smoke in SPATIAL_INDEX_SMOKES:
        assert smoke.query.startswith("EXPLAIN ")
        assert f"l.{smoke.scope_property} = $scope_key" in smoke.query
        assert "l.spatial_derivation_revision = $revision" in smoke.query
        assert smoke.sample_scope_key not in smoke.query
        assert smoke.sample_revision not in smoke.query


@pytest.mark.asyncio
async def test_plan_evidence_reports_each_expected_index() -> None:
    client = AsyncMock()
    client.explain.side_effect = [
        {
            "operator_type": "NodeIndexSeek",
            "arguments": {"index": smoke.index_name},
            "children": [],
        }
        for smoke in SPATIAL_INDEX_SMOKES
    ]

    evidence = await collect_spatial_index_plan_evidence(client)

    assert evidence["schema_version"] == 1
    assert evidence["all_expected_indexes_used"] is True
    assert [row["scope_kind"] for row in evidence["plans"]] == [
        "country",
        "admin1",
        "admin2",
    ]
    assert all(row["expected_index_used"] for row in evidence["plans"])
    assert [call.args[1] for call in client.explain.await_args_list] == [
        {"scope_key": smoke.sample_scope_key, "revision": smoke.sample_revision}
        for smoke in SPATIAL_INDEX_SMOKES
    ]


@pytest.mark.asyncio
async def test_plan_evidence_fails_closed_when_expected_index_is_absent() -> None:
    client = AsyncMock()
    client.explain.return_value = {
        "operator_type": "NodeByLabelScan",
        "arguments": {},
        "children": [],
    }

    evidence = await collect_spatial_index_plan_evidence(client)

    assert evidence["all_expected_indexes_used"] is False
    assert not any(row["expected_index_used"] for row in evidence["plans"])


@pytest.mark.asyncio
async def test_plan_evidence_accepts_neo4j_schema_details_without_index_name() -> None:
    client = AsyncMock()
    client.explain.side_effect = [
        {
            "operator_type": "NodeIndexSeek",
            "arguments": {
                "Details": (
                    f"RANGE INDEX l:Location({smoke.scope_property}, "
                    "spatial_derivation_revision)"
                )
            },
            "children": [],
        }
        for smoke in SPATIAL_INDEX_SMOKES
    ]

    evidence = await collect_spatial_index_plan_evidence(client)

    assert evidence["all_expected_indexes_used"] is True
