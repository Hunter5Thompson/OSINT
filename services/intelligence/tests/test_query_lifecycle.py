"""Cancellation owns and joins work before returning from the request."""
import asyncio

import pytest

from query_lifecycle import ClientDisconnectedError, run_connected


@pytest.mark.asyncio
@pytest.mark.parametrize("ending", ["disconnect", "timeout", "cancel", "failure", "success"])
async def test_request_joins_work_and_watcher_on_all_exits(ending):
    started, finish, disconnect, cleaned = (asyncio.Event() for _ in range(4))

    async def work():
        try:
            started.set()
            await finish.wait()
            if ending == "failure":
                raise ValueError("failed")
            return "result"
        finally:
            # Cleanup may itself be asynchronous; it must finish before return.
            await asyncio.sleep(0)
            cleaned.set()

    async def is_disconnected():
        return disconnect.is_set()

    before = asyncio.all_tasks()
    task = asyncio.create_task(run_connected(
        work(), is_disconnected, timeout_s=0.03 if ending == "timeout" else 2,
        poll_s=0.001,
    ))
    await asyncio.wait_for(started.wait(), 1)
    if ending == "disconnect":
        disconnect.set()
    elif ending == "cancel":
        task.cancel()
    elif ending != "timeout":
        finish.set()
    result = (await asyncio.wait_for(asyncio.gather(task, return_exceptions=True), 1))[0]
    expected = {"disconnect": ClientDisconnectedError, "timeout": TimeoutError,
                "cancel": asyncio.CancelledError, "failure": ValueError}
    if ending == "success":
        assert result == "result"
    else:
        assert isinstance(result, expected[ending])
    assert cleaned.is_set()
    assert asyncio.all_tasks() <= before


@pytest.mark.asyncio
async def test_disconnect_probe_swallowing_cancellation_cannot_leak_watcher():
    probing = asyncio.Event()

    async def work():
        await probing.wait()
        return "complete"

    async def disconnect_probe():
        probing.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            # Starlette's is_disconnected uses an AnyIO CancelScope, which may
            # consume cancellation arriving while receive() is being probed.
            return False

    assert await asyncio.wait_for(run_connected(
        work(), disconnect_probe, timeout_s=1, poll_s=0.001,
    ), .1) == "complete"


@pytest.mark.asyncio
@pytest.mark.parametrize("ending", ["disconnect", "timeout"])
async def test_http_query_cancels_downstream_before_returning(monkeypatch, ending):
    import json

    import main

    started, disconnected, cleaned = (asyncio.Event() for _ in range(3))

    async def slow_query(req):
        try:
            started.set()
            await asyncio.Event().wait()
        finally:
            await asyncio.sleep(0)
            cleaned.set()

    monkeypatch.setattr(main, "query_intelligence", slow_query)
    monkeypatch.setattr(main.settings, "query_timeout_s", .03 if ending == "timeout" else 1)
    body = json.dumps({"query": "synthetic", "spatial_relation": "either"}).encode()
    first = True
    statuses = []

    async def receive():
        nonlocal first
        if first:
            first = False
            return {"type": "http.request", "body": body, "more_body": False}
        await disconnected.wait()
        return {"type": "http.disconnect"}

    async def send(message):
        assert cleaned.is_set(), "HTTP response sent before owned work ended"
        if message["type"] == "http.response.start":
            statuses.append(message["status"])

    scope = {
        "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
        "method": "POST", "scheme": "http", "path": "/query",
        "raw_path": b"/query", "query_string": b"", "root_path": "",
        "headers": [(b"content-type", b"application/json")],
        "client": ("127.0.0.1", 1), "server": ("127.0.0.1", 2),
    }
    task = asyncio.create_task(main.app(scope, receive, send))
    try:
        await asyncio.wait_for(started.wait(), 1)
        if ending == "disconnect":
            disconnected.set()
        await asyncio.wait_for(task, 2)
        assert statuses == [499 if ending == "disconnect" else 504]
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
