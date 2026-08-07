"""Tests for graph_integrity.cli — parser only (no DB, no Settings)."""
import json
from argparse import Namespace
from unittest.mock import AsyncMock

import pytest

from graph_integrity.cli import _run_reviewed, build_parser
from graph_integrity.spatial_batch import report_fingerprint


def test_parser_has_graph_integrity_subcommands():
    p = build_parser()
    assert p.parse_args(["report"]).command == "report"
    assert p.parse_args(["backfill-incident-geo", "--dry-run"]).dry_run is True
    assert p.parse_args(["backfill-gdelt-geo"]).dry_run is False
    assert p.parse_args(["spatial-index-smoke"]).command == "spatial-index-smoke"


def test_spatial_backfill_cli_requires_explicit_mode_and_checkpoint():
    parser = build_parser()
    args = parser.parse_args(
        [
            "backfill-spatial-scope",
            "--lane",
            "gdelt_raw",
            "--target-derivation-revision",
            "derive-a",
            "--batch-size",
            "17",
            "--checkpoint",
            "/tmp/spatial-checkpoint.json",
            "--dry-run",
        ]
    )

    assert args.dry_run is True
    assert args.apply is False
    assert args.batch_size == 17
    with pytest.raises(SystemExit):
        parser.parse_args(
            [
                "backfill-spatial-scope",
                "--lane",
                "gdelt_raw",
                "--target-derivation-revision",
                "derive-a",
                "--checkpoint",
                "/tmp/spatial-checkpoint.json",
            ]
        )


def test_spatial_reenrichment_cli_has_explicit_mode_and_previous_catalog():
    args = build_parser().parse_args(
        [
            "reenrich-spatial-scope",
            "--previous-catalog",
            "/catalogs/previous",
            "--checkpoint",
            "/tmp/spatial-checkpoint.json",
            "--lane",
            "rss_pipeline",
            "--dry-run",
        ]
    )

    assert args.command == "reenrich-spatial-scope"
    assert args.lanes == ["rss_pipeline"]
    assert args.dry_run is True


@pytest.mark.asyncio
async def test_apply_requires_matching_reviewed_dry_run(tmp_path):
    dry_run = {
        "schema_version": 1,
        "mode": "dry-run",
        "complete": True,
        "total": 1,
        "writes_planned": 1,
        "writes_applied": 0,
    }
    dry_run["report_fingerprint"] = report_fingerprint(dry_run)
    approval = tmp_path / "approved.json"
    approval.write_text(json.dumps(dry_run))
    applied = {
        **dry_run,
        "mode": "apply",
        "writes_applied": 1,
    }
    applied["report_fingerprint"] = report_fingerprint(applied)
    runner = AsyncMock(side_effect=[dict(dry_run), applied])
    args = Namespace(
        dry_run=False,
        apply=True,
        approved_report=approval,
    )

    result = await _run_reviewed(runner, args)

    assert result == applied
    assert [call.kwargs for call in runner.await_args_list] == [
        {"dry_run": True},
        {"dry_run": False},
    ]


@pytest.mark.asyncio
async def test_apply_without_reviewed_dry_run_is_rejected_before_runner() -> None:
    runner = AsyncMock()
    args = Namespace(dry_run=False, apply=True, approved_report=None)

    with pytest.raises(ValueError, match="requires --approved-report"):
        await _run_reviewed(runner, args)

    runner.assert_not_awaited()
