"""analyze_image tool — Qwen3.5 multimodal vision via vLLM.

Security: URL validation, SSRF protection, size/dimension limits.
"""

from __future__ import annotations

import base64
from io import BytesIO
from urllib.parse import urlparse

import structlog
from langchain_core.tools import tool
from langgraph.prebuilt import ToolRuntime
from PIL import Image

from agents.tools.capabilities import tool_allowed_for_state
from agents.tools.vision_transport import download_image, is_global_unicast
from config import settings
from graph.state import AgentState

log = structlog.get_logger(__name__)


def validate_image_url(url: str) -> bool:
    """Accept only absolute HTTPS URLs without embedded credentials."""
    if not url:
        return False
    try:
        parsed = urlparse(url)
        _port = parsed.port
    except ValueError:
        return False
    return (
        parsed.scheme == "https"
        and bool(parsed.hostname)
        and parsed.username is None
        and parsed.password is None
    )


def _is_private_ip(ip_str: str) -> bool:
    """Return true unless the address is validated global unicast."""
    return not is_global_unicast(ip_str)


async def _download_image(url: str) -> bytes:
    """Download image with SSRF protection and size limits."""
    return await download_image(
        url,
        max_bytes=settings.vision_max_file_size_mb * 1024 * 1024,
        timeout_s=settings.vision_download_timeout_s,
    )


def _validate_dimensions(image_bytes: bytes) -> None:
    """Check image dimensions are within limits."""
    with Image.open(BytesIO(image_bytes)) as img:
        w, h = img.size
        max_dim = settings.vision_max_dimension
        if w > max_dim or h > max_dim:
            raise ValueError(f"Image dimensions {w}x{h} exceed max {max_dim}x{max_dim}")
        img.load()


async def _load_image(url: str) -> str:
    """Load image from an HTTPS URL and return base64 data URL."""
    if not validate_image_url(url):
        raise ValueError("image_url must be an absolute HTTPS URL without credentials")
    image_bytes = await _download_image(url)

    max_size = settings.vision_max_file_size_mb * 1024 * 1024
    if len(image_bytes) > max_size:
        raise ValueError(f"Image too large: {len(image_bytes)} bytes")

    _validate_dimensions(image_bytes)

    b64 = base64.b64encode(image_bytes).decode()
    # Detect format from bytes
    if image_bytes[:8] == b'\x89PNG\r\n\x1a\n':
        mime = "image/png"
    elif image_bytes[:2] == b'\xff\xd8':
        mime = "image/jpeg"
    else:
        mime = "image/png"  # default

    return f"data:{mime};base64,{b64}"


@tool
async def analyze_image(
    question: str,
    runtime: ToolRuntime[dict[str, object], AgentState],
) -> str:
    """Analyze an image using Qwen3.5 multimodal vision.
    Use for satellite imagery, document photos, maps, or any visual content.

    Args:
        question: Specific question about the image content.
    """
    if not tool_allowed_for_state("analyze_image", runtime.state):
        return "SPATIAL_SCOPE_UNSUPPORTED: analyze_image requires an attached image"

    image_url = runtime.state.get("image_url")
    if not isinstance(image_url, str) or not image_url:
        return "SPATIAL_SCOPE_UNSUPPORTED: analyze_image requires an attached image"
    if not validate_image_url(image_url):
        return (
            f"Image URL rejected: '{image_url}'. "
            "Only absolute HTTPS URLs without credentials are allowed."
        )

    try:
        data_url = await _load_image(image_url)
    except Exception as e:
        log.warning("vision_image_load_failed", url=image_url[:200], error=str(e))
        return f"Failed to load image: {e}"

    try:
        from openai import AsyncOpenAI

        client = AsyncOpenAI(
            base_url=settings.llm_base_url,
            api_key="not-needed",
        )

        response = await client.chat.completions.create(
            model=settings.llm_model,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": data_url}},
                    {"type": "text", "text": question},
                ],
            }],
            max_tokens=1000,
            temperature=0.2,
        )

        return response.choices[0].message.content or "No analysis returned."

    except Exception as e:
        log.warning("vision_analysis_failed", url=image_url[:200], error=str(e))
        return f"Image analysis failed: {e}"
