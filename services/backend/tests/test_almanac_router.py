import time

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers import almanac
from app.services.signal_stream import get_signal_stream


def _build_app() -> FastAPI:
    app = FastAPI()
    app.include_router(almanac.router, prefix="/api")
    return app


def test_get_country_almanac_by_iso3() -> None:
    client = TestClient(_build_app())
    response = client.get("/api/almanac/countries/GRC")
    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "Greece"
    assert body["capital"]["name"] == "Athens"


def test_get_country_almanac_by_m49() -> None:
    client = TestClient(_build_app())
    response = client.get("/api/almanac/countries/732")
    assert response.status_code == 200
    assert response.json()["name"] == "W. Sahara"


def test_get_country_almanac_404_for_unknown() -> None:
    client = TestClient(_build_app())
    response = client.get("/api/almanac/countries/NOPE")
    assert response.status_code == 404
    assert response.json()["detail"] == "country almanac not found"


def test_get_country_signals_matches_explicit_iso3() -> None:
    stream = get_signal_stream()
    stream.clear()
    record_id = f"{int(time.time() * 1000)}-0"
    stream.insert_record(
        record_id,
        {
            "codebook_type": "signal.rss",
            "title": "Diplomatic statement indexed by Hugin",
            "severity": "low",
            "source": "rss",
            "country_iso3": "GRC",
        },
    )

    client = TestClient(_build_app())
    response = client.get("/api/almanac/countries/GRC/signals?limit=5")
    assert response.status_code == 200
    body = response.json()
    assert body["country_id"] == "GRC"
    assert body["items"][0]["title"] == "Diplomatic statement indexed by Hugin"
    stream.clear()


def test_get_country_signals_rejects_title_only_match() -> None:
    stream = get_signal_stream()
    stream.clear()
    record_id = f"{int(time.time() * 1000)}-1"
    stream.insert_record(
        record_id,
        {
            "codebook_type": "signal.rss",
            "title": "Greece mentioned only in title",
            "severity": "low",
            "source": "rss",
        },
    )

    client = TestClient(_build_app())
    response = client.get("/api/almanac/countries/GRC/signals?limit=5")
    assert response.status_code == 200
    assert response.json()["items"] == []
    stream.clear()
