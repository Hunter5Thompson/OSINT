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

    `event_id` is a fixed-width normalized Redis Stream record-id of the form
    `<013d ms>-<06d seq>`. Lexicographic string comparison of two `event_id`s
    matches their chronological/intra-ms order on a single Redis stream.
    `ts` is ISO-8601 UTC with millisecond precision ending in 'Z'.
    """

    event_id: str = Field(..., description="`<013d ms>-<06d seq>`, lex-monotonic")
    ts: str = Field(..., description="ISO-8601 UTC with ms precision, ends with 'Z'")
    type: str = Field(..., description="e.g. signal.firms, signal.ucdp, signal.unknown")
    payload: SignalPayload
