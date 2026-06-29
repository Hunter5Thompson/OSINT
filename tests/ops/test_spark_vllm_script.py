"""Safety contract for the Spark vLLM operations script."""

from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "spark" / "odin-spark-vllm.sh"


def _dry_run(action: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(SCRIPT), "--dry-run", action],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def test_dry_run_up_prints_cutover_without_calling_docker() -> None:
    result = _dry_run("up")

    assert result.returncode == 0, result.stderr
    assert "[dry-run] docker stop vllm-qwen36" in result.stdout
    assert "[dry-run] docker run" in result.stdout
    assert "would wait for" in result.stdout


def test_dry_run_rollback_prints_both_container_transitions() -> None:
    result = _dry_run("rollback")

    assert result.returncode == 0, result.stderr
    assert "[dry-run] docker stop vllm-qwen36-nvfp4" in result.stdout
    assert "[dry-run] docker start vllm-qwen36" in result.stdout
