"""Own one query task and join cancellation before its HTTP handler exits."""
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Coroutine
from typing import Any


class ClientDisconnectedError(Exception):
    """The caller left before the query completed."""


async def run_connected[T](
    work: Coroutine[Any, Any, T],
    is_disconnected: Callable[[], Awaitable[bool]],
    *,
    timeout_s: float,
    poll_s: float = 0.1,
) -> T:
    stopping = asyncio.Event()

    async def watch() -> None:
        while not stopping.is_set():
            if await is_disconnected():
                raise ClientDisconnectedError
            if not stopping.is_set():
                await asyncio.sleep(poll_s)

    task = asyncio.create_task(work)
    watcher = asyncio.create_task(watch())
    try:
        async with asyncio.timeout(timeout_s):
            completed, _ = await asyncio.wait(
                {task, watcher}, return_when=asyncio.FIRST_COMPLETED,
            )
            # If both completed, the computed result owns the terminal state.
            if task in completed:
                return task.result()
            watcher.result()
            raise AssertionError("disconnect watcher returned without an error")
    finally:
        stopping.set()
        task.cancel()
        watcher.cancel()
        await asyncio.gather(task, watcher, return_exceptions=True)
