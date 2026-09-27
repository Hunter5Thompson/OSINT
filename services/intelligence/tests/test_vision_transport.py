"""S03 transport contract tests through the real httpcore connection pool."""

import asyncio
import base64
import socket
import ssl
import zlib
from collections.abc import Iterable
from io import BytesIO

import httpcore
import pytest
from PIL import Image

from agents.tools.vision_transport import download_image

URL = "https://images.example.test/assets/photo.png"


def _dns_rows(*addresses: str):
    rows = []
    for address in addresses:
        ip = __import__("ipaddress").ip_address(address)
        family = socket.AF_INET6 if ip.version == 6 else socket.AF_INET
        sockaddr = (address, 443, 0, 0) if ip.version == 6 else (address, 443)
        rows.append((family, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", sockaddr))
    return rows


class FakeNetworkStream:
    def __init__(self, wire: bytes, *, delay: float = 0.0):
        self.wire = wire
        self.delay = delay
        self.request = bytearray()
        self.server_hostname: str | None = None
        self.ssl_context: ssl.SSLContext | None = None
        self.closed = False

    async def read(self, max_bytes: int, timeout: float | None = None) -> bytes:
        if self.delay:
            await asyncio.sleep(self.delay)
        chunk, self.wire = self.wire[:max_bytes], self.wire[max_bytes:]
        return chunk

    async def write(self, buffer: bytes, timeout: float | None = None) -> None:
        self.request.extend(buffer)

    async def start_tls(
        self,
        ssl_context: ssl.SSLContext,
        server_hostname: str | None = None,
        timeout: float | None = None,
    ):
        self.ssl_context = ssl_context
        self.server_hostname = server_hostname
        return self

    async def aclose(self) -> None:
        self.closed = True

    def get_extra_info(self, info: str):
        if info == "ssl_object":
            return type("FakeSSLObject", (), {"selected_alpn_protocol": lambda _self: "http/1.1"})()
        return None


class FakeNetworkBackend:
    def __init__(self, wire: bytes, *, delay: float = 0.0, on_connect=None):
        self.wire = wire
        self.delay = delay
        self.on_connect = on_connect
        self.connects: list[tuple[str, int]] = []
        self.stream: FakeNetworkStream | None = None

    async def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
        if self.on_connect is not None:
            self.on_connect()
        self.connects.append((host, port))
        self.stream = FakeNetworkStream(self.wire, delay=self.delay)
        return self.stream

    async def connect_unix_socket(self, *args, **kwargs):  # pragma: no cover - forbidden path
        raise AssertionError("Unix sockets are not used")

    async def sleep(self, seconds):  # pragma: no cover - retries disabled
        raise AssertionError("transport retry attempted")


class Resolver:
    def __init__(self, rows, *, delay: float = 0.0):
        self.rows = rows
        self.delay = delay
        self.calls: list[tuple[str, int]] = []

    async def __call__(self, host: str, port: int):
        self.calls.append((host, port))
        if self.delay:
            await asyncio.sleep(self.delay)
        return self.rows


def _wire(body: bytes, *, status: int = 200, headers: Iterable[tuple[str, str]] = ()) -> bytes:
    fields = {"content-type": "image/png", "content-length": str(len(body))}
    fields.update({name.lower(): value for name, value in headers})
    header_bytes = b"".join(f"{name}: {value}\r\n".encode() for name, value in fields.items())
    return (
        f"HTTP/1.1 {status} Example\r\n".encode()
        + header_bytes
        + b"Connection: close\r\n\r\n"
        + body
    )


@pytest.mark.asyncio
async def test_real_httpcore_pool_pins_ip_and_preserves_tls_and_host():
    resolver = Resolver(_dns_rows("93.184.216.34"))
    backend = FakeNetworkBackend(_wire(b"png-data"))

    result = await download_image(
        URL, max_bytes=1024, timeout_s=1, resolver=resolver, network_backend=backend
    )

    assert result == b"png-data"
    assert resolver.calls == [("images.example.test", 443)]
    assert backend.connects == [("93.184.216.34", 443)]
    assert backend.stream is not None
    assert backend.stream.server_hostname == "images.example.test"
    assert backend.stream.ssl_context is not None
    assert backend.stream.ssl_context.verify_mode == ssl.CERT_REQUIRED
    assert backend.stream.ssl_context.check_hostname is True
    assert b"Host: images.example.test" in backend.stream.request
    assert b"sni_hostname" not in backend.stream.request


@pytest.mark.asyncio
async def test_real_anyio_backend_treats_pinned_numeric_address_as_literal(monkeypatch):
    import anyio._core._sockets as anyio_sockets
    from httpcore import AnyIOBackend

    from agents.tools.vision_transport import _PinnedNetworkBackend

    calls = []
    marker_stream = object()

    class FakeAsyncBackend:
        async def connect_tcp(self, remote_host, remote_port, local_address):
            calls.append((remote_host, remote_port))
            return marker_stream

    def no_dns(*_args, **_kwargs):
        raise AssertionError("numeric pinned address triggered another DNS lookup")

    monkeypatch.setattr(anyio_sockets, "get_async_backend", lambda: FakeAsyncBackend())
    monkeypatch.setattr(anyio_sockets, "getaddrinfo", no_dns)
    pinned = _PinnedNetworkBackend("images.example.test", "93.184.216.34", AnyIOBackend())
    stream = await pinned.connect_tcp("images.example.test", 443, timeout=1)
    assert calls == [("93.184.216.34", 443)]
    assert stream is not None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "addresses",
    [
        ("127.0.0.1",),
        ("10.0.0.4",),
        ("169.254.1.2",),
        ("100.64.0.1",),
        ("0.0.0.0",),
        ("224.0.0.1",),
        ("240.0.0.1",),
        ("::",),
        ("::1",),
        ("fe80::1",),
        ("ff02::1",),
        ("4000::1",),
        ("::ffff:8.8.8.8",),
        ("64:ff9b::a00:1",),
        ("93.184.216.34", "192.168.0.1"),
    ],
)
async def test_forbidden_or_mixed_dns_answer_never_connects(addresses):
    resolver = Resolver(_dns_rows(*addresses))
    backend = FakeNetworkBackend(_wire(b"x"))
    with pytest.raises(ValueError):
        await download_image(
            URL, max_bytes=1024, timeout_s=1, resolver=resolver, network_backend=backend
        )
    assert resolver.calls == [("images.example.test", 443)]
    assert backend.connects == []


@pytest.mark.asyncio
async def test_resolver_answer_change_does_not_trigger_second_lookup_or_repin():
    resolver = Resolver(_dns_rows("93.184.216.34"))
    backend = FakeNetworkBackend(
        _wire(b"ok"), on_connect=lambda: setattr(resolver, "rows", _dns_rows("127.0.0.1"))
    )
    await download_image(
        URL, max_bytes=1024, timeout_s=1, resolver=resolver, network_backend=backend
    )
    assert resolver.calls == [("images.example.test", 443)]
    assert resolver.rows == _dns_rows("127.0.0.1")
    assert backend.connects == [("93.184.216.34", 443)]


@pytest.mark.asyncio
async def test_empty_dns_answer_fails_before_connect():
    backend = FakeNetworkBackend(_wire(b"ok"))
    with pytest.raises(ValueError, match="no addresses"):
        await download_image(
            URL, max_bytes=1024, timeout_s=1, resolver=Resolver([]), network_backend=backend
        )
    assert backend.connects == []


@pytest.mark.asyncio
async def test_invalid_zero_port_is_rejected_before_dns():
    resolver = Resolver(_dns_rows("93.184.216.34"))
    backend = FakeNetworkBackend(_wire(b"ok"))
    with pytest.raises(ValueError, match="port"):
        await download_image(
            "https://images.example.test:0/photo.png",
            max_bytes=1024,
            timeout_s=1,
            resolver=resolver,
            network_backend=backend,
        )
    assert resolver.calls == []
    assert backend.connects == []


@pytest.mark.asyncio
async def test_public_ipv6_answer_connects_to_canonical_literal():
    backend = FakeNetworkBackend(_wire(b"ok"))
    result = await download_image(
        URL,
        max_bytes=1024,
        timeout_s=1,
        resolver=Resolver(_dns_rows("2606:4700:4700::1111")),
        network_backend=backend,
    )
    assert result == b"ok"
    assert backend.connects == [("2606:4700:4700::1111", 443)]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("wire", "limit", "message"),
    [
        (
            _wire(b"body", status=302, headers=(("Location", "http://127.0.0.1/"),)),
            1024,
            "redirect",
        ),
        (_wire(b"body", headers=(("Content-Type", "text/html"),)), 1024, "content type"),
        (_wire(b"body", headers=(("Content-Type", "image/"),)), 1024, "content type"),
        (_wire(b"12345"), 4, "size"),
        (_wire(b"body", headers=(("Content-Length", "invalid"),)), 1024, "Content-Length"),
    ],
)
async def test_response_policy_rejects_redirect_type_invalid_length_and_oversize(
    wire, limit, message
):
    backend = FakeNetworkBackend(wire)
    expected_error = (ValueError, httpcore.RemoteProtocolError)
    with pytest.raises(expected_error, match=message):
        await download_image(
            URL,
            max_bytes=limit,
            timeout_s=1,
            resolver=Resolver(_dns_rows("93.184.216.34")),
            network_backend=backend,
        )


