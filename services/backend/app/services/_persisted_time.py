"""Strict UTC decoding for timestamps read from persisted records."""
from __future__ import annotations

from datetime import UTC, datetime


def parse_persisted_datetime(
    value: str | datetime | None,
    *,
    missing_fallback: datetime | None = None,
) -> datetime:
    """Parse a stored timestamp, treating naive historical values explicitly as UTC."""
    if value is None:
        if missing_fallback is None:
            raise ValueError("missing persisted datetime")
        parsed = missing_fallback
    elif isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        if not value:
            raise ValueError("empty persisted datetime")
        normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
        try:
            parsed = datetime.fromisoformat(normalized)
        except ValueError as exc:
            raise ValueError("invalid persisted datetime") from exc
    else:
        raise TypeError("persisted datetime must be a string or datetime")

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)
