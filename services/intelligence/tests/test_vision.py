"""Tests for vision tool — URL validation, SSRF protection, image analysis."""

import pytest
from unittest.mock import AsyncMock, patch

from agents.tools.vision import (
    validate_image_url,
    _is_private_ip,
    analyze_image,
)


class TestUrlValidation:
    def test_https_allowed(self):
        assert validate_image_url("https://example.com/image.jpg") is True

    def test_http_rejected(self):
        assert validate_image_url("http://example.com/image.jpg") is False

    def test_whitelisted_local_path(self):
        assert validate_image_url("/tmp/odin/images/sat.png") is True

    def test_non_whitelisted_local_path(self):
        assert validate_image_url("/etc/passwd") is False

    def test_empty_url_rejected(self):
        assert validate_image_url("") is False

    def test_ftp_rejected(self):
        assert validate_image_url("ftp://files.com/image.png") is False

    def test_data_url_rejected(self):
        assert validate_image_url("data:image/png;base64,abc") is False


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
        result = await analyze_image.ainvoke({
            "image_url": "http://evil.com/img.jpg",
            "question": "what is this",
        })
        assert "rejected" in result.lower() or "invalid" in result.lower()

    @pytest.mark.asyncio
    async def test_rejects_private_path(self):
        result = await analyze_image.ainvoke({
            "image_url": "/etc/shadow",
            "question": "what is this",
        })
        assert "rejected" in result.lower() or "invalid" in result.lower()

    @pytest.mark.asyncio
    async def test_handles_download_error(self):
        with patch("agents.tools.vision._load_image") as mock_load:
            mock_load.side_effect = Exception("Connection refused")

            result = await analyze_image.ainvoke({
                "image_url": "https://example.com/img.jpg",
                "question": "describe this",
            })
            assert "failed" in result.lower()
