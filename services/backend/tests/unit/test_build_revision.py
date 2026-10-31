"""Health reports the process build, rather than caller environment claims."""

import pytest
from fastapi.testclient import TestClient

import app.main as main


def test_missing_build_revision_is_explicitly_unknown(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ODIN_BUILD_REVISION", "f" * 40)
    monkeypatch.setattr(main, "BUILD_REVISION", None, raising=False)

    response = TestClient(main.app).get("/api/health")

    assert response.status_code == 200
    assert response.json()["revision"] is None
    assert response.json()["version"] == "0.1.0"


def test_health_reports_the_loaded_build_revision(monkeypatch: pytest.MonkeyPatch) -> None:
    revision = "a" * 40
    monkeypatch.setattr(main, "BUILD_REVISION", revision, raising=False)
    monkeypatch.setenv("ODIN_BUILD_REVISION", "b" * 40)

    response = TestClient(main.app).get("/api/health")

    assert response.json()["revision"] == revision


@pytest.mark.parametrize("payload", [
    b"unknown\n", b"deadbeef\n", b"g" * 40, b"a" * 40 + b"suffix", b"\xff",
    b"a" * 40 + b" " * 100,
])
def test_invalid_image_metadata_does_not_claim_a_revision(tmp_path, payload: bytes) -> None:
    from app.build_revision import read_image_revision

    path = tmp_path / ".build-revision"
    path.write_bytes(payload)

    assert read_image_revision(path) is None


def test_image_metadata_is_used_instead_of_environment(
    tmp_path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.build_revision import read_image_revision

    path = tmp_path / ".build-revision"
    path.write_text("a" * 40 + "\n")
    monkeypatch.setenv("ODIN_BUILD_REVISION", "b" * 40)

    assert read_image_revision(path) == "a" * 40
    assert read_image_revision(tmp_path / "missing") is None
