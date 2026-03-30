"""analyze_image tool — Qwen3.5 multimodal vision via vLLM.

Security: URL validation, SSRF protection, size/dimension limits.
"""

from __future__ import annotations

import base64
import ipaddress
import socket
from io import BytesIO
from pathlib import Path
from urllib.parse import urlparse

import httpx
import structlog
from langchain_core.tools import tool
from PIL import Image

from config import settings

log = structlog.get_logger(__name__)


def validate_image_url(url: str) -> bool:
    """Check if URL is safe: https:// or whitelisted local path."""
    if not url:
        return False

    # Local file path
    if url.startswith("/"):
        return any(url.startswith(p) for p in settings.vision_allowed_local_paths)

    # Only HTTPS
    parsed = urlparse(url)
    return parsed.scheme == "https"


def _is_private_ip(ip_str: str) -> bool:
    """Check if an IP address is in a private/reserved range."""
    try:
        addr = ipaddress.ip_address(ip_str)
        return addr.is_private or addr.is_loopback or addr.is_reserved
    except ValueError:
        return False


async def _download_image(url: str) -> bytes:
    """Download image with SSRF protection and size limits."""
    parsed = urlparse(url)
    hostname = parsed.hostname or ""

    # Resolve hostname and check for private IPs
    try:
        resolved_ips = socket.getaddrinfo(hostname, None)
        for _, _, _, _, sockaddr in resolved_ips:
            ip = sockaddr[0]
            if _is_private_ip(ip):
                raise ValueError(f"URL resolves to private IP: {ip}")
    except socket.gaierror:
        raise ValueError(f"Cannot resolve hostname: {hostname}")

    max_size = settings.vision_max_file_size_mb * 1024 * 1024

    async with httpx.AsyncClient(
        timeout=settings.vision_download_timeout_s,
        follow_redirects=False,
    ) as client:
        # HEAD check for content type
        head_resp = await client.head(url)
        content_type = head_resp.headers.get("content-type", "")
        if not content_type.startswith("image/"):
            raise ValueError(f"Not an image: content-type={content_type}")

        content_length = int(head_resp.headers.get("content-length", 0))
        if content_length > max_size:
            raise ValueError(f"Image too large: {content_length} bytes (max {max_size})")

        # Download
        resp = await client.get(url)
        resp.raise_for_status()

        if len(resp.content) > max_size:
            raise ValueError(f"Image too large: {len(resp.content)} bytes")

        return resp.content


def _validate_dimensions(image_bytes: bytes) -> None:
    """Check image dimensions are within limits."""
    img = Image.open(BytesIO(image_bytes))
    w, h = img.size
    max_dim = settings.vision_max_dimension
    if w > max_dim or h > max_dim:
        raise ValueError(f"Image dimensions {w}x{h} exceed max {max_dim}x{max_dim}")


async def _load_image(url: str) -> str:
    """Load image from URL or local path and return base64 data URL."""
    if url.startswith("/"):
        # Local file
        path = Path(url)
        if not path.exists():
            raise FileNotFoundError(f"Image not found: {url}")
        image_bytes = path.read_bytes()
    else:
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
    image_url: str,
    question: str = "Describe this image in detail. Identify objects, text, locations, and any intelligence-relevant features.",
) -> str:
    """Analyze an image using Qwen3.5 multimodal vision.
    Use for satellite imagery, document photos, maps, or any visual content.

    Args:
        image_url: HTTPS URL or whitelisted local path to the image.
        question: Specific question about the image content.
    """
    if not validate_image_url(image_url):
        return (
            f"Image URL rejected: '{image_url}'. "
            "Only HTTPS URLs or whitelisted local paths are allowed."
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
