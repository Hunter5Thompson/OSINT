"""Tests for graph_integrity.cli — parser only (no DB, no Settings)."""
from graph_integrity.cli import build_parser


def test_parser_has_graph_integrity_subcommands():
    p = build_parser()
    assert p.parse_args(["report"]).command == "report"
    assert p.parse_args(["backfill-incident-geo", "--dry-run"]).dry_run is True
    assert p.parse_args(["backfill-gdelt-geo"]).dry_run is False
    assert p.parse_args(["spatial-index-smoke"]).command == "spatial-index-smoke"
