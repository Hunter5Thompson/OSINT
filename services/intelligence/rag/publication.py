"""Conservative day-level comparison of explicit original publication headers."""

import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal

PublicationCheck = Literal[
    "not_checked", "not_found", "matched_day", "timezone_unresolved", "conflict"
]


@dataclass(frozen=True)
class PublicationResult:
    status: PublicationCheck
    original_date: date | None


def check_publication(text: str, provider_time: datetime | None) -> PublicationResult:
    # Only explicit headers near the beginning; event dates in prose do not qualify.
    match = re.search(
        r"(?:^|\n)\s*(?:Published|First published|Veröffentlicht)"
        r"\s*(?:on|am)?\s*:?\s*([^\n]{1,100})",
        text[:12000],
        re.I,
    )
    original = None
    if match:
        header = match[1].strip().replace("Sept ", "Sep ")
        iso = re.match(r"(\d{4}-\d{2}-\d{2})(?:\b|T)", header)
        english = re.match(r"([A-Za-z]+\s+\d{1,2},?\s+\d{4})\b", header)
        try:
            if iso:
                original = date.fromisoformat(iso[1])
            elif english:
                for format_string in ("%B %d, %Y", "%b %d, %Y", "%B %d %Y", "%b %d %Y"):
                    try:
                        original = datetime.strptime(english[1], format_string).date()
                        break
                    except ValueError:
                        continue
        except ValueError:
            original = None
    if original is None:
        return PublicationResult("not_found", None)
    if provider_time is None:
        return PublicationResult("not_checked", original)
    days = abs((original - provider_time.date()).days)
    return PublicationResult(
        "matched_day" if days == 0 else "timezone_unresolved" if days == 1 else "conflict", original
    )
