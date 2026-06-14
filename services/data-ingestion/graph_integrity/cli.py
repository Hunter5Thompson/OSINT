"""CLI for graph-integrity jobs. Reads Neo4j creds + parquet path from Settings."""
from __future__ import annotations

import argparse
import asyncio

from graph_integrity import geo_gdelt, geo_incident, report
from graph_integrity.neo4j_client import Neo4jClient


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="graph-integrity")
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("report")
    inc = sub.add_parser("backfill-incident-geo")
    inc.add_argument("--dry-run", action="store_true")
    gd = sub.add_parser("backfill-gdelt-geo")
    gd.add_argument("--dry-run", action="store_true")
    return p


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
            print(report.shape_report(orphans, geo, dup))
        elif args.command == "backfill-incident-geo":
            n = await geo_incident.run(client, dry_run=args.dry_run)
            print(f"incident-geo: {n} incidents {'(dry-run)' if args.dry_run else 'wired'}")
        elif args.command == "backfill-gdelt-geo":
            gdelt_cfg = get_gdelt_settings()
            n = await geo_gdelt.run(client, gdelt_cfg.parquet_path, dry_run=args.dry_run)
            print(f"gdelt-geo: {n} events {'(dry-run)' if args.dry_run else 'wired'}")
    finally:
        await client.close()


def main() -> None:
    asyncio.run(_amain(build_parser().parse_args()))


if __name__ == "__main__":
    main()
