"""Bind build contexts to one clean commit, without starting Docker."""

import importlib.util
import subprocess
from pathlib import Path
from unittest.mock import Mock

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "build_release", ROOT / "scripts/ops/build_release.py"
)


def module():
    assert SPEC and SPEC.loader
    value = importlib.util.module_from_spec(SPEC)
    SPEC.loader.exec_module(value)
    return value


def git_runner(root, sha="a" * 40, dirty=""):
    def run(command, **kwargs):
        if command[0] == "git":
            if "--show-toplevel" in command:
                output = str(root) + "\n"
            elif "status" in command:
                output = dirty
            elif "archive" in command:
                output = b"fixed committed tar bytes"
            else:
                output = sha + "\n"
            return subprocess.CompletedProcess(command, 0, output, "")
        if command[:3] == ["docker", "image", "inspect"]:
            return subprocess.CompletedProcess(
                command,
                0,
                '[{"Id":"sha256:'
                + "b" * 64
                + '","Config":{"Labels":{"org.opencontainers.image.revision":"'
                + sha
                + '"}}}]',
                "",
            )
        return subprocess.CompletedProcess(command, 0, "", "")

    return Mock(side_effect=run)


@pytest.mark.parametrize("dirty", [" M source.py\n", "?? unknown.txt\n"])
def test_dirty_source_fails_before_archive_or_docker(tmp_path, dirty):
    m = module()
    runner = git_runner(tmp_path, dirty=dirty)
    with pytest.raises(ValueError, match="clean"):
        m.make_plan(tmp_path, ["backend"], runner=runner)
    assert not any(
        c.args[0][0] == "docker" or "archive" in c.args[0]
        for c in runner.call_args_list
    )


def test_invalid_git_revision_fails_without_manual_override(tmp_path):
    m = module()
    runner = git_runner(tmp_path, sha="3234993")
    with pytest.raises(ValueError, match="revision"):
        m.make_plan(tmp_path, ["frontend"], runner=runner)


def test_plan_all_services_exports_exact_commit_and_context(tmp_path):
    m = module()
    runner = git_runner(tmp_path)
    plan = m.make_plan(tmp_path, list(m.SERVICES), runner=runner)
    assert plan["revision"] == "a" * 40
    expected = {
        "vision-enrichment": ("services/vision-enrichment", "Dockerfile"),
        "backend": ("services/backend", "Dockerfile"),
        "frontend": ("services/frontend", "Dockerfile"),
        "intelligence": ("services/intelligence", "Dockerfile"),
        "data-ingestion": ("", "services/data-ingestion/Dockerfile"),
    }
    for item in plan["images"]:
        context, dockerfile = expected[item["service"]]
        assert item["archive_command"][-1] == "a" * 40 + (
            ":" + context if context else ""
        )
        command = item["build_command"]
        assert command[-1] == "-"
        assert command[command.index("--file") + 1] == dockerfile
        assert "ODIN_BUILD_REVISION=" + "a" * 40 in command
        assert "VITE_SPATIAL_SCOPE_ENABLED=true" in command
    assert not any(c.args[0][0] == "docker" for c in runner.call_args_list)


def test_build_uses_archive_bytes_receipt_and_does_not_claim_manifest_digest(tmp_path):
    m = module()
    runner = git_runner(tmp_path / "repo")
    plan = m.make_plan(tmp_path, ["backend"], runner=runner)
    receipt = m.build_plan(plan, tmp_path / "artifacts", runner=runner)
    build = next(
        c for c in runner.call_args_list if c.args[0][:2] == ["docker", "build"]
    )
    assert build.kwargs["input"] == b"fixed committed tar bytes"
    assert receipt["images"][0]["image_id"] == "sha256:" + "b" * 64
    assert receipt["images"][0]["context_sha256"]
    assert "manifest_digest" not in receipt["images"][0]
    assert receipt["release_qualified"] is False
    assert (
        tmp_path / "artifacts" / "backend.context.tar"
    ).read_bytes() == b"fixed committed tar bytes"
    assert (tmp_path / "artifacts" / "receipt.json").is_file()


def test_wrong_image_label_is_rejected(tmp_path):
    m = module()
    runner = git_runner(tmp_path / "repo")
    original = runner.side_effect

    def run(command, **kwargs):
        result = original(command, **kwargs)
        if command[:3] == ["docker", "image", "inspect"]:
            result.stdout = result.stdout.replace("a" * 40, "c" * 40)
        return result

    runner.side_effect = run
    with pytest.raises(ValueError, match="label"):
        m.build_plan(
            m.make_plan(tmp_path, ["backend"], runner=runner),
            tmp_path / "artifacts",
            runner=runner,
        )
    assert not (tmp_path / "artifacts" / "receipt.json").exists()


def test_changed_source_stops_before_next_image(tmp_path):
    m = module()
    runner = git_runner(tmp_path / "repo")
    original = runner.side_effect
    statuses = 0

    def run(command, **kwargs):
        nonlocal statuses
        result = original(command, **kwargs)
        if command[0] == "git" and "status" in command:
            statuses += 1
            if statuses >= 5:
                result.stdout = " M late.py\n"
        return result

    runner.side_effect = run
    plan = m.make_plan(tmp_path, ["backend", "frontend"], runner=runner)
    with pytest.raises(ValueError, match="clean"):
        m.build_plan(plan, tmp_path / "artifacts", runner=runner)
    assert (
        len([c for c in runner.call_args_list if c.args[0][:2] == ["docker", "build"]])
        == 1
    )


def test_existing_artifacts_are_preserved(tmp_path):
    m = module()
    runner = git_runner(tmp_path / "repo")
    folder = tmp_path / "artifacts"
    folder.mkdir()
    (folder / "receipt.json").write_text("existing")
    with pytest.raises(FileExistsError):
        m.build_plan(
            m.make_plan(tmp_path, ["backend"], runner=runner), folder, runner=runner
        )
    assert (folder / "receipt.json").read_text() == "existing"
    assert not any(c.args[0][0] == "docker" for c in runner.call_args_list)


def test_artifacts_in_checkout_are_rejected_without_docker(tmp_path):
    m = module()
    runner = git_runner(tmp_path)
    with pytest.raises(ValueError, match="outside"):
        m.build_plan(
            m.make_plan(tmp_path, ["backend"], runner=runner),
            tmp_path / "artifacts",
            runner=runner,
        )
    assert not any(c.args[0][0] == "docker" for c in runner.call_args_list)


def test_head_changed_after_plan_is_rejected(tmp_path):
    m = module()
    runner = git_runner(tmp_path / "repo")
    plan = m.make_plan(tmp_path, ["backend"], runner=runner)
    runner.side_effect = git_runner(tmp_path / "repo", sha="c" * 40).side_effect
    with pytest.raises(ValueError, match="changed"):
        m.build_plan(plan, tmp_path / "artifacts", runner=runner)
    assert not any(c.args[0][0] == "docker" for c in runner.call_args_list)


def test_cli_rejects_inherited_git_index_override_before_git(monkeypatch, capsys):
    m = module()
    monkeypatch.setenv("GIT_INDEX_FILE", "/tmp/fixture-index")
    monkeypatch.setattr("sys.argv", ["build_release.py"])
    probe = Mock(
        side_effect=AssertionError("Must not inspect an overridden Git context")
    )
    monkeypatch.setattr(m, "make_plan", probe)
    assert m.main() == 1
    assert "Git override" in capsys.readouterr().err
    probe.assert_not_called()
