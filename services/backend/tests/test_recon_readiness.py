"""Optional Recon states survive app startup without concealing failed delivery."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app


@pytest.mark.parametrize(
    "mode,configured,payload,status,availability,reason",
    [
        ("auto", False, None, 200, "disabled", "not_configured"),
        ("disabled", True, "invalid-json", 200, "disabled", "operator_disabled"),
        ("enabled", False, None, 503, None, None),
        ("auto", True, None, 503, None, None),
        ("auto", True, "invalid-json", 503, None, None),
    ],
)
def test_startup_distinguishes_inactive_and_failed_recon(
    tmp_path, monkeypatch, mode, configured, payload, status, availability, reason,
):
    config = settings.model_dump()
    config["recon_mode"] = mode
    monkeypatch.setattr("app.main.settings", SimpleNamespace(**config))
    manifest = tmp_path / "recon_manifest.json"
    if payload is not None:
        manifest.write_text(payload)
    if configured:
        monkeypatch.setenv("RECON_MANIFEST_PATH", str(manifest))
    else:
        monkeypatch.delenv("RECON_MANIFEST_PATH", raising=False)
        # Relocate only the default path, so the default absence is hermetic.
        monkeypatch.setattr("app.main.__file__", str(tmp_path / "app/main.py"))
    with patch("app.services.report_store.bootstrap_report_schema", new=AsyncMock()):
        with TestClient(app) as client:
            response = client.get("/api/recon/scenes")
            assert response.status_code == status
            if availability is not None:
                assert response.json() == {
                    "scenes": [], "availability": availability, "reason": reason,
                }
            assert client.get("/api/health").status_code == 200
