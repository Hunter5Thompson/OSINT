"""Vision must participate in the existing release source contract."""

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def load(name):
    spec = importlib.util.spec_from_file_location(
        name, ROOT / "scripts/ops" / f"{name}.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_vision_docker_has_baked_and_labelled_revision_from_pinned_base():
    body = (ROOT / "services/vision-enrichment/Dockerfile").read_text()
    expected_base = (ROOT / "services/backend/Dockerfile").read_text().splitlines()[0]
    assert body.splitlines()[0] == expected_base
    assert "ARG ODIN_BUILD_REVISION=unknown" in body
    assert (
        "Path('/app/.build-revision')" in body
        or "pathlib.Path('/app/.build-revision')" in body
    )
    assert "LABEL org.opencontainers.image.revision=$ODIN_BUILD_REVISION" in body
    assert "uv sync --locked" in body


def test_vision_has_ci_image_build_smoke_and_service_context():
    workflow = (
        (ROOT / ".github/workflows/ci.yml").read_text().split("  test-intelligence:")[0]
    )
    assert "- service: vision-enrichment" in workflow
    assert "context: services/vision-enrichment" in workflow
    assert "dockerfile: services/vision-enrichment/Dockerfile" in workflow
    assert "vision-enrichment" in load("smoke_image").SERVICES
    assert load("build_release").SERVICES["vision-enrichment"] == (
        "services/vision-enrichment",
        "Dockerfile",
    )


def test_vision_smoke_proves_process_revision_without_claiming_consumer_readiness(
    monkeypatch,
):
    import json
    import subprocess

    m = load("smoke_image")
    calls = []
    revision = "a" * 40

    def docker(*args, **kwargs):
        calls.append(args)
        if args[:2] == ("image", "inspect"):
            body = json.dumps(
                [
                    {
                        "Id": "sha256:" + "c" * 64,
                        "Config": {
                            "Labels": {"org.opencontainers.image.revision": revision}
                        },
                    }
                ]
            )
        elif args[0] == "inspect":
            body = json.dumps([{"State": {"Running": True}}])
        elif args[0] == "logs":
            body = "\n".join(
                json.dumps({"event": event, "revision": revision})
                for event in (
                    "vision_service_starting",
                    "scheduler_starting",
                    "scheduler_running",
                )
            )
        else:
            body = ""
        return subprocess.CompletedProcess(args, 0, body, "")

    monkeypatch.setattr(m, "docker", docker)
    result = m.smoke("vision-enrichment", "fixture-image", revision)
    assert result["process_start_revision"] == revision
    assert result["consumer_readiness"] == "not_assessed"
    assert (
        "network",
        "create",
        "--internal",
        next(c[3] for c in calls if c[:3] == ("network", "create", "--internal")),
    ) in calls
    run = next(c for c in calls if c[0] == "run")
    assert (
        "--entrypoint" not in run
        and "-p" not in run
        and "-v" not in run
        and "--mount" not in run
    )
    assert "ODIN_BUILD_REVISION=" + "b" * 40 in run
    assert any(c[:2] == ("rm", "-f") for c in calls)


def test_vision_smoke_rejects_runtime_revision_even_with_correct_oci_label(monkeypatch):
    import json
    import subprocess

    import pytest

    m = load("smoke_image")
    revision = "a" * 40

    def docker(*args, **kwargs):
        if args[:2] == ("image", "inspect"):
            body = json.dumps(
                [
                    {
                        "Id": "sha256:" + "c" * 64,
                        "Config": {
                            "Labels": {"org.opencontainers.image.revision": revision}
                        },
                    }
                ]
            )
        elif args[0] == "inspect":
            body = json.dumps([{"State": {"Running": True}}])
        elif args[0] == "logs":
            body = "\n".join(
                json.dumps(
                    {
                        "event": event,
                        "revision": "b" * 40
                        if event == "vision_service_starting"
                        else revision,
                    }
                )
                for event in (
                    "vision_service_starting",
                    "scheduler_starting",
                    "scheduler_running",
                )
            )
        else:
            body = ""
        return subprocess.CompletedProcess(args, 0, body, "")

    monkeypatch.setattr(m, "docker", docker)
    with pytest.raises(AssertionError):
        m.smoke("vision-enrichment", "fixture-image", revision)
