"""Pydantic models for the /api/signals event envelope."""

from __future__ import annotations

from pydantic import BaseModel, Field


class SignalPayload(BaseModel):
    """Envelope payload — open schema but with the known canonical fields.

    `redis_id` is always populated with the originating Redis Stream record-id
    (format `<ms>-<seq>`) so clients can correlate with upstream events.

    Additional fields from the Redis record are allowed and pass through.
    """

    title: str = ""
    severity: str = "low"
    source: str = ""
    url: str = ""
    redis_id: str

    model_config = {"extra": "allow"}


class SignalEnvelope(BaseModel):
    """Common event envelope for all /api/signals SSE frames.

    `event_id` is a ULID derived from the upstream Redis record timestamp,
    monotonic even within the same millisecond.
    `ts` is ISO-8601 UTC with millisecond precision ending in 'Z'.
    """

    event_id: str = Field(..., description="ULID, monotonically sortable")
    ts: str = Field(..., description="ISO-8601 UTC with ms precision, ends with 'Z'")
    type: str = Field(..., description="e.g. signal.firms, signal.ucdp, signal.unknown")
    payload: SignalPayload