@pytest.mark.asyncio
async def test_missing_content_length_is_stream_bounded_and_accepted():
    wire = b"HTTP/1.1 200 OK\r\nContent-Type: image/png\r\nConnection: close\r\n\r\nabc"
    result = await download_image(
        URL,
        max_bytes=3,
        timeout_s=1,
        resolver=Resolver(_dns_rows("93.184.216.34")),
        network_backend=FakeNetworkBackend(wire),
    )
    assert result == b"abc"


@pytest.mark.asyncio
async def test_chunked_body_overflow_is_bounded():
    body = b"5\r\n12345\r\n0\r\n\r\n"
    wire = (
        b"HTTP/1.1 200 OK\r\nContent-Type: image/png\r\n"
        b"Transfer-Encoding: chunked\r\nConnection: close\r\n\r\n"
        + body
    )
    with pytest.raises(ValueError, match="size"):
        await download_image(
            URL,
            max_bytes=4,
            timeout_s=1,
            resolver=Resolver(_dns_rows("93.184.216.34")),
            network_backend=FakeNetworkBackend(wire),
        )


@pytest.mark.asyncio
async def test_compressed_decoded_overflow_and_unknown_encoding_are_rejected():
    compressed = zlib.compressobj(wbits=31)
    encoded = compressed.compress(b"x" * 1000) + compressed.flush()
    compressed_wire = _wire(encoded, headers=(("Content-Encoding", "gzip"),))
    for wire, error in (
        (compressed_wire, "decoded"),
        (_wire(b"x", headers=(("Content-Encoding", "br"),)), "encoding"),
    ):
        with pytest.raises(ValueError, match=error):
            await download_image(
                URL,
                max_bytes=100,
                timeout_s=1,
                resolver=Resolver(_dns_rows("93.184.216.34")),
                network_backend=FakeNetworkBackend(wire),
            )


