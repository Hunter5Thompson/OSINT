import pytest
from pydantic import ValidationError

from app.models.intel import IntelQuery

URL_REJECT_CASES = [
    "http://example.com/image.jpg",
    "https://user:pass@example.com/a.png",
    "https://@example.com/a.png",
    "/tmp/odin/images/a.png",
    "file:///tmp/a.png",
    "data:image/png;base64,AA==",
    "https:///missing-host.png",
    "https://example.com:bad/a.png",
    "https://",
    "https://[bad",
]
URL_ACCEPT_CASES = ["https://example.com/image.jpg", "https://8.8.8.8/a.png"]


@pytest.mark.parametrize("url", URL_REJECT_CASES)
def test_query_image_url_contract_rejects_non_https_and_credentials(url):
    with pytest.raises(ValidationError):
        IntelQuery(query="inspect", image_url=url)


@pytest.mark.parametrize("url", URL_ACCEPT_CASES)
def test_query_image_url_contract_accepts_https(url):
    assert IntelQuery(query="inspect", image_url=url).image_url == url


@pytest.mark.parametrize("url", URL_REJECT_CASES)
def test_http_query_rejects_image_url_before_stream(monkeypatch, url):
    from fastapi.testclient import TestClient

    from app.main import app
    from app.routers import intel

    def fail_stream(**_kwargs):
        raise AssertionError("stream pipeline must not run")

    monkeypatch.setattr(intel, "stream_intel_query", fail_stream)
    response = TestClient(app).post("/api/intel/query", json={"query": "inspect", "image_url": url})
    assert response.status_code == 422
