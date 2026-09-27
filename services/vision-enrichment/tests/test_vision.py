"""Tests for vision image analysis via vLLM."""

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest

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
            json={"choices": [{"message": {"content": json.dumps(vision_result)}}]},
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
                image_root=str(Path(tmp_path).parent),
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
                image_root=str(Path(tmp_path).parent),
            )

            call_args = mock_client.post.call_args
            payload = call_args.kwargs.get("json") or call_args[1].get("json")
            messages = payload["messages"]
            user_msg = messages[1]
            assert any(
                c.get("type") == "image_url" for c in user_msg["content"] if isinstance(c, dict)
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

    async def test_rejects_file_outside_root_before_llm(self, tmp_path):
        root = tmp_path / "root"
        root.mkdir()
        image = tmp_path / "outside.jpg"
        image.write_bytes(b"abc")
        client = AsyncMock(spec=httpx.AsyncClient)
        result = await analyze_image(
            client=client,
            vllm_url="http://unused",
            model="qwen",
            image_path=str(image),
            image_root=str(root),
        )
        assert result is None
        client.post.assert_not_called()

    async def test_rejects_parent_symlink_and_non_regular_files(self, tmp_path):
        from vision import _read_image_bounded

        root = tmp_path / "root"
        outside = tmp_path / "outside"
        root.mkdir()
        outside.mkdir()
        (outside / "secret.jpg").write_bytes(b"secret")
        (root / "link").symlink_to(outside, target_is_directory=True)
        with pytest.raises(OSError):
            _read_image_bounded(str(root / "link" / "secret.jpg"), str(root), 100)
        with pytest.raises(ValueError):
            _read_image_bounded(str(root), str(root), 100)
        (root / "leaf-link").symlink_to(outside / "secret.jpg")
        with pytest.raises(OSError):
            _read_image_bounded(str(root / "leaf-link"), str(root), 100)

    async def test_rejects_parent_traversal_and_similar_neighbor(self, tmp_path):
        from vision import _read_image_bounded

        root = tmp_path / "media"
        neighbor = tmp_path / "media-private"
        root.mkdir()
        neighbor.mkdir()
        (neighbor / "secret.jpg").write_bytes(b"secret")
        for candidate in (neighbor / "secret.jpg", root / ".." / "media-private" / "secret.jpg"):
            with pytest.raises(ValueError, match="outside|invalid"):
                _read_image_bounded(str(candidate), str(root), 100)

    async def test_fifo_is_nonregular_and_does_not_block(self, tmp_path):
        import os

        from vision import _read_image_bounded

        root = tmp_path / "root"
        root.mkdir()
        fifo = root / "pipe"
        os.mkfifo(fifo)
        with pytest.raises(ValueError, match="regular file"):
            _read_image_bounded(str(fifo), str(root), 100)

    async def test_rejects_oversized_file_using_bounded_read(self, tmp_path):
        from vision import _read_image_bounded

        root = tmp_path / "root"
        root.mkdir()
        image = root / "large.jpg"
        image.write_bytes(b"x" * 20)
        with pytest.raises(ValueError, match="maximum size"):
            _read_image_bounded(str(image), str(root), 10)

    async def test_known_oversize_is_rejected_before_read(self, tmp_path, monkeypatch):
        import vision

        root = tmp_path / "root"
        root.mkdir()
        image = root / "large.jpg"
        image.write_bytes(b"x" * 20)
        monkeypatch.setattr(
            vision.os, "read", lambda *_: (_ for _ in ()).throw(AssertionError("read called"))
        )
        with pytest.raises(ValueError, match="maximum size"):
            vision._read_image_bounded(str(image), str(root), 10)

    async def test_file_growth_after_stat_still_hits_read_limit(self, tmp_path, monkeypatch):
        import vision

        root = tmp_path / "root"
        root.mkdir()
        image = root / "growing.jpg"
        image.write_bytes(b"12345")
        real_read = vision.os.read
        first = True

        def grow_then_read(fd, count):
            nonlocal first
            if first:
                first = False
                with image.open("ab") as writer:
                    writer.write(b"67890")
            return real_read(fd, count)

        monkeypatch.setattr(vision.os, "read", grow_then_read)
        with pytest.raises(ValueError, match="maximum size"):
            vision._read_image_bounded(str(image), str(root), 8)

    async def test_component_swapped_for_symlink_before_open_is_rejected(
        self, tmp_path, monkeypatch
    ):
        import vision

        root = tmp_path / "root"
        child = root / "child"
        outside = tmp_path / "outside"
        root.mkdir()
        child.mkdir()
        outside.mkdir()
        (child / "image.jpg").write_bytes(b"inside")
        (outside / "image.jpg").write_bytes(b"outside")
        real_open = vision.os.open
        swapped = False

        def swap_then_open(path, flags, *args, **kwargs):
            nonlocal swapped
            if path == "child" and not swapped:
                swapped = True
                (root / "child").rename(root / "moved")
                (root / "child").symlink_to(outside, target_is_directory=True)
            return real_open(path, flags, *args, **kwargs)

        monkeypatch.setattr(vision.os, "open", swap_then_open)
        with pytest.raises(OSError):
            vision._read_image_bounded(str(child / "image.jpg"), str(root), 100)
