"""The process build revision must survive model-readiness failures."""

from unittest.mock import AsyncMock

import httpx
import pytest

import main
from model_readiness import ModelReadiness, ReadinessReason


@pytest.mark.asyncio
@pytest.mark.parametrize("ready", [True, False])
async def test_health_exposes_process_revision_even_when_not_ready(
    monkeypatch: pytest.MonkeyPatch, ready: bool,
) -> None:
    revision = "a" * 40
    monkeypatch.setattr(main, "BUILD_REVISION", revision, raising=False)
    monkeypatch.setenv("ODIN_BUILD_REVISION", "b" * 40)
    monkeypatch.setattr(main, "check_model_readiness", AsyncMock(return_value=ModelReadiness(
        ready=ready,
        reason=ReadinessReason.READY if ready else ReadinessReason.MISSING_MODELS,
        required_models=("qwen3.5", "munin"),
        missing_models=() if ready else ("munin",),
    )))

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=main.app), base_url="http://intelligence.test",
    ) as client:
        response = await client.get("/health")

    assert response.status_code == (200 if ready else 503)
    assert response.json()["revision"] == revision


@pytest.mark.asyncio
async def test_missing_process_revision_is_explicitly_unknown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(main, "BUILD_REVISION", None, raising=False)
    monkeypatch.setattr(main, "check_model_readiness", AsyncMock(return_value=ModelReadiness(
        ready=True, reason=ReadinessReason.READY, required_models=("qwen3.5",), missing_models=(),
    )))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=main.app), base_url="http://intelligence.test",
    ) as client:
        response = await client.get("/health")

    assert response.json()["revision"] is None


@pytest.mark.parametrize("payload", [
    b"unknown\n", b"deadbeef\n", b"g" * 40, b"a" * 40 + b"suffix", b"\xff",
    b"a" * 40 + b" " * 100,
])
def test_invalid_image_metadata_does_not_claim_a_revision(tmp_path, payload: bytes) -> None:
    from build_revision import read_image_revision

    path = tmp_path / ".build-revision"
    path.write_bytes(payload)

    assert read_image_revision(path) is None


def test_image_metadata_is_used_instead_of_environment(
    tmp_path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from build_revision import read_image_revision

    path = tmp_path / ".build-revision"
    path.write_text("a" * 40 + "\n")
    monkeypatch.setenv("ODIN_BUILD_REVISION", "b" * 40)

    assert read_image_revision(path) == "a" * 40
    assert read_image_revision(tmp_path / "missing") is None
