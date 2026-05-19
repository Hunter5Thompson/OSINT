"""Promoter shell — startup/shutdown and config gating."""
import asyncio

import pytest

from app.services.incident_promoter.cluster_store import ClusterStore
from app.services.incident_promoter.config import PromoterConfig
from app.services.incident_promoter.promoter import Promoter


@pytest.fixture
def disabled_config() -> PromoterConfig:
    return PromoterConfig.from_env().__class__(
        **{**PromoterConfig.from_env().__dict__, "enabled": False}
    )


async def test_promoter_request_stop_is_idempotent(fake_clock, disabled_config,
                                                   fake_incident_store,
                                                   fake_incident_event_stream):
    promoter = Promoter(
        signal_stream=None,                       # not used while disabled
        cluster_store=ClusterStore(clock=fake_clock),
        incident_store=fake_incident_store,
        incident_event_stream=fake_incident_event_stream,
        config=disabled_config,
        clock=fake_clock,
        detectors=[],
    )
    promoter.request_stop()
    promoter.request_stop()    # no exception
    assert promoter.is_stop_requested() is True


async def test_promoter_run_exits_promptly_when_disabled(fake_clock, disabled_config,
                                                        fake_incident_store,
                                                        fake_incident_event_stream):
    promoter = Promoter(
        signal_stream=None,
        cluster_store=ClusterStore(clock=fake_clock),
        incident_store=fake_incident_store,
        incident_event_stream=fake_incident_event_stream,
        config=disabled_config,
        clock=fake_clock,
        detectors=[],
    )
    # When disabled, run() should return without subscribing or draining.
    await asyncio.wait_for(promoter.run(), timeout=0.5)
