"""Admin token comparison: blank config fails closed, surrounding space does not."""

import pytest
from fastapi import HTTPException

from app.admin_auth import require_admin_token
from app.config import settings
from app.routers import almanac, reports


def test_supplied_token_whitespace_is_ignored() -> None:
    require_admin_token(expected_token="secret", supplied_token=" secret ", area="reports")


def test_blank_configured_token_is_unavailable() -> None:
    with pytest.raises(HTTPException) as exc:
        require_admin_token(expected_token="   ", supplied_token="secret", area="reports")
    assert exc.value.status_code == 503


def test_bearer_prefix_is_not_accepted() -> None:
    with pytest.raises(HTTPException) as exc:
        require_admin_token(
            expected_token="secret",
            supplied_token="Bearer secret",
            area="reports",
        )
    assert exc.value.status_code == 401


def test_almanac_prefers_the_reports_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "reports_admin_token", "reports-secret")
    monkeypatch.setattr(settings, "incidents_admin_token", "incidents-secret")

    almanac._require_report_admin("reports-secret")
    with pytest.raises(HTTPException) as exc:
        almanac._require_report_admin("incidents-secret")
    assert exc.value.status_code == 401


def test_almanac_uses_the_incidents_token_when_reports_token_is_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "reports_admin_token", "")
    monkeypatch.setattr(settings, "incidents_admin_token", "incidents-secret")

    almanac._require_report_admin(" incidents-secret ")


@pytest.mark.parametrize("router", [almanac, reports], ids=["almanac", "reports"])
@pytest.mark.parametrize("blank", [" ", "\n\t"])
def test_blank_reports_candidate_uses_normalized_incident_fallback(monkeypatch, router, blank):
    monkeypatch.setattr(settings, "reports_admin_token", blank)
    monkeypatch.setattr(settings, "incidents_admin_token", " test-only-fallback ")
    router._require_report_admin(" test-only-fallback ")


@pytest.mark.parametrize("router", [almanac, reports], ids=["almanac", "reports"])
def test_both_normalized_candidates_blank_are_unavailable(monkeypatch, router):
    monkeypatch.setattr(settings, "reports_admin_token", " \n")
    monkeypatch.setattr(settings, "incidents_admin_token", " \t")
    with pytest.raises(HTTPException) as exc:
        router._require_report_admin("test-only-supplied")
    assert exc.value.status_code == 503


@pytest.mark.parametrize("router", [almanac, reports], ids=["almanac", "reports"])
def test_real_reports_candidate_keeps_precedence_and_rejects_wrong_token(monkeypatch, router):
    monkeypatch.setattr(settings, "reports_admin_token", " test-only-primary ")
    monkeypatch.setattr(settings, "incidents_admin_token", "test-only-fallback")
    router._require_report_admin("test-only-primary")
    with pytest.raises(HTTPException) as exc:
        router._require_report_admin("test-only-fallback")
    assert exc.value.status_code == 401