@pytest.mark.asyncio
@pytest.mark.parametrize("encoding", ["gzip", "deflate"])
async def test_gzip_and_deflate_are_bounded_and_successfully_decoded(encoding):
    source = b"image-content" * 8
    if encoding == "gzip":
        compressor = zlib.compressobj(wbits=16 + zlib.MAX_WBITS)
    else:
        compressor = zlib.compressobj(wbits=zlib.MAX_WBITS)
    compressed = compressor.compress(source) + compressor.flush()
    result = await download_image(
        URL,
        max_bytes=1024,
        timeout_s=1,
        resolver=Resolver(_dns_rows("93.184.216.34")),
        network_backend=FakeNetworkBackend(
            _wire(compressed, headers=(("Content-Encoding", encoding),))
        ),
    )
    assert result == source


@pytest.mark.asyncio
@pytest.mark.parametrize("suffix", ["truncated", "trailing"])
async def test_malformed_compressed_body_is_rejected(suffix):
    compressor = zlib.compressobj(wbits=16 + zlib.MAX_WBITS)
    compressed = compressor.compress(b"payload") + compressor.flush()
    malformed = compressed[:-4] if suffix == "truncated" else compressed + b"junk"
    wire = _wire(malformed, headers=(("Content-Encoding", "gzip"),))
    with pytest.raises(ValueError, match="compressed image"):
        await download_image(
            URL,
            max_bytes=1024,
            timeout_s=1,
            resolver=Resolver(_dns_rows("93.184.216.34")),
            network_backend=FakeNetworkBackend(wire),
        )


