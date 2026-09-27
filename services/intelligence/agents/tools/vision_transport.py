"""SSRF-resistant HTTPS image download using httpcore's public backend seam."""

from __future__ import annotations

import asyncio
import ipaddress
import socket
import ssl
import zlib
from collections.abc import Awaitable, Callable, Sequence
from typing import Any
from urllib.parse import urlparse

import httpcore

Resolver = Callable[[str, int], Awaitable[Sequence[tuple[Any, ...]]]]


def is_global_unicast(ip_str: str) -> bool:
    """Accept only public global-unicast addresses, never special-use space."""
    try:
        address = ipaddress.ip_address(ip_str)
    except ValueError:
        return False
    return (
        address.is_global
        and not address.is_private
        and not address.is_loopback
        and not address.is_link_local
        and not address.is_unspecified
        and not address.is_multicast
        and not address.is_reserved
        and not (
            isinstance(address, ipaddress.IPv6Address)
            and address.ipv4_mapped is not None
        )
    )


async def _resolve(host: str, port: int) -> Sequence[tuple[Any, ...]]:
    loop = asyncio.get_running_loop()
    return await loop.getaddrinfo(host, port, family=socket.AF_UNSPEC, type=socket.SOCK_STREAM)


def _validated_addresses(records: Sequence[tuple[Any, ...]]) -> list[str]:
    if not records:
        raise ValueError("image host resolved to no addresses")
    addresses: list[str] = []
    for record in records:
        try:
            raw_address = record[4][0]
            if "%" in raw_address:
                raise ValueError("scoped address")
            address = ipaddress.ip_address(raw_address)
        except (IndexError, TypeError, ValueError) as exc:
            raise ValueError("image host returned an invalid address") from exc
        if not is_global_unicast(raw_address):
            raise ValueError(f"image host resolved to a non-global address: {address}")
        normalized = address.compressed
        if normalized not in addresses:
            addresses.append(normalized)
    return addresses


class _PinnedNetworkBackend(httpcore.AsyncNetworkBackend):
    """Delegate TCP to a fixed IP while httpcore retains the origin hostname for TLS."""

    def __init__(self, origin_host: str, address: str, backend: httpcore.AsyncNetworkBackend):
        self._origin_host = origin_host
        self._address = address
        self._backend = backend

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options=None,
    ) -> httpcore.AsyncNetworkStream:
        if host.lower() != self._origin_host.lower():
            raise httpcore.ConnectError("unexpected HTTP origin host")
        return await self._backend.connect_tcp(
            self._address,
            port,
            timeout=timeout,
            local_address=local_address,
            socket_options=socket_options,
        )

    async def connect_unix_socket(self, *args, **kwargs) -> httpcore.AsyncNetworkStream:
        raise httpcore.ConnectError("Unix sockets are disabled for remote image downloads")

    async def sleep(self, seconds: float) -> None:
        await self._backend.sleep(seconds)


def _response_header_values(response: httpcore.Response, name: bytes) -> list[bytes]:
    return [value for key, value in response.headers if key.lower() == name]


def _single_header(response: httpcore.Response, name: bytes) -> bytes | None:
    values = _response_header_values(response, name)
    if len(values) > 1:
        raise ValueError(f"multiple {name.decode()} headers are not accepted")
    return values[0] if values else None


def _decoder_for(content_encoding: bytes | None):
    if content_encoding is None or content_encoding.lower().strip() in (b"", b"identity"):
        return None
    encoding = content_encoding.lower().strip()
    if encoding == b"gzip":
        return zlib.decompressobj(16 + zlib.MAX_WBITS)
    if encoding == b"deflate":
        return zlib.decompressobj(zlib.MAX_WBITS)
    raise ValueError(f"unsupported content encoding: {encoding.decode('latin-1')}")


def _append_decoded(output: bytearray, decoder, chunk: bytes, max_bytes: int) -> None:
    pending = chunk
    while pending:
        remaining = max_bytes - len(output)
        decoded = decoder.decompress(pending, remaining + 1)
        output.extend(decoded)
        if len(output) > max_bytes:
            raise ValueError("decoded image exceeds maximum size")
        pending = decoder.unconsumed_tail
        if pending and not decoded:
            raise ValueError("compressed image exceeds maximum size")


