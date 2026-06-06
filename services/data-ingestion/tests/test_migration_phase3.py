from unittest.mock import AsyncMock, MagicMock

from gdelt_raw.migrations import apply as mig


def test_phase3_cypher_is_idempotent_and_batched():
    text = mig.read_cypher_file("phase3_timeline_at.cypher")
    assert "IF NOT EXISTS" in text
    assert "IN TRANSACTIONS" in text
    assert "e.timeline_at IS NULL" in text


async def test_apply_phase3_runs_statements_autocommit():
    # each statement runs in its own implicit/auto-commit session.run (no explicit tx)
    session = AsyncMock()
    session.run = AsyncMock()
    driver = MagicMock()
    driver.session.return_value.__aenter__ = AsyncMock(return_value=session)
    driver.session.return_value.__aexit__ = AsyncMock(return_value=False)
    await mig.apply_phase3(driver)
    assert session.run.await_count >= 2  # index + backfill
