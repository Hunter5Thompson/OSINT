from pathlib import Path

from graph_integrity.spatial_normalizer import load_normalization_index
from spatial_renormalization import build_cutover_plan


def test_cutover_plan_binds_both_stores_to_one_target_and_unique_scans():
    root = Path(__file__).resolve().parents[2] / "backend/data/spatial"
    crosswalk = Path("spatial_catalog/data/country_crosswalk.json")
    previous = load_normalization_index(
        root / "catalogs/spatial-v1-0180e188358c", crosswalk_path=crosswalk
    )
    target = load_normalization_index(
        root / "catalogs/spatial-v1-2ff6da288a58", crosswalk_path=crosswalk
    )
    plan = build_cutover_plan(previous, target)
    assert plan["target_catalog_revision"] == target.catalog_revision
    assert plan["scope_count"] == len(target.scopes)
    assert plan["compatible_previous_scopes"] == 0
    assert len(plan["neo4j_jobs"]) == 5
    assert len({job["lane"] for job in plan["neo4j_jobs"]}) == 5
    assert {job["lane"] for job in plan["qdrant_jobs"]} == {
        "gdelt_gkg",
        "notebooklm",
        "usgs",
        "firms",
        "ucdp",
        "eonet",
        "gdacs",
    }
    assert len({job["target_projection_revision"] for job in plan["qdrant_jobs"]}) == 1
    assert plan["live_writes"] is False


async def test_source_projector_runs_through_real_qdrant_preview_engine(monkeypatch):
    from qdrant_spatial import derive_spatial_projection_revision
    from spatial_reprojection import reproject_payload

    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "intelligence"))
    from rag.spatial_reenrich import (
        ReenrichmentJob,
        ReenrichmentPage,
        ReenrichmentPoint,
        preview_spatial_reenrichment,
    )

    target = load_normalization_index(
        Path("../backend/data/spatial/catalogs/spatial-v1-2ff6da288a58"),
        crosswalk_path=Path("spatial_catalog/data/country_crosswalk.json"),
    )

    class Store:
        async def fetch_page(self, lane, cursor, limit):
            return ReenrichmentPage(
                points=(
                    ReenrichmentPoint(
                        point_id=1,
                        vector=[0.1, 0.2],
                        payload={
                            "source": "usgs",
                            "usgs_id": "one",
                            "latitude": 48.0,
                            "longitude": 37.8,
                        },
                    ),
                ),
                next_cursor=None,
            )

        async def replace_points(self, lane, replacements):
            raise AssertionError("preview must never write")

    class Projector:
        def project(self, point, job):
            return reproject_payload(point.payload, target)

    report = await preview_spatial_reenrichment(
        Store(),
        Projector(),
        ReenrichmentJob("usgs", derive_spatial_projection_revision(target)),
    )
    assert report["complete"] is True
    assert report["input_fingerprint"]


def test_catalog_revokes_every_stored_derivation_from_the_audit_conflict_examples():
    import json

    from graph_integrity.spatial_normalizer import (
        CountryCodeSystem,
        RawLocationIdentity,
        normalize_location,
    )

    root = Path(__file__).resolve().parents[3]
    evidence = json.loads(
        (root / "docs/reports/2026-09-27-spatial-source-graph-audit-evidence.json").read_text()
    )
    target = load_normalization_index(
        root / "services/backend/data/spatial/catalogs/spatial-v1-2ff6da288a58",
        crosswalk_path=Path("spatial_catalog/data/country_crosswalk.json"),
    )
    for row in evidence["examples"]:
        result = normalize_location(
            RawLocationIdentity(
                country_code=row["code"],
                country_code_system=CountryCodeSystem(row["system"]),
                latitude=row["lat"],
                longitude=row["lon"],
            ),
            target,
        )
        assert result.status == "conflict"
        assert not target.is_compatible_derivation(row["scope"], row["derivation"])
