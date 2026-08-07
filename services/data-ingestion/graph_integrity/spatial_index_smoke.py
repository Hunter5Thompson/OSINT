"""Read-only EXPLAIN probes for the canonical Location composite indexes."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Protocol


class ExplainClient(Protocol):
    async def explain(
        self,
        cypher: str,
        params: dict[str, Any],
    ) -> dict[str, Any]: ...


@dataclass(frozen=True, slots=True)
class SpatialIndexSmoke:
    scope_kind: str
    scope_property: str
    index_name: str
    sample_scope_key: str
    sample_revision: str

    @property
    def query(self) -> str:
        return (
            "EXPLAIN MATCH (l:Location) "
            f"WHERE l.{self.scope_property} = $scope_key "
            "AND l.spatial_derivation_revision = $revision "
            "RETURN l LIMIT 1"
        )


_SAMPLE_REVISION = "spatial-derive-v1-plan-smoke"
SPATIAL_INDEX_SMOKES = (
    SpatialIndexSmoke(
        scope_kind="country",
        scope_property="country_scope_key",
        index_name="location_country_scope_derivation",
        sample_scope_key="country:UKR",
        sample_revision=_SAMPLE_REVISION,
    ),
    SpatialIndexSmoke(
        scope_kind="admin1",
        scope_property="admin1_scope_key",
        index_name="location_admin1_scope_derivation",
        sample_scope_key="admin1:iso3166-2:UA-30",
        sample_revision=_SAMPLE_REVISION,
    ),
    SpatialIndexSmoke(
        scope_kind="admin2",
        scope_property="admin2_scope_key",
        index_name="location_admin2_scope_derivation",
        sample_scope_key="admin2:gbopen:UKR.1.1",
        sample_revision=_SAMPLE_REVISION,
    ),
)


async def collect_spatial_index_plan_evidence(
    client: ExplainClient,
) -> dict[str, Any]:
    """Collect JSON-safe EXPLAIN evidence without executing a graph read or write."""

    plans: list[dict[str, Any]] = []
    for smoke in SPATIAL_INDEX_SMOKES:
        plan = await client.explain(
            smoke.query,
            {
                "scope_key": smoke.sample_scope_key,
                "revision": smoke.sample_revision,
            },
        )
        encoded_plan = json.dumps(plan, sort_keys=True, default=str)
        encoded_plan_lower = encoded_plan.lower()
        expected_index_used = smoke.index_name in encoded_plan or (
            "indexseek" in encoded_plan_lower
            and smoke.scope_property in encoded_plan
            and "spatial_derivation_revision" in encoded_plan
        )
        plans.append(
            {
                "scope_kind": smoke.scope_kind,
                "scope_property": smoke.scope_property,
                "expected_index": smoke.index_name,
                "expected_index_used": expected_index_used,
                "plan": plan,
            }
        )
    return {
        "schema_version": 1,
        "all_expected_indexes_used": all(
            plan["expected_index_used"] for plan in plans
        ),
        "plans": plans,
    }
