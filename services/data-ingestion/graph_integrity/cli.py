"""CLI for graph-integrity jobs. Reads Neo4j creds + parquet path from Settings."""
from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any

from graph_integrity import (
    backfill_spatial_scope,
    cleanup_null_island,
    geo_gdelt,
    geo_incident,
    reenrich_spatial_scope,
    rekey_incident_locations,
    report,
    spatial_index_smoke,
)
from graph_integrity.neo4j_client import Neo4jClient
from graph_integrity.spatial_batch import (
    SUPPORTED_LOCATION_LANES,
    JsonCheckpointStore,
    report_fingerprint,
    validate_dry_run_approval,
)
from graph_integrity.spatial_normalizer import (
    load_active_normalization_index,
    load_normalization_index,
)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="graph-integrity")
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("report")
    inc = sub.add_parser("backfill-incident-geo")
    inc.add_argument("--dry-run", action="store_true")
    gd = sub.add_parser("backfill-gdelt-geo")
    gd.add_argument("--dry-run", action="store_true")
    rk = sub.add_parser("rekey-incident-locations")
    rk.add_argument("--dry-run", action="store_true")
    cn = sub.add_parser("cleanup-null-island")
    cn.add_argument("--dry-run", action="store_true")
    sub.add_parser("spatial-index-smoke")
    spatial_backfill = sub.add_parser("backfill-spatial-scope")
    spatial_backfill.add_argument("--lane", choices=SUPPORTED_LOCATION_LANES, required=True)
    spatial_backfill.add_argument("--target-derivation-revision", required=True)
    _add_spatial_batch_arguments(spatial_backfill)
    spatial_reenrich = sub.add_parser("reenrich-spatial-scope")
    spatial_reenrich.add_argument("--previous-catalog", type=Path, required=True)
    spatial_reenrich.add_argument(
        "--lane",
        action="append",
        choices=SUPPORTED_LOCATION_LANES,
        dest="lanes",
    )
    _add_spatial_batch_arguments(spatial_reenrich)
    return p


def _add_spatial_batch_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--batch-size", type=int, default=500)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--report-out", type=Path)
    parser.add_argument("--approved-report", type=Path)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--apply", action="store_true")


