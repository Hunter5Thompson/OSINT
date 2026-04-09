"""Tests for FIRMS-ACLED cross-correlation job."""

from __future__ import annotations

from feeds.correlation_job import correlation_score


def test_score_close_same_day_explosion():
    """5km, same day, possible_explosion, Explosions type, high confidence → ≥ 0.8."""
    score = correlation_score(
        distance_km=5.0,
        days_diff=0,
        possible_explosion=True,
        acled_event_type="Explosions/Remote violence",
        firms_confidence="high",
    )
    assert score >= 0.8


def test_score_far_next_day():
    """45km, next day, no explosion, Battles type, nominal confidence → < 0.5."""
    score = correlation_score(
        distance_km=45.0,
        days_diff=1,
        possible_explosion=False,
        acled_event_type="Battles",
        firms_confidence="nominal",
    )
    assert score < 0.5


def test_score_boundary_50km():
    """Exactly 50km → dist_score = 0.0, base = 0.0."""
    score = correlation_score(
        distance_km=50.0,
        days_diff=0,
        possible_explosion=False,
        acled_event_type="Battles",
        firms_confidence="nominal",
    )
    assert score == 0.0


def test_score_capped_at_1():
    """Maximum bonuses should not exceed 1.0."""
    score = correlation_score(
        distance_km=0.0,
        days_diff=0,
        possible_explosion=True,
        acled_event_type="Explosions/Remote violence",
        firms_confidence="high",
    )
    assert score == 1.0


def test_score_zero_km_same_day_no_bonus():
    """0km, same day, no bonuses → base = 1.0."""
    score = correlation_score(
        distance_km=0.0,
        days_diff=0,
        possible_explosion=False,
        acled_event_type="Battles",
        firms_confidence="nominal",
    )
    assert score == 1.0