@pytest.mark.asyncio
async def test_environment_proxy_is_ignored(monkeypatch):
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:9")
    monkeypatch.setenv("ALL_PROXY", "http://127.0.0.1:9")
    backend = FakeNetworkBackend(_wire(b"ok"))
    result = await download_image(
        URL,
        max_bytes=1024,
        timeout_s=1,
        resolver=Resolver(_dns_rows("93.184.216.34")),
        network_backend=backend,
    )
    assert result == b"ok"
    assert backend.connects == [("93.184.216.34", 443)]


def _png_bytes(size=(2, 2)) -> bytes:
    image = Image.new("RGB", size, color=(20, 30, 40))
    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


@pytest.mark.asyncio
async def test_load_image_uses_pinned_pool_and_fully_decodes_image(monkeypatch):
    from agents.tools import vision, vision_transport

    image_bytes = _png_bytes()
    backend = FakeNetworkBackend(_wire(image_bytes))

    async def resolve(host, port):
        return _dns_rows("93.184.216.34")

    monkeypatch.setattr(vision_transport, "_resolve", resolve)
    monkeypatch.setattr(vision_transport.httpcore, "AnyIOBackend", lambda: backend)
    result = await vision._load_image(URL)
    assert result == f"data:image/png;base64,{base64.b64encode(image_bytes).decode()}"
    assert backend.connects == [("93.184.216.34", 443)]


@pytest.mark.asyncio
async def test_load_image_rejects_truncated_image_and_dimension_excess(monkeypatch):
    from agents.tools import vision, vision_transport

    image_bytes = _png_bytes()

    async def resolve(host, port):
        return _dns_rows("93.184.216.34")

    monkeypatch.setattr(vision_transport, "_resolve", resolve)
    monkeypatch.setattr(
        vision_transport.httpcore,
        "AnyIOBackend",
        lambda: FakeNetworkBackend(_wire(image_bytes[:-24])),
    )
    with pytest.raises(OSError):
        await vision._load_image(URL)

    monkeypatch.setattr(
        vision_transport.httpcore, "AnyIOBackend", lambda: FakeNetworkBackend(_wire(image_bytes))
    )
    monkeypatch.setattr(vision.settings, "vision_max_dimension", 1)
    with pytest.raises(ValueError, match="dimensions"):
        await vision._load_image(URL)


@pytest.mark.asyncio
async def test_total_deadline_includes_dns_and_body_streaming():
    slow_dns = Resolver(_dns_rows("93.184.216.34"), delay=0.1)
    with pytest.raises(TimeoutError):
        await download_image(
            URL,
            max_bytes=1024,
            timeout_s=0.01,
            resolver=slow_dns,
            network_backend=FakeNetworkBackend(_wire(b"ok")),
        )

    slow_body = FakeNetworkBackend(_wire(b"ok"), delay=0.1)
    with pytest.raises(TimeoutError):
        await download_image(
            URL,
            max_bytes=1024,
            timeout_s=0.01,
            resolver=Resolver(_dns_rows("93.184.216.34")),
            network_backend=slow_body,
        )
