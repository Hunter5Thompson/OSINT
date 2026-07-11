"""Tests for the live Base + Munin smoke contract."""

from __future__ import annotations

import json

import httpx

from scripts.react_smoke import run_smoke


def test_smoke_uses_base_for_tool_call_and_munin_for_synthesis() -> None:
    requested_models: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.read())
        requested_models.append(body["model"])
        if body["model"] == "qwen3.5":
            assert body["tool_choice"] == "auto"
            assert body["temperature"] == 0
            message = {"tool_calls": [{"function": {"name": "noop", "arguments": "{}"}}]}
        else:
            message = {"content": "Ein ausreichend langer deutscher Testlagebericht von Munin."}
        return httpx.Response(200, json={"choices": [{"message": message}]})

    result = run_smoke(
        base_url="https://vllm.test/v1",
        base_model="qwen3.5",
        synthesis_model="munin",
        transport=httpx.MockTransport(handler),
    )

    assert result is True
    assert requested_models == ["qwen3.5", "munin"]


def test_smoke_fails_when_base_does_not_call_tool() -> None:
    transport = httpx.MockTransport(
        lambda _request: httpx.Response(
            200,
            json={"choices": [{"message": {"content": "No tool call"}}]},
        )
    )

    result = run_smoke(
        base_url="https://vllm.test/v1",
        base_model="qwen3.5",
        synthesis_model="munin",
        transport=transport,
    )

    assert result is False
