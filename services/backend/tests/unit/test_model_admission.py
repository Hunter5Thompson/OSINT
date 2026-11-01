"""Admission invariants across independent processes and response lifetimes."""
import multiprocessing
from pathlib import Path

import pytest

from app.services.model_admission import AdmissionBusyError, FileAdmission


def compete(path, connection):
    try:
        with FileAdmission(Path(path), 1).acquire():
            connection.send("admitted")
    except AdmissionBusyError:
        connection.send("busy")
    finally:
        connection.close()


def child_result(path):
    context = multiprocessing.get_context("spawn")
    receiver, sender = context.Pipe(duplex=False)
    process = context.Process(target=compete, args=(str(path), sender))
    process.start()
    sender.close()
    try:
        assert receiver.poll(10), "child did not report admission"
        return receiver.recv()
    finally:
        process.join(10)
        if process.is_alive():
            process.kill()
            process.join()
        receiver.close()
        assert process.exitcode == 0


def test_capacity_is_shared_with_another_process_and_released(tmp_path):
    gate = FileAdmission(tmp_path, 1)
    with gate.acquire():
        assert child_result(tmp_path) == "busy"
    assert child_result(tmp_path) == "admitted"


def test_exception_and_double_close_do_not_leak_or_release_another_lease(tmp_path):
    gate = FileAdmission(tmp_path, 1)
    with pytest.raises(RuntimeError), gate.acquire():
        raise RuntimeError("downstream failed")
    old = gate.acquire()
    old.close()
    with gate.acquire():
        old.close()
        with pytest.raises(AdmissionBusyError):
            gate.acquire()


def test_capacity_is_exact_and_queue_is_empty(tmp_path):
    gate = FileAdmission(tmp_path, 2)
    with gate.acquire(), gate.acquire():
        with pytest.raises(AdmissionBusyError):
            gate.acquire()
    with gate.acquire(), gate.acquire():
        pass


@pytest.mark.parametrize("capacity", [0, -1, 65])
def test_invalid_capacity_is_rejected(tmp_path, capacity):
    with pytest.raises(ValueError):
        FileAdmission(tmp_path, capacity)


def test_symlink_slot_is_rejected_without_touching_target(tmp_path):
    target = tmp_path / "protected"
    target.write_text("preserved")
    (tmp_path / "slot-0.lock").symlink_to(target)
    with pytest.raises(OSError):
        FileAdmission(tmp_path, 1).acquire()
    assert target.read_text() == "preserved"


@pytest.mark.parametrize("ending", ["complete", "disconnect", "cancel", "failure"])
async def test_permit_spans_sse_and_is_released_on_every_exit(tmp_path, monkeypatch, ending):
    import asyncio
    import json

    from fastapi import FastAPI

    from app.config import settings
    from app.routers import intel

    monkeypatch.setattr(settings, "model_admission_dir", tmp_path)
    monkeypatch.setattr(settings, "reports_admin_token", "test-operator")
    app = FastAPI()
    app.include_router(intel.router, prefix="/api")
    started, finish, disconnected, closed = (asyncio.Event() for _ in range(4))

    async def stream(**kwargs):
        try:
            yield {"event": "status", "data": "{}"}
            started.set()
            await finish.wait()
            if ending == "failure":
                raise RuntimeError("upstream generator failed")
            yield {"event": "done", "data": ""}
        finally:
            closed.set()

    monkeypatch.setattr(intel, "stream_intel_query", stream)
    body = json.dumps({"query": "test"}).encode()
    first = True

    async def receive():
        nonlocal first
        if first:
            first = False
            return {"type": "http.request", "body": body, "more_body": False}
        await disconnected.wait()
        return {"type": "http.disconnect"}

    async def send(message):
        pass

    scope = {
        "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
        "method": "POST", "scheme": "http", "path": "/api/intel/query",
        "raw_path": b"/api/intel/query", "query_string": b"", "root_path": "",
        "headers": [(b"content-type", b"application/json"),
                    (b"x-admin-token", b"test-operator")],
        "client": ("127.0.0.1", 1), "server": ("127.0.0.1", 2),
    }
    task = asyncio.create_task(app(scope, receive, send))
    try:
        await asyncio.wait_for(started.wait(), 2)
        with pytest.raises(AdmissionBusyError):
            FileAdmission(tmp_path, 1).acquire()
        if ending == "disconnect":
            disconnected.set()
        elif ending == "cancel":
            task.cancel()
        else:
            finish.set()
        result = await asyncio.wait_for(asyncio.gather(task, return_exceptions=True), 2)
        if ending in {"cancel", "failure"}:
            assert isinstance(result[0], BaseException)
        else:
            assert result == [None]
        assert closed.is_set()
        with FileAdmission(tmp_path, 1).acquire():
            pass
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


def hold_until_terminated(path, connection):
    with FileAdmission(Path(path), 1).acquire():
        connection.send("held")
        connection.recv()


def test_worker_death_releases_kernel_permit(tmp_path):
    context = multiprocessing.get_context("spawn")
    parent, child = context.Pipe()
    process = context.Process(target=hold_until_terminated, args=(str(tmp_path), child))
    process.start()
    child.close()
    try:
        assert parent.poll(10)
        assert parent.recv() == "held"
        with pytest.raises(AdmissionBusyError):
            FileAdmission(tmp_path, 1).acquire()
    finally:
        process.terminate()
        process.join(10)
        parent.close()
    assert not process.is_alive()
    with FileAdmission(tmp_path, 1).acquire():
        pass