async def _amain(args: argparse.Namespace) -> None:
    # Settings are instantiated inside _amain so imports work without env vars.
    from config import Settings
    from gdelt_raw.config import get_settings as get_gdelt_settings

    cfg = Settings()
    client = Neo4jClient(cfg.neo4j_url, cfg.neo4j_user, cfg.neo4j_password)
    try:
        if args.command == "report":
            orphans = await client.run(report.ORPHAN_BY_LABEL, {"labels": report.REPORT_LABELS})
            geo = await client.run(report.GEO_COVERAGE)
            dup = await client.run(report.DUP_ACTOR_EDGES, {"actor_rels": report.ACTOR_RELS})
            coord_dis = await client.run(report.COORD_DISAGREEMENT)
            null_island = await client.run(report.NULL_ISLAND)
            print(report.shape_report(orphans, geo, dup, coord_dis, null_island))
        elif args.command == "backfill-incident-geo":
            n = await geo_incident.run(client, dry_run=args.dry_run)
            print(f"incident-geo: {n} incidents {'(dry-run)' if args.dry_run else 'wired'}")
        elif args.command == "backfill-gdelt-geo":
            gdelt_cfg = get_gdelt_settings()
            n = await geo_gdelt.run(client, gdelt_cfg.parquet_path, dry_run=args.dry_run)
            print(f"gdelt-geo: {n} events {'(dry-run)' if args.dry_run else 'wired'}")
        elif args.command == "rekey-incident-locations":
            n = await rekey_incident_locations.run(client, dry_run=args.dry_run)
            suffix = "(dry-run)" if args.dry_run else "rewired"
            print(f"rekey-incident-locations: {n} incidents {suffix}")
            if not args.dry_run:
                dups = await rekey_incident_locations.verify_no_duplicate_loc_keys(client)
                if dups:
                    print(
                        f"  preflight: {len(dups)} duplicate loc_keys REMAIN"
                        f" -- do NOT apply the constraint yet: {dups[:5]}"
                    )
                else:
                    print(
                        "  preflight: 0 duplicate loc_keys"
                        " -- safe to apply migrations/location_loc_key_unique.cypher"
                    )
        elif args.command == "cleanup-null-island":
            n = await cleanup_null_island.run(client, dry_run=args.dry_run)
            suffix = "(dry-run)" if args.dry_run else "deleted"
            print(f"cleanup-null-island: {n} (0,0) locations {suffix}")
        elif args.command == "spatial-index-smoke":
            evidence = await spatial_index_smoke.collect_spatial_index_plan_evidence(client)
            print(json.dumps(evidence, sort_keys=True, separators=(",", ":")))
            if not evidence["all_expected_indexes_used"]:
                raise RuntimeError("one or more spatial indexes were not selected")
        elif args.command == "backfill-spatial-scope":
            spatial_index = load_active_normalization_index(
                cfg.spatial_catalog_path,
                crosswalk_path=cfg.spatial_country_crosswalk_path,
            )
            checkpoints = JsonCheckpointStore(args.checkpoint)

            async def run_backfill(*, dry_run: bool) -> dict[str, Any]:
                return await backfill_spatial_scope.run(
                    client,
                    spatial_index,
                    checkpoints,
                    lane=args.lane,
                    target_derivation_revision=args.target_derivation_revision,
                    batch_size=args.batch_size,
                    dry_run=dry_run,
                )

            result = await _run_reviewed(run_backfill, args)
            _emit_report(result, args.report_out)
        elif args.command == "reenrich-spatial-scope":
            current_index = load_active_normalization_index(
                cfg.spatial_catalog_path,
                crosswalk_path=cfg.spatial_country_crosswalk_path,
            )
            previous_index = load_normalization_index(
                args.previous_catalog,
                crosswalk_path=cfg.spatial_country_crosswalk_path,
            )
            jobs = reenrich_spatial_scope.plan_reenrichment_jobs(
                reenrich_spatial_scope.derivation_revision_map(previous_index),
                reenrich_spatial_scope.derivation_revision_map(current_index),
                lanes=args.lanes or SUPPORTED_LOCATION_LANES,
                batch_size=args.batch_size,
            )
            checkpoints = JsonCheckpointStore(args.checkpoint)

            async def run_reenrichment(*, dry_run: bool) -> dict[str, Any]:
                return await reenrich_spatial_scope.run_jobs(
                    client,
                    current_index,
                    checkpoints,
                    jobs,
                    dry_run=dry_run,
                )

            result = await _run_reviewed(run_reenrichment, args)
            _emit_report(result, args.report_out)
    finally:
        await client.close()


def main() -> None:
    asyncio.run(_amain(build_parser().parse_args()))


async def _run_reviewed(runner, args: argparse.Namespace) -> dict[str, Any]:
    if args.dry_run:
        if args.approved_report is not None:
            raise ValueError("--approved-report is only valid with --apply")
        return await runner(dry_run=True)
    if args.approved_report is None:
        raise ValueError("--apply requires --approved-report from a reviewed dry-run")
    approved = _load_json_object(args.approved_report)
    fresh = await runner(dry_run=True)
    validate_dry_run_approval(approved, fresh)
    return await runner(dry_run=False)


def _load_json_object(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise ValueError("approved report must be a regular file")
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise ValueError("approved report must contain a JSON object")
    return value


def _emit_report(report: dict[str, Any], path: Path | None) -> None:
    if report.get("report_fingerprint") != report_fingerprint(report):
        raise ValueError("refusing to emit a report with an invalid fingerprint")
    encoded = json.dumps(report, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    if path is None:
        print(encoded)
        return
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise ValueError("report output must be a regular file")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"{encoded}\n")


if __name__ == "__main__":
    main()
