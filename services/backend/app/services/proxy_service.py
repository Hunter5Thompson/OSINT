"""HTTP proxy service for external API calls."""

from typing import Any

import httpx
import structlog

logger = structlog.get_logger()


class ProxyService:
    def __init__(self) -> None:
        self._client: httpx.AsyncClient | None = None

    async def start(self) -> None:
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(30.0, connect=10.0),
            follow_redirects=True,
            limits=httpx.Limits(max_connections=50, max_keepalive_connections=20),
        )
        logger.info("proxy_service_started")

    async def stop(self) -> None:
        if self._client:
            await self._client.aclose()

    @property
    def client(self) -> httpx.AsyncClient:
        if not self._client:
            raise RuntimeError("ProxyService not started")
        return self._client

    async def get_json(
        self,
        url: str,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        auth: tuple[str, str] | None = None,
    ) -> Any:
        try:
            resp = await self.client.get(url, params=params, headers=headers, auth=auth)
            resp.raise_for_status()
            return resp.json()
        except httpx.TimeoutException:
            logger.error("upstream_timeout", url=url)
            raise
        except httpx.HTTPStatusError as e:
            logger.error("upstream_error", url=url, status=e.response.status_code)
            raise
        except Exception:
            logger.error("proxy_request_failed", url=url)
            raise

    async def get_text(
        self,
        url: str,
        params: dict[str, Any] | None = None,
    ) -> str:
        try:
            resp = await self.client.get(url, params=params)
            resp.raise_for_status()
            return resp.text
        except Exception:
            logger.error("proxy_text_request_failed", url=url)
            raise
