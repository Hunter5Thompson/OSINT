"""`odin.sh up` warms every served local LLM after an interactive start.

The first request after a vLLM (re)start pays kernel warm-up; without a warm-up the
first ReAct query spent ~87 s in iteration 0 and blew the 120 s analysis budget.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

MODELS_JSON = '{"data":[{"id":"qwen3.5"},{"id":"munin"}]}'


def _run_up(tmp_path: Path, mode: str, *, models_json: str = MODELS_JSON) -> tuple[
    subprocess.CompletedProcess[str], list[str], str
]:
    repository = tmp_path / "repository"
    (repository / "services" / "data-ingestion").mkdir(parents=True)
    for name in ("odin.sh", "docker-compose.yml", "docker-compose.override.yml"):
        shutil.copy2(ROOT / name, repository / name)
    env_file = repository / "runtime.env"
    env_file.write_text("ODIN_BIND_HOST=127.0.0.1\nNEO4J_PASSWORD=x\n", encoding="utf-8")
    env_file.chmod(0o600)

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    docker_log = tmp_path / "docker.log"
    curl_log = tmp_path / "curl.log"
    (fake_bin / "docker").write_text(
        """#!/usr/bin/env bash
printf '%s\\n' "$*" >> "$ODIN_TEST_DOCKER_LOG"
if [[ " $* " == *" -f - config --format json "* ]]; then
  echo '{"services":{"odin-preflight":{"environment":{"NEO4J_CONFIGURED":"configured"},"ports":[{"host_ip":"127.0.0.1"}]}}}'
fi
exit 0
""",
        encoding="utf-8",
    )
    (fake_bin / "curl").write_text(
        """#!/usr/bin/env bash
printf '%s\\n' "$*" >> "$ODIN_TEST_CURL_LOG"
if [[ " $* " == *"/v1/models"* ]]; then
  printf '%s' "$ODIN_TEST_MODELS_JSON"
fi
exit 0
""",
        encoding="utf-8",
    )
    (fake_bin / "uv").write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    for stub in fake_bin.iterdir():
        stub.chmod(0o755)
    home = tmp_path / "home"
    home.mkdir()

    result = subprocess.run(
        [str(repository / "odin.sh"), "--env-file", str(env_file), "up", mode],
        cwd=repository,
        env={
            "HOME": str(home),
            "MODELS_PATH": str(tmp_path / "models"),
            "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
            "SPARK_VLLM_URL": "http://127.0.0.1:1",
            "ODIN_TEST_DOCKER_LOG": str(docker_log),
            "ODIN_TEST_CURL_LOG": str(curl_log),
            "ODIN_TEST_MODELS_JSON": models_json,
            "ODIN_WARMUP_TIMEOUT_S": "2",
        },
        check=False,
        text=True,
        capture_output=True,
    )
    curls = curl_log.read_text(encoding="utf-8").splitlines() if curl_log.exists() else []
    docker = docker_log.read_text(encoding="utf-8") if docker_log.exists() else ""
    return result, curls, docker


def _warmup_posts(curls: list[str]) -> list[str]:
    return [c for c in curls if "/v1/chat/completions" in c and "127.0.0.1:8000" in c]


def test_up_interactive_spark_warms_every_listed_local_model(tmp_path: Path) -> None:
    result, curls, docker = _run_up(tmp_path, "interactive-spark")

    assert result.returncode == 0, result.stdout + result.stderr
    posts = _warmup_posts(curls)
    assert len(posts) == 2
    assert any('"model":"qwen3.5"' in p for p in posts)
    assert any('"model":"munin"' in p for p in posts)
    assert " up -d " in f" {docker} "
    assert "warm" in result.stdout.lower()


def test_up_interactive_warms_local_llm(tmp_path: Path) -> None:
    result, curls, _ = _run_up(tmp_path, "interactive")

    assert result.returncode == 0, result.stdout + result.stderr
    assert len(_warmup_posts(curls)) == 2


def test_up_ingestion_does_not_warm_the_interactive_llm(tmp_path: Path) -> None:
    result, curls, _ = _run_up(tmp_path, "ingestion")

    assert result.returncode == 0, result.stdout + result.stderr
    assert _warmup_posts(curls) == []


def test_unreachable_llm_warns_but_does_not_fail_up(tmp_path: Path) -> None:
    result, curls, _ = _run_up(tmp_path, "interactive-spark", models_json="")

    assert result.returncode == 0, result.stdout + result.stderr
    assert _warmup_posts(curls) == []
    assert "WARN" in result.stdout
