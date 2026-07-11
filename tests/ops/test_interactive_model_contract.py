"""Executable contract for the interactive Base + Munin compose path."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
COMPOSE_FIXTURE = ROOT / "tests" / "fixtures" / "compose.env"
VLLM_IMAGE = (
    "vllm/vllm-openai@sha256:228113d30448941e7a845f57ef0b3d3ea74ffda81be72ded4f8d6dfab0124fe6"
)


def _copy_compose_project(destination: Path) -> Path:
    shutil.copy2(ROOT / "docker-compose.yml", destination / "docker-compose.yml")
    shutil.copy2(
        ROOT / "docker-compose.override.yml",
        destination / "docker-compose.override.yml",
    )
    fixture = destination / "tests" / "fixtures" / "compose.env"
    fixture.parent.mkdir(parents=True)
    shutil.copy2(COMPOSE_FIXTURE, fixture)
    return fixture


def _render_contract_profiles(project: Path) -> dict:
    fixture = _copy_compose_project(project)
    home = project / "home"
    home.mkdir()
    env = {
        "HOME": str(home),
        "ODIN_ENV_FILE": str(fixture.relative_to(project)),
        "PATH": os.environ["PATH"],
    }
    result = subprocess.run(
        [
            "docker",
            "compose",
            "--env-file",
            str(fixture.relative_to(project)),
            "--profile",
            "interactive",
            "--profile",
            "ingestion",
            "--profile",
            "interactive-spark",
            "config",
            "--no-env-resolution",
            "--format",
            "json",
        ],
        cwd=project,
        env=env,
        check=False,
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr
    assert not (project / ".env").exists()
    return json.loads(result.stdout)


def _env_file_paths(service: dict) -> set[Path]:
    paths: set[Path] = set()
    for item in service.get("env_file", []):
        raw = item.get("path") if isinstance(item, dict) else item
        paths.add(Path(raw).resolve())
    return paths


def test_service_env_files_use_synthetic_env_without_root_dotenv(tmp_path: Path) -> None:
    config = _render_contract_profiles(tmp_path)
    expected = (tmp_path / "tests" / "fixtures" / "compose.env").resolve()

    assert _env_file_paths(config["services"]["backend"]) == {expected}
    assert _env_file_paths(config["services"]["intelligence"]) == {expected}
    assert _env_file_paths(config["services"]["data-ingestion"]) == {expected}
    assert _env_file_paths(config["services"]["data-ingestion-spark"]) == {expected}


def test_interactive_render_keeps_base_and_munin_contract(tmp_path: Path) -> None:
    config = _render_contract_profiles(tmp_path)
    vllm = config["services"]["vllm-9b"]
    intelligence = config["services"]["intelligence"]
    command = vllm["command"]
    command_text = " ".join(command) if isinstance(command, list) else str(command)

    assert vllm["image"] == VLLM_IMAGE
    assert "--enable-lora" in command_text
    assert "--lora-modules munin=/models/lora/munin" in command_text
    assert intelligence["environment"]["VLLM_MODEL"] == "qwen3.5"
    assert intelligence["environment"]["SYNTHESIS_MODEL"] == "munin"
    assert (
        intelligence["environment"]["VLLM_MODEL"] != intelligence["environment"]["SYNTHESIS_MODEL"]
    )
