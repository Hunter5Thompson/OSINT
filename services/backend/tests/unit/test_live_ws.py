"""Live sockets report a failed fetch and stop when the client leaves."""

import json
from unittest.mock import AsyncMock

import pytest
from fastapi import WebSocketDisconnect

from app.config import settings
from app.models.flight import Aircraft
from app.ws import flight_ws, vessel_ws


def _socket(cache_payload: object = None) -> tuple[AsyncMock, list[str]]:
    sent: list[str] = []
    socket = AsyncMock()
    socket.app.state.cache = AsyncMock()
    socket.app.state.cache.get.return_value = cache_payload
    socket.app.state.proxy = AsyncMock()
    socket.send_text = AsyncMock(side_effect=lambda payload: sent.append(payload))
    return socket, sent


@pytest.mark.asyncio
async def test_flight_socket_sends_an_error_frame_when_fetch_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    socket, sent = _socket()
    monkeypatch.setattr(
        flight_ws.flight_service,
        "get_flights",
        AsyncMock(side_effect=RuntimeError("down")),
    )

    async def stop(_seconds: float) -> None:
        raise WebSocketDisconnect()

    monkeypatch.setattr(flight_ws.asyncio, "sleep", stop)

    await flight_ws.flight_stream(socket)

    assert json.loads(sent[0])["type"] == "error"


@pytest.mark.asyncio
async def test_flight_socket_sends_positions(monkeypatch: pytest.MonkeyPatch) -> None:
    socket, sent = _socket()
    monkeypatch.setattr(
        flight_ws.flight_service,
        "get_flights",
        AsyncMock(return_value=[Aircraft(icao24="abc", latitude=50.0, longitude=8.0)]),
    )

    async def stop(_seconds: float) -> None:
        raise WebSocketDisconnect()

    monkeypatch.setattr(flight_ws.asyncio, "sleep", stop)

    await flight_ws.flight_stream(socket)

    payload = json.loads(sent[0])
    assert payload["type"] == "flights"
    assert payload["count"] == 1
    assert payload["data"][0]["icao24"] == "abc"


@pytest.mark.asyncio
async def test_vessel_socket_sends_empty_without_an_api_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    socket, sent = _socket(None)
    monkeypatch.setattr(settings, "aisstream_api_key", "")

    async def stop(_seconds: float) -> None:
        raise WebSocketDisconnect()

    monkeypatch.setattr(vessel_ws.asyncio, "sleep", stop)

    await vessel_ws.vessel_stream(socket)

    payload = json.loads(sent[0])
    assert payload["type"] == "vessels"
    assert payload["count"] == 0
