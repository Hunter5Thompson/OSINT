"""Image analysis via vLLM Qwen3-VL-8B."""

from __future__ import annotations

import base64
import json
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


async def analyze_image(
    *,
    client: httpx.AsyncClient,
    vllm_url: str,
    model: str,
    image_path: str,
) -> dict | None:
    """Analyze an image via vLLM vision model. Returns parsed JSON dict or None on failure."""
    try:
        image_data = Path(image_path).read_bytes()
        b64 = base64.b64encode(image_data).decode("utf-8")
    except (FileNotFoundError, PermissionError) as e:
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
            {"role": "system", "content": "You are an OSINT image analyst. Output valid JSON only."},
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
