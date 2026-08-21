"""Static contract for the checked-in Spark Qwen3.8 launcher and verifier."""

from __future__ import annotations

import importlib.util
import re
import subprocess
from pathlib import Path

from config import Settings

REPO_ROOT = Path(__file__).resolve().parents[3]
LAUNCHER = REPO_ROOT / "scripts" / "spark" / "odin-spark-vllm.sh"
VERIFIER = REPO_ROOT / "scripts" / "spark" / "verify_ingestion_contract.py"
STATUS_DOC = REPO_ROOT / "docs" / "CONTAINER-STATUS.md"
SERVED_MODEL = "Qwen/Qwen3.8-27B"
MODEL_REPOSITORY = "unsloth/Qwen3.8-27B-NVFP4"
IMAGE = (
    "vllm/vllm-openai@"
    "sha256:0a51ea5b4ae2dc5d81890e5173f54203d2a3ae0cfffe51b8fd2afd4391bfd967"
)


def _shell_assignment(script: str, name: str) -> str:
    match = re.search(
        rf'^{name}="([^"]+)"(?:\s+#.*)?$',
        script,
        re.MULTILINE,
    )
    assert match is not None
    return match.group(1)


def _load_verifier():
    spec = importlib.util.spec_from_file_location("spark_contract_verifier", VERIFIER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_launcher_matches_verified_qwen38_runtime_contract() -> None:
    script = LAUNCHER.read_text()

    assert _shell_assignment(script, "IMG_NVFP4") == IMAGE
    assert _shell_assignment(script, "NEW") == "vllm-qwen38-nvfp4"
    assert _shell_assignment(script, "SERVED") == SERVED_MODEL
    assert f"--model {MODEL_REPOSITORY}" in script
    assert "--max-model-len 131072" in script
    assert "--gpu-memory-utilization 0.85" in script
    assert "--max-num-seqs 4" in script
    assert "--enable-auto-tool-choice" in script
    assert "--tool-call-parser qwen3_coder" in script
    assert "--reasoning-parser qwen3" in script
    assert "--speculative-config" in script
    assert '"method":"mtp","num_speculative_tokens":5' in script


def test_launcher_dry_run_serves_the_client_default_without_docker() -> None:
    result = subprocess.run(
        ["bash", str(LAUNCHER), "--dry-run", "up"],
        check=True,
        capture_output=True,
        text=True,
    )

    assert MODEL_REPOSITORY in result.stdout
    assert f"--served-model-name {SERVED_MODEL}" in result.stdout


def test_verifier_matches_client_default_and_timeout() -> None:
    verifier = _load_verifier()

    assert Settings.model_fields["ingestion_vllm_model"].default == SERVED_MODEL
    assert Settings.model_fields["ingestion_vllm_timeout"].default == 240.0
    assert verifier.MODEL == SERVED_MODEL
    assert verifier._post.__defaults__ == (240,)


def test_runbook_marks_qwen38_as_current_spark_production() -> None:
    document = STATUS_DOC.read_text()
    heading = "### vLLM + Qwen3.8-27B NVFP4 on the Spark (DGX GB10)"

    assert heading in document
    current = document.split(heading, maxsplit=1)[1].split(
        "## Infrastructure Containers", maxsplit=1
    )[0]
    assert "**Status: WORKS (production)." in current
    assert "vllm-qwen38-nvfp4" in current
    assert MODEL_REPOSITORY in current
    assert SERVED_MODEL in current
    assert "--max-model-len 131072" in current
    assert "--speculative-config" in current
    assert "INGESTION_VLLM_MODEL=Qwen/Qwen3.6-35B-A3B" in current
