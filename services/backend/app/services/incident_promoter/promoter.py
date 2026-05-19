"""Auto-promoter — FastAPI lifespan task.

Phase 4 deliverable: full drain loop, rehydrate, sweeper, and composable
helper methods. The __init__, request_stop, is_stop_requested, and
_has_runtime_deps from Phase 1 are preserved unchanged.
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

    # -- composable methods (Phase 4) -----------------------------------

    async def _subscribe(self) -> None:
        if self._signal_stream is None:
            self._subscribed_queue = None
            return
        self._subscribed_queue = self._signal_stream.subscribe()

    def _unsubscribe(self) -> None:
        if self._signal_stream is not None and self._subscribed_queue is not None:
            self._signal_stream.unsubscribe(self._subscribed_queue)
        self._subscribed_queue = None

    async def _rehydrate(self) -> None:
        if self._incident_store is None:
            return
        owned = await self._incident_store.list_owned_for_rehydrate()
        for incident in owned:
            cluster_key = self._extract_cluster_key(incident.layer_hints)
            if cluster_key is None:
                logger.info(
                    "promoter_rehydrate_skipped",
                    incident_id=incident.id,
                    reason="no_cluster_marker",
                )
                continue
            detector_id = cluster_key.split(":", 2)[1] if ":" in cluster_key else "unknown"
            self._cluster_store._by_key[cluster_key] = self._build_rehydrated_state(  # noqa: SLF001
                incident, cluster_key, detector_id
            )
            self._cluster_store._by_incident_id[incident.id] = cluster_key  # noqa: SLF001

    def _build_rehydrated_state(self, incident, cluster_key: str, detector_id: str):
        from app.services.incident_promoter.cluster_store import ClusterState

        return ClusterState(
            cluster_key=cluster_key,
            incident_id=incident.id,
            detector_id=detector_id,
            severity=incident.severity,
            coords=incident.coords,
            hit_count=len(incident.timeline),
            last_signal_ts=self._estimate_last_ts(incident),
            created_ts=incident.trigger_ts,
            contributing_signal_ids=[],
            incident_status=(
                "promoted" if str(incident.status) == "promoted" else "open"
            ),
        )

    @staticmethod
    def _extract_cluster_key(layer_hints: list[str]) -> str | None:
        for h in layer_hints:
            if h.startswith("cluster:"):
                return h[len("cluster:"):]
        return None

    def _estimate_last_ts(self, incident):
        if incident.timeline:
            offset = max(e.t_offset_s for e in incident.timeline)
            from datetime import timedelta
            return incident.trigger_ts + timedelta(seconds=offset)
        return incident.trigger_ts

    async def _drain_one(self) -> None:
        if self._subscribed_queue is None:
            return
        envelope = await self._subscribed_queue.get()
        await self._process(envelope)

    async def _drain_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                await self._drain_one()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 — keep loop alive
                logger.exception("promoter_drain_loop_error")

    async def _process(self, envelope) -> None:
        for detector in self._detectors:
            try:
                hit = detector.detect(envelope)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "promoter_detector_error",
                    detector_id=getattr(detector, "id", "?"),
                    error=str(exc),
                    envelope_event_id=getattr(envelope, "event_id", "?"),
                )
                continue
            if hit is None:
                continue
            await self._cluster_store.handle(
                hit,
                incident_store=self._incident_store,
                incident_event_stream=self._incident_event_stream,
            )

    async def run(self) -> None:
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
        # Register detector termination listeners (must be before any signal arrives)
        for detector in self._detectors:
            self._cluster_store.add_termination_listener(detector.on_cluster_terminated)
        await self._subscribe()
        try:
            await self._rehydrate()
            logger.info(
                "promoter_started",
                detectors_enabled=[d.id for d in self._detectors if d.enabled],
                rehydrated_count=len(self._cluster_store.active_clusters()),
            )
            await self._drain_loop()
        finally:
            self._unsubscribe()

    # -- sweeper --------------------------------------------------------

    async def _sweep_once(self) -> None:
        now = self._clock()
        snap = self._cluster_store.snapshot_for_sweep(
            quiet_window_sec=self._config.quiet_window_sec, now=now
        )
        # Expire cooldowns inline (no I/O)
        self._cluster_store.pop_expired_cooldowns(snap.expired_cooldown_keys)
        # Close stale open
        from app.models.incident import IncidentStatus
        for state in snap.stale_open:
            try:
                closed = await self._incident_store.close_incident(
                    state.incident_id, status=IncidentStatus.CLOSED
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "promoter_close_failed",
                    incident_id=state.incident_id,
                    error=str(exc),
                )
                continue
            await self._cluster_store.drop_cluster(state.cluster_key)
            if closed is not None:
                self._incident_event_stream.publish("incident.close", closed)
                logger.info(
                    "promoter_cluster_closed",
                    cluster_key=state.cluster_key,
                    incident_id=state.incident_id,
                    quiet_seconds=int(self._config.quiet_window_sec),
                    final_hit_count=state.hit_count,
                )
        # Drop stale promoted — no DB write (analyst already wrote PROMOTED via /promote router)
        for state in snap.stale_promoted:
            await self._cluster_store.drop_cluster(state.cluster_key)

    async def sweeper_loop(self) -> None:
        if not self._config.enabled:
            return
        if not self._has_runtime_deps():
            return
        while not self._stop_event.is_set():
            try:
                await asyncio.wait_for(
                    self._stop_event.wait(),
                    timeout=self._config.sweeper_tick_sec,
                )
                return  # stop set during the wait
            except TimeoutError:
                pass
            try:
                await self._sweep_once()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                logger.exception("promoter_sweeper_error")
