import pytest
from pydantic import ValidationError

from app.models.intel import IntelQuery


def test_intel_query_accepts_public_http_image_url() -> None:
    query = IntelQuery(query="analyze", image_url="https://example.org/image.jpg")

    assert query.image_url == "https://example.org/image.jpg"


@pytest.mark.parametrize(
    "url",
    [
        "ftp://example.org/image.jpg",
        "http://localhost/image.jpg",
        "http://127.0.0.1/image.jpg",
        "http://10.0.0.5/image.jpg",
        "http://169.254.169.254/latest/meta-data",
        "http://[::1]/image.jpg",
        "http://camera.local/image.jpg",
    ],
)
def test_intel_query_rejects_non_public_image_urls(url: str) -> None:
    with pytest.raises(ValidationError):
        IntelQuery(query="analyze", image_url=url)
