from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.static.cached_static import CachedStaticFiles


def _build_app(tmp_path: Path) -> FastAPI:
    (tmp_path / "hello.bin").write_bytes(b"abcdefghijklmnop")
    app = FastAPI()
    app.mount("/s", CachedStaticFiles(directory=str(tmp_path)), name="s")
    return app


def test_full_request_returns_200_with_immutable_cache_control(tmp_path):
    client = TestClient(_build_app(tmp_path))
    r = client.get("/s/hello.bin")
    assert r.status_code == 200
    assert r.headers["cache-control"] == "public, max-age=31536000, immutable"
    assert r.content == b"abcdefghijklmnop"


def test_range_request_returns_206_with_correct_bytes(tmp_path):
    client = TestClient(_build_app(tmp_path))
    r = client.get("/s/hello.bin", headers={"Range": "bytes=0-3"})
    assert r.status_code == 206
    assert r.content == b"abcd"
    assert r.headers["cache-control"] == "public, max-age=31536000, immutable"


def test_unknown_file_returns_404(tmp_path):
    client = TestClient(_build_app(tmp_path))
    r = client.get("/s/missing.bin")
    assert r.status_code == 404
