# HN-S03 Remote image transport design

## Transport

Use `httpcore.AsyncConnectionPool` with a small `AsyncNetworkBackend` wrapper.
Resolve the original URL host asynchronously with `loop.getaddrinfo`, inspect
every A/AAAA result, and fail closed if any answer is not global unicast or is
IPv4-mapped IPv6. Give `AnyIOBackend.connect_tcp` only one validated numeric IP
for the URL's original port. Keep the request URL and Host untouched so
httpcore's TLS upgrade uses the original origin hostname as SNI and certificate
verification name. Do not accept or set the request `sni_hostname` extension.

httpcore documents the supported backend seam and async pool:
[Network Backends](https://www.encode.io/httpcore/network-backends/). The pool
is per download, has retries disabled, has no proxy configured, and receives a
`CERT_REQUIRED`/hostname-checking SSL context. Redirects are rejected. A single
overall deadline encloses DNS, connect, response headers, and body streaming.

## Response bounds

Do not use HEAD as a security check. Require an image media type from the GET
response. Enforce the encoded-byte budget while reading the HTTP body and also
check a valid `Content-Length` when present. Decode only supported gzip/deflate
content encodings with zlib's bounded `max_length`, enforcing the decoded-byte
budget as output is produced. Reject unknown encodings and malformed/truncated
compressed streams. Fully decode with Pillow and enforce pixel dimensions
before returning image bytes.

## Security boundary

This prevents connections to non-global and mixed DNS answers, and pins the TCP
connection to an address validated for the request. It preserves TLS hostname
verification and the HTTP Host header. It does not establish trust in arbitrary
public image hosts or replace host-level outbound firewall policy. The fake
stream integration tests assert that httpcore passes the original SNI and that
the configured SSL context requires verification; they do not claim to perform
a real certificate handshake.

## Regression matrix

- Public-only A/AAAA set connects to a validated numeric address; original Host
  and TLS server name remain the URL hostname; resolver is called once.
- Private, loopback, link-local, reserved, multicast, unspecified, CGNAT,
  IPv4-mapped IPv6, empty and mixed public/private answers fail before connect.
- DNS answer changes after validation do not change the pinned connection
  target. No second hostname lookup, environment proxy, retry, or redirect is
  allowed.
- 302, non-image content type, invalid present length, absent length (stream
  limit must still hold), chunked and
  compressed bodies, encoded/decoded overflow, malformed compression, and slow
  DNS/body exercise the error and byte/deadline bounds.
- Valid image bytes pass through the HTTP-core pool and Pillow full decode;
  invalid/truncated images and dimension/pixel excess fail closed.

All network tests use the real httpcore pool and a fake `AsyncNetworkStream`;
they do not open sockets to internal or public hosts.
