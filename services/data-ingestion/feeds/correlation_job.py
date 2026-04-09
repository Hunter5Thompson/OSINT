"""FIRMS-ACLED cross-correlation batch job.

Correlates FIRMS thermal anomalies (possible_explosion=true) with
ACLED conflict events within a configurable radius and time window.
Writes CORROBORATED_BY relationships to Neo4j.
"""

from __future__ import annotations


def correlation_score(
    distance_km: float,
    days_diff: int,
    possible_explosion: bool,
    acled_event_type: str,
    firms_confidence: str,
) -> float:
    """Compute correlation confidence between a FIRMS and ACLED event.

    Returns a score from 0.0 to 1.0.
    """
    # Distance: 0km = 1.0, 50km = 0.0 (linear)
    dist_score = max(0.0, 1.0 - distance_km / 50.0)

    # Time: same day = 1.0, ±1 day = 0.5
    time_score = 1.0 if days_diff == 0 else 0.5

    # Base = distance × time
    base = dist_score * time_score

    # Additive bonuses, capped at 1.0
    bonus = 0.0
    if possible_explosion:
        bonus += 0.3
    if acled_event_type == "Explosions/Remote violence":
        bonus += 0.2
    if firms_confidence == "high":
        bonus += 0.1

    return min(1.0, round(base + bonus, 2))
