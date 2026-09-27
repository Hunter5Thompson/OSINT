"""Tests for vision tool — URL validation, SSRF protection, image analysis."""

from unittest.mock import patch

import pytest
from pydantic import ValidationError

from agents.tools.vision import (
    _is_private_ip,
    analyze_image,
    validate_image_url,
)
from tests.tool_runtime import agent_state, invoke_runtime_tool


class TestUrlValidation:
    def test_https_allowed(self):
        assert validate_image_url("https://example.com/image.jpg") is True

    def test_http_rejected(self):
        assert validate_image_url("http://example.com/image.jpg") is False

    def test_local_path_rejected(self):
        assert validate_image_url("/tmp/odin/images/sat.png") is False

    def test_non_https_local_path(self):
        assert validate_image_url("/etc/passwd") is False

    def test_empty_url_rejected(self):
        assert validate_image_url("") is False

    def test_ftp_rejected(self):
        assert validate_image_url("ftp://files.com/image.png") is False

    def test_data_url_rejected(self):
        assert validate_image_url("data:image/png;base64,abc") is False

    @pytest.mark.parametrize("url", [
        "http://example.com/image.jpg", "https://user:pass@example.com/a.png",
        "https://@example.com/a.png",
        "/tmp/odin/images/a.png", "file:///tmp/a.png", "data:image/png;base64,AA==",
        "https:///missing-host.png", "https://example.com:bad/a.png", "https://", "https://[bad",
    ])
    def test_shared_query_contract_rejects_non_https_or_credentials(self, url):
        from main import QueryRequest
        with pytest.raises(ValidationError):
            QueryRequest(query="inspect", spatial_relation="either", image_url=url)

    @pytest.mark.parametrize("url", [
        "https://example.com/image.jpg", "https://8.8.8.8/a.png",
    ])
    def test_shared_query_contract_accepts_https_public_hosts(self, url):
        from main import QueryRequest
        request = QueryRequest(query="inspect", spatial_relation="either", image_url=url)
        assert request.image_url == url

    @pytest.mark.parametrize("url", [
        "http://example.com/image.jpg", "https://user:pass@example.com/a.png",
        "https://@example.com/a.png", "/tmp/odin/images/a.png", "file:///tmp/a.png",
        "data:image/png;base64,AA==", "https:///missing-host.png",
        "https://example.com:bad/a.png", "https://", "https://[bad",
    ])
    def test_http_query_rejects_image_url_before_pipeline(self, url):
        from fastapi.testclient import TestClient

        from main import app
        with patch(
            "main.run_intelligence_query", side_effect=AssertionError("must not run")
        ) as run:
            response = TestClient(app).post(
                "/query",
                json={"query": "inspect", "spatial_relation": "either", "image_url": url},
            )
        assert response.status_code == 422
        run.assert_not_called()

    @pytest.mark.asyncio
    async def test_loader_rechecks_url_contract(self):
        from agents.tools.vision import _load_image
        with patch("agents.tools.vision._download_image") as download:
            with pytest.raises(ValueError):
                await _load_image("https://user:pass@example.com/a.png")
            download.assert_not_awaited()


class TestPrivateIpDetection:
    def test_localhost_is_private(self):
        assert _is_private_ip("127.0.0.1") is True

    def test_ten_range_is_private(self):
        assert _is_private_ip("10.0.0.5") is True

    def test_172_range_is_private(self):
        assert _is_private_ip("172.16.0.1") is True

    def test_192_range_is_private(self):
        assert _is_private_ip("192.168.1.1") is True

    def test_public_ip_not_private(self):
        assert _is_private_ip("8.8.8.8") is False

    def test_invalid_ip_treated_as_not_private(self):
        assert _is_private_ip("not-an-ip") is False


class TestAnalyzeImageTool:
    @pytest.mark.asyncio
    async def test_rejects_http_url(self):
        result = await invoke_runtime_tool(
            analyze_image,
            {"question": "what is this"},
            state=agent_state(image_url="http://evil.com/img.jpg"),
        )
        assert "rejected" in result.lower() or "invalid" in result.lower()

    @pytest.mark.asyncio
    async def test_rejects_private_path(self):
        result = await invoke_runtime_tool(
            analyze_image,
            {"question": "what is this"},
            state=agent_state(image_url="/etc/shadow"),
        )
        assert "rejected" in result.lower() or "invalid" in result.lower()

    @pytest.mark.asyncio
    async def test_handles_download_error(self):
        with patch("agents.tools.vision._load_image") as mock_load:
            mock_load.side_effect = Exception("Connection refused")

            result = await invoke_runtime_tool(
                analyze_image,
                {"question": "describe this"},
                state=agent_state(image_url="https://example.com/img.jpg"),
            )
            assert "failed" in result.lower()
            mock_load.assert_awaited_once_with("https://example.com/img.jpg")

    @pytest.mark.asyncio
    async def test_without_attached_image_is_blocked_before_loading(self):
        with patch(
            "agents.tools.vision._load_image",
            side_effect=AssertionError("image load must not run"),
        ):
            result = await invoke_runtime_tool(
                analyze_image,
                {"question": "describe this"},
                state=agent_state(image_url=None),
            )

        assert result.startswith("SPATIAL_SCOPE_UNSUPPORTED")

    @pytest.mark.asyncio
    async def test_malformed_runtime_image_is_blocked_without_assert_dependency(self):
        with patch(
            "agents.tools.vision._load_image",
            side_effect=AssertionError("image load must not run"),
        ):
            result = await invoke_runtime_tool(
                analyze_image,
                {"question": "describe this"},
                state=agent_state(image_url=42),
            )

        assert result.startswith("SPATIAL_SCOPE_UNSUPPORTED")
