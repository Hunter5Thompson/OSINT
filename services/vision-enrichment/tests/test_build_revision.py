"""Immutable loaded revision is not a consumer readiness or store-write claim."""

from unittest.mock import AsyncMock, Mock

import pytest


@pytest.mark.parametrize(
    "body,expected",
    [("a" * 40 + "\n", "a" * 40), ("unknown\n", None), ("a" * 41, None), ("x" * 129, None)],
)
def test_image_revision_is_bounded_and_ignores_runtime_env(tmp_path, monkeypatch, body, expected):
    from build_revision import read_image_revision

    monkeypatch.setenv("ODIN_BUILD_REVISION", "b" * 40)
    path = tmp_path / ".build-revision"
    path.write_text(body)
    assert read_image_revision(path) == expected
    assert read_image_revision(tmp_path / "missing") is None


async def test_actual_entrypoint_logs_loaded_revision_before_consumer(monkeypatch):
    import main as entry

    handlers = {}
    monkeypatch.setattr(
        entry.signal, "signal", lambda signum, callback: handlers.__setitem__(signum, callback)
    )
    redis = Mock(aclose=AsyncMock())
    monkeypatch.setattr(entry.aioredis, "from_url", lambda url: redis)

    async def consume():
        handlers[entry.signal.SIGTERM](entry.signal.SIGTERM, None)

    consumer = Mock(run=AsyncMock(side_effect=consume))
    monkeypatch.setattr(entry, "VisionConsumer", lambda **kwargs: consumer)
    monkeypatch.setattr(entry, "BUILD_REVISION", "a" * 40, raising=False)
    logger = Mock()
    monkeypatch.setattr(entry, "log", logger)
    await entry.main()
    assert logger.info.call_args_list[0].args == ("vision_service_starting",)
    assert logger.info.call_args_list[0].kwargs == {"revision": "a" * 40}
    redis.aclose.assert_awaited_once()
