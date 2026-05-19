"""Auto-promoter — FastAPI lifespan task.

Phase 1 deliverable: lifecycle scaffolding only (run / stop / sweeper-loop
placeholders). The drain loop and sweeper logic are wired up in Phase 4.
"""
from __future__ import annotations

import asyncio
from collections.abc import Callable, Sequence
from datetime import datetime

import structlog

from app.services.incident_promoter.cluster_store import ClusterStore
from app.services.incident_promoter.config import PromoterConfig
from app.services.incident_promoter.detectors.base import Detector

logger = structlog.get_logger(__name__)


class Promoter:
    """Single owner of the signal→incident pipeline."""

    def __init__(
        self,
        *,
        signal_stream,                         # SignalStream | None
        cluster_store: ClusterStore,
        incident_store,                        # object with create/apply/close/list_owned
        incident_event_stream,                 # object with publish(type_, incident)
        config: PromoterConfig,
        clock: Callable[[], datetime],
        detectors: Sequence[Detector],
    ) -> None:
        self._signal_stream = signal_stream
        self._cluster_store = cluster_store
        self._incident_store = incident_store
        self._incident_event_stream = incident_event_stream
        self._config = config
        self._clock = clock
        self._detectors: list[Detector] = list(detectors)
        self._stop_event = asyncio.Event()
        self._subscribed_queue: asyncio.Queue | None = None

    # -- lifecycle -------------------------------------------------------

    def request_stop(self) -> None:
        self._stop_event.set()

    def is_stop_requested(self) -> bool:
        return self._stop_event.is_set()

    def _has_runtime_deps(self) -> bool:
        """True only when both the signal stream and incident store are wired.

        Lifespan calls this before scheduling ``run`` / ``sweeper_loop``;
        ``run`` and ``sweeper_loop`` themselves re-check and bail with a
        warning so a misconfigured caller can't trigger a busy spin.
        """
        return self._signal_stream is not None and self._incident_store is not None

    async def run(self) -> None:
        """Phase 1 placeholder — no-op when disabled, real logic in Phase 4."""
        if not self._config.enabled:
            logger.info("promoter_disabled_skipping_run")
            return
        if not self._has_runtime_deps():
            logger.warning(
                "promoter_run_missing_runtime_deps_skipping",
                has_signal_stream=self._signal_stream is not None,
                has_incident_store=self._incident_store is not None,
            )
            return
        # Phase 4 implementation will:
        #   await self._subscribe()
        #   await self._rehydrate()
        #   await self._drain_loop()
        logger.warning("promoter_run_not_implemented_phase1")

    async def sweeper_loop(self) -> None:
        """Phase 1 placeholder — real implementation in Phase 4."""
        if not self._config.enabled:
            return
        if not self._has_runtime_deps():
            return
        logger.warning("promoter_sweeper_not_implemented_phase1")
