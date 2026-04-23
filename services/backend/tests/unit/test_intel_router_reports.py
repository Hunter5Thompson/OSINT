"""Intel router tests for report-scoped persistence wiring."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models.report import ReportRecord


class _MockResp:
    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return {
            "agent_chain": ["osint_agent", "analyst_agent"],
            "sources_used": ["firms·1"],
            "analysis": "Synthesis text",
            "confidence": 0.84,
            "threat_assessment": "MODERATE",
            "tool_trace": [],
            "mode": "react",
            "timestamp": datetime.now(UTC).isoformat(),
        }


class _MockHttpClient:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def post(self, *args, **kwargs):
        return _MockResp()


def _sample_report() -> ReportRecord:
    now = datetime.now(UTC)
    return ReportRecord(
        id="r-044",
        paragraph_num=44,
        stamp="14·IV",
        title="Sinjar",
        status="Draft",
        confidence=0.8,
        location="Sinjar",
        coords="--",
        findings=["A"],
        metrics=[],
        context="ctx",
        body_title="body",
        body_paragraphs=["p"],
        margin=[],
        sources=["firms·1"],
        created_at=now,
        updated_at=now,
    )


class TestIntelReportScopedPersistence:
    @pytest.fixture
    def client(self) -> TestClient:
        return TestClient(app)

    def test_returns_error_when_report_missing(self, client: TestClient) -> None:
        with patch("app.routers.intel.report_store.get_report", AsyncMock(return_value=None)):
            resp = client.post(
                "/api/v1/intel/query",
                json={"query": "Brief me", "report_id": "r-missing", "report_message": "Brief me"},
            )

        assert resp.status_code == 200
        assert "REPORT_NOT_FOUND" in resp.text

    def test_persists_user_and_munin_messages(self, client: TestClient) -> None:
        append_mock = AsyncMock()
        with (
            patch("app.routers.intel.report_store.get_report", AsyncMock(return_value=_sample_report())),
            patch("app.routers.intel.report_store.append_report_message", append_mock),
            patch("app.routers.intel.httpx.AsyncClient", return_value=_MockHttpClient()),
        ):
            resp = client.post(
                "/api/v1/intel/query",
                json={
                    "query": "Report 44: Brief me",
                    "report_id": "r-044",
                    "report_message": "Brief me on Sinjar",
                },
            )

        assert resp.status_code == 200
        assert "event: result" in resp.text
        assert append_mock.await_count >= 2
        first_call = append_mock.await_args_list[0]
        second_call = append_mock.await_args_list[1]
        assert first_call.args[0] == "r-044"
        assert first_call.args[1].role == "user"
        assert second_call.args[1].role == "munin"