async def download_image(
    url: str,
    *,
    max_bytes: int,
    timeout_s: float,
    resolver: Resolver | None = None,
    network_backend: httpcore.AsyncNetworkBackend | None = None,
) -> bytes:
    """Fetch one bounded image over HTTPS, pinning TCP to validated DNS output.

    Resolver and backend injection are internal test seams. Production defaults
    use event-loop DNS and AnyIO's socket backend.
    """
    if max_bytes <= 0 or timeout_s <= 0:
        raise ValueError("image byte limit and timeout must be positive")
    parsed = urlparse(url)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise ValueError("image_url must be an absolute HTTPS URL without credentials")
    try:
        port = parsed.port if parsed.port is not None else 443
    except ValueError as exc:
        raise ValueError("image_url has an invalid port") from exc
    if not 1 <= port <= 65535:
        raise ValueError("image_url has an invalid port")
    host = parsed.hostname
    dns_resolver = resolver if resolver is not None else _resolve
    base_backend = network_backend if network_backend is not None else httpcore.AnyIOBackend()

    async with asyncio.timeout(timeout_s):
        try:
            records = await dns_resolver(host, port)
        except (OSError, socket.gaierror) as exc:
            raise ValueError(f"cannot resolve image host: {host}") from exc
        addresses = _validated_addresses(records)

        ssl_context = ssl.create_default_context(ssl.Purpose.SERVER_AUTH)
        ssl_context.verify_mode = ssl.CERT_REQUIRED
        ssl_context.check_hostname = True
        backend = _PinnedNetworkBackend(host, addresses[0], base_backend)
        timeout_extensions = {
            "connect": timeout_s,
            "read": timeout_s,
            "write": timeout_s,
            "pool": timeout_s,
        }
        output = bytearray()
        encoded_size = 0

        async with (
            httpcore.AsyncConnectionPool(
                ssl_context=ssl_context,
                proxy=None,
                retries=0,
                max_connections=1,
                max_keepalive_connections=0,
                network_backend=backend,
            ) as pool,
            pool.stream(
                "GET",
                url,
                headers={
                    "Accept": "image/*",
                    "Accept-Encoding": "gzip, deflate",
                    "Connection": "close",
                },
                extensions={"timeout": timeout_extensions},
            ) as response,
        ):
            if response.status != 200:
                if 300 <= response.status < 400:
                    raise ValueError("image server redirects are disabled")
                raise ValueError(f"image server returned HTTP {response.status}")
            content_type = _single_header(response, b"content-type")
            if content_type is None:
                raise ValueError("image response is missing content type")
            media_type = content_type.split(b";", 1)[0].strip().lower()
            if not media_type.startswith(b"image/") or media_type == b"image/":
                raise ValueError("image response has invalid content type")

            content_length = _single_header(response, b"content-length")
            if content_length is not None:
                try:
                    declared_size = int(content_length)
                except ValueError as exc:
                    raise ValueError("image response has invalid content length") from exc
                if declared_size < 0:
                    raise ValueError("image response has invalid content length")
                if declared_size > max_bytes:
                    raise ValueError("encoded image exceeds maximum size")

            decoder = _decoder_for(_single_header(response, b"content-encoding"))
            async for chunk in response.stream:
                encoded_size += len(chunk)
                if encoded_size > max_bytes:
                    raise ValueError("encoded image exceeds maximum size")
                if decoder is None:
                    output.extend(chunk)
                    if len(output) > max_bytes:
                        raise ValueError("decoded image exceeds maximum size")
                else:
                    _append_decoded(output, decoder, chunk, max_bytes)
            if content_length is not None and encoded_size != declared_size:
                raise ValueError("image response content length does not match body")
            if decoder is not None and (not decoder.eof or decoder.unused_data):
                raise ValueError("compressed image is truncated or has trailing data")
    return bytes(output)
