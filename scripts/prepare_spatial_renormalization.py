#!/usr/bin/env python3
"""Prepare a shared cutover plan and optional read-only full-store previews.

Run with the locked data-ingestion environment from a complete repository checkout.
This deliberately has no apply or catalog activation option.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [
    str(ROOT / "services/data-ingestion"),
    str(ROOT / "services/intelligence"),
]

from config import Settings  # noqa: E402
from graph_integrity.neo4j_client import Neo4jClient  # noqa: E402
from graph_integrity.reenrich_spatial_scope import (  # noqa: E402
    derivation_revision_map,
    plan_reenrichment_jobs,
    run_jobs,
)
from graph_integrity.spatial_batch import MemoryCheckpointStore  # noqa: E402
from graph_integrity.spatial_normalizer import load_normalization_index  # noqa: E402
from spatial_renormalization import build_cutover_plan  # noqa: E402
from spatial_reprojection import reproject_payload  # noqa: E402


async def prepare(args):
    previous = load_normalization_index(args.previous, crosswalk_path=args.crosswalk)
    target = load_normalization_index(args.target, crosswalk_path=args.crosswalk)
    result = build_cutover_plan(previous, target)
    if args.preview:
        from qdrant_client import AsyncQdrantClient, models

        from rag.spatial_reenrich import (
            QdrantReenrichmentStore,
            ReenrichmentJob,
            preview_spatial_reenrichment,
        )

        class Projector:
            def project(self, point, job):
                return reproject_payload(point.payload, target)

        settings = Settings()
        graph = Neo4jClient(
            settings.neo4j_url, settings.neo4j_user, settings.neo4j_password
        )
        vectors = AsyncQdrantClient(url=settings.qdrant_url)
        try:
            result["neo4j_preview"] = await run_jobs(
                graph,
                target,
                MemoryCheckpointStore(),
                plan_reenrichment_jobs(
                    derivation_revision_map(previous), derivation_revision_map(target)
                ),
                dry_run=True,
            )
            filters = {
                entry["lane"]: models.Filter(
                    must=[
                        models.FieldCondition(
                            key=entry["filter"]["key"],
                            match=models.MatchValue(value=entry["filter"]["value"]),
                        )
                    ]
                )
                for entry in result["qdrant_jobs"]
            }
            store = QdrantReenrichmentStore(
                vectors, settings.qdrant_collection, filters
            )
            result["qdrant_previews"] = [
                await preview_spatial_reenrichment(
                    store,
                    Projector(),
                    ReenrichmentJob(
                        entry["lane"],
                        entry["target_projection_revision"],
                    ),
                )
                for entry in result["qdrant_jobs"]
            ]
        finally:
            await graph.close()
            await vectors.close()
    # Exclusive creation protects an already reviewed operator artifact.
    with args.output.open("x", encoding="utf-8") as output:
        json.dump(result, output, ensure_ascii=False, sort_keys=True, indent=2)
        output.write("\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--previous", type=Path, required=True)
    parser.add_argument("--target", type=Path, required=True)
    parser.add_argument(
        "--crosswalk",
        type=Path,
        default=ROOT
        / "services/data-ingestion/spatial_catalog/data/country_crosswalk.json",
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--preview", action="store_true", help="read both stores; never write"
    )
    asyncio.run(prepare(parser.parse_args()))


if __name__ == "__main__":
    main()
