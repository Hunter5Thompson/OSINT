"""Image analysis via vLLM Qwen3-VL-8B."""

from __future__ import annotations

import base64
import json
import os
import stat
from pathlib import Path

import httpx
import structlog

log = structlog.get_logger(__name__)

VISION_PROMPT = """\
Analyze this image from a geopolitical/military OSINT context.
Extract:
- scene_description: What is shown in the image
- visible_text: Any text, labels, watermarks visible
- military_equipment: Equipment types if identifiable (e.g., "T-72B3 tank", "HIMARS launcher")
- location_indicators: Any clues about location (signs, terrain, landmarks)
- map_annotations: If satellite/map image — marked areas, arrows, labels
- damage_assessment: If applicable — infrastructure damage, impact craters
Output as JSON."""


def _read_image_bounded(image_path: str, image_root: str, max_bytes: int) -> bytes:
    """Open a regular file under the trusted admin-configured root.

    Every image-path component below this deployment root is untrusted and
    opened using dir-fd traversal with symlink following disabled.
    """
    if max_bytes <= 0:
        raise ValueError("max_bytes must be positive")
    root = Path(image_root).resolve(strict=True)
    candidate = Path(image_path).absolute()
    try:
        relative = candidate.relative_to(root)
    except ValueError as exc:
        raise ValueError("image_path is outside configured image root") from exc
    if not relative.parts or any(part in {".", ".."} for part in relative.parts):
        raise ValueError("invalid image_path")
    directory_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for component in relative.parts[:-1]:
            next_fd = os.open(
                component,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                dir_fd=directory_fd,
            )
            os.close(directory_fd)
            directory_fd = next_fd
        file_fd = os.open(
            relative.parts[-1],
            os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
            dir_fd=directory_fd,
        )
        try:
            file_stat = os.fstat(file_fd)
            if not stat.S_ISREG(file_stat.st_mode):
                raise ValueError("image_path must refer to a regular file")
            if file_stat.st_size > max_bytes:
                raise ValueError(f"image exceeds maximum size of {max_bytes} bytes")
            chunks: list[bytes] = []
            remaining = max_bytes + 1
            while remaining:
                chunk = os.read(file_fd, min(65_536, remaining))
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            data = b"".join(chunks)
            if len(data) > max_bytes:
                raise ValueError(f"image exceeds maximum size of {max_bytes} bytes")
            return data
        finally:
            os.close(file_fd)
    finally:
        os.close(directory_fd)


async def analyze_image(
    *,
    client: httpx.AsyncClient,
    vllm_url: str,
    model: str,
    image_path: str,
    image_root: str = "/data/telegram/media",
    max_file_size_mb: int = 10,
) -> dict | None:
    """Analyze an image via vLLM vision model. Returns parsed JSON dict or None on failure."""
    try:
        image_data = _read_image_bounded(image_path, image_root, max_file_size_mb * 1024 * 1024)
        b64 = base64.b64encode(image_data).decode("utf-8")
    except (OSError, ValueError) as e:
        log.error("vision_image_read_failed", path=image_path, error=str(e))
        return None

    suffix = Path(image_path).suffix.lower()
    mime = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
    }.get(suffix, "image/jpeg")

    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": "You are an OSINT image analyst. Output valid JSON only.",
            },
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
                    {"type": "text", "text": VISION_PROMPT},
                ],
            },
        ],
        "temperature": 0.1,
        "max_tokens": 1500,
    }

    try:
        resp = await client.post(f"{vllm_url}/chat/completions", json=payload, timeout=60.0)
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"]
        return json.loads(content)
    except (httpx.HTTPError, json.JSONDecodeError, KeyError, IndexError) as e:
        log.error("vision_analysis_failed", path=image_path, error=str(e))
        return None
