"""Pure cross-store cutover planning; no database or activation capabilities."""

from __future__ import annotations

from graph_integrity.reenrich_spatial_scope import derivation_revision_map, plan_reenrichment_jobs
from graph_integrity.spatial_normalizer import SpatialNormalizationIndex
from qdrant_spatial import derive_spatial_projection_revision
from source_spatial import SOURCE_ID_FIELDS


def build_cutover_plan(
    previous: SpatialNormalizationIndex,
    target: SpatialNormalizationIndex,
) -> dict[str, object]:
    projection_revision = derive_spatial_projection_revision(target)
    lanes = [(source, "source", source) for source in sorted(SOURCE_ID_FIELDS)] + [
        ("gdelt_gkg", "source", "gdelt_gkg"),
        ("notebooklm", "source_type", "notebooklm"),
    ]
    return {
        "schema_version": 1,
        "previous_catalog_revision": previous.catalog_revision,
        "target_catalog_revision": target.catalog_revision,
        "scope_count": len(target.scopes),
        "compatible_previous_scopes": sum(
            target.is_compatible_derivation(key, scope.derivation_revision)
            for key, scope in previous.scopes.items()
            if key in target.scopes
        ),
        "neo4j_jobs": [
            job.to_dict()
            for job in plan_reenrichment_jobs(
                derivation_revision_map(previous),
                derivation_revision_map(target),
            )
        ],
        "qdrant_jobs": [
            {
                "lane": lane,
                "target_projection_revision": projection_revision,
                "filter": {"key": key, "value": value},
            }
            for lane, key, value in lanes
        ],
        "requirements": [
            "pause affected writers for snapshot, preview and apply",
            "durable Neo4j backup and Qdrant snapshot including vectors",
            "review complete source-bound dry-runs; reject input fingerprint drift",
            "reproject raw evidence; withdraw tokens when source evidence is absent",
            "deploy readers and writers with the same target catalog",
            "publish measured coverage only after verification",
        ],
        "live_writes": False,
    }
