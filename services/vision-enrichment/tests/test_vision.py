"""Tests for vision image analysis via vLLM."""

import json
import os
import tempfile
from unittest.mock import AsyncMock

import httpx

from vision import analyze_image

_DUMMY_REQUEST = httpx.Request("POST", "http://localhost:8011/v1/chat/completions")


class TestAnalyzeImage:
    async def test_returns_parsed_json(self):
        vision_result = {
            "scene_description": "Military convoy on highway",
            "visible_text": "Z marking on vehicle",
            "military_equipment": ["T-72B3 tank", "BMP-2"],
            "location_indicators": ["Road sign in Cyrillic"],
            "map_annotations": [],
            "damage_assessment": "No visible damage",
        }
        mock_response = httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"content": json.dumps(vision_result)}}
                ]
            },
            request=_DUMMY_REQUEST,
        )
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.post.return_value = mock_response

        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
            f.write(b"\xff\xd8\xff\xe0" + b"\x00" * 100)
            tmp_path = f.name

        try:
            result = await analyze_image(
                client=mock_client,
                vllm_url="http://localhost:8011/v1",
                model="qwen-vl",
                image_path=tmp_path,
            )

            assert result["scene_description"] == "Military convoy on highway"
            assert "T-72B3 tank" in result["military_equipment"]
            mock_client.post.assert_called_once()
        finally:
            os.unlink(tmp_path)

    async def test_returns_none_on_error(self):
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.post.side_effect = httpx.HTTPStatusError(
            "500", request=_DUMMY_REQUEST, response=httpx.Response(500, request=_DUMMY_REQUEST)
        )

        result = await analyze_image(
            client=mock_client,
            vllm_url="http://localhost:8011/v1",
            model="qwen-vl",
            image_path="/data/photo.jpg",
        )
        assert result is None

    async def test_sends_base64_image(self):
        """Verify the image is sent as base64 in the request payload."""
        mock_response = httpx.Response(
            200,
            json={"choices": [{"message": {"content": "{}"}}]},
            request=_DUMMY_REQUEST,
        )
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.post.return_value = mock_response

        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
            f.write(b"\xff\xd8\xff\xe0" + b"\x00" * 100)
            tmp_path = f.name

        try:
            await analyze_image(
                client=mock_client,
                vllm_url="http://localhost:8011/v1",
                model="qwen-vl",
                image_path=tmp_path,
            )

            call_args = mock_client.post.call_args
            payload = call_args.kwargs.get("json") or call_args[1].get("json")
            messages = payload["messages"]
            user_msg = messages[1]
            assert any(
                c.get("type") == "image_url"
                for c in user_msg["content"]
                if isinstance(c, dict)
            )
        finally:
            os.unlink(tmp_path)

    async def test_returns_none_on_file_not_found(self):
        mock_client = AsyncMock(spec=httpx.AsyncClient)

        result = await analyze_image(
            client=mock_client,
            vllm_url="http://localhost:8011/v1",
            model="qwen-vl",
            image_path="/nonexistent/path/photo.jpg",
        )
        assert result is None
        mock_client.post.assert_not_called()
