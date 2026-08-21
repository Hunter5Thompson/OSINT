"""Intel router tests for report-scoped persistence wiring."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models.intel import SpatialRunApplicationV1
from app.models.report import ReportRecord

_SPATIAL_APPLICATION = {
    "schema_version": 1,
    "scope": {
        "schema_version": 1,
        "scope_key": "country:UKR",
        "catalog_revision": "spatial-v1-e76a16bff799",
        "derivation_revision": "spatial-derive-v1-d30efa07e141",
        "boundary_policy": "odin-reference-v1",
    },
    "relation": "either",
    "qdrant": {
        "status": "applied",
        "mode": "semantic-key",
        "completeness": "partial",
    },
    "neo4j": {
        "status": "not-called",
        "mode": "semantic-key",
        "completeness": "unknown",
    },
    "blocked_tools": ["gdelt_query", "rss_fetch"],
    "coverage_revision": None,
}


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


class _SpatialMockHttpClient(_MockHttpClient):
    async def post(self, *args, **kwargs):
        response = _MockResp()
        base_json = response.json
        response.json = lambda: {
            **base_json(),
            "spatial_application": _SPATIAL_APPLICATION,
        }
        return response


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
        with patch(
            "app.services.intel_stream.report_store.get_report", AsyncMock(return_value=None)
        ):
            resp = client.post(
                "/api/intel/query",
                json={"query": "Brief me", "report_id": "r-missing", "report_message": "Brief me"},
            )

        assert resp.status_code == 200
        assert "REPORT_NOT_FOUND" in resp.text

    def test_persists_user_and_munin_messages(self, client: TestClient) -> None:
        append_mock = AsyncMock()
        update_mock = AsyncMock(return_value=_sample_report())
        with (
            patch(
                "app.services.intel_stream.report_store.get_report",
                AsyncMock(return_value=_sample_report()),
            ),
            patch("app.services.intel_stream.report_store.update_report", update_mock),
            patch("app.services.intel_stream.report_store.append_report_message", append_mock),
            patch("app.services.intel_stream.httpx.AsyncClient", return_value=_MockHttpClient()),
        ):
            resp = client.post(
                "/api/intel/query",
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
        patch_request = update_mock.await_args.args[1]
        assert "spatial_application" in patch_request.model_fields_set
        assert patch_request.spatial_application is None

    def test_clears_previous_application_for_later_unscoped_run(
        self,
        client: TestClient,
    ) -> None:
        report = _sample_report().model_copy(
            update={
                "spatial_application": SpatialRunApplicationV1.model_validate(
                    _SPATIAL_APPLICATION
                )
            }
        )
        cleared = report.model_copy(update={"spatial_application": None})
        update_mock = AsyncMock(return_value=cleared)
        with (
            patch(
                "app.services.intel_stream.report_store.get_report",
                AsyncMock(return_value=report),
            ),
            patch("app.services.intel_stream.report_store.update_report", update_mock),
            patch(
                "app.services.intel_stream.report_store.append_report_message",
                AsyncMock(),
            ),
            patch(
                "app.services.intel_stream.httpx.AsyncClient",
                return_value=_MockHttpClient(),
            ),
        ):
            response = client.post(
                "/api/intel/query",
                json={"query": "global follow-up", "report_id": "r-044"},
            )

        assert response.status_code == 200
        assert "event: result" in response.text
        patch_request = update_mock.await_args.args[1]
        assert "spatial_application" in patch_request.model_fields_set
        assert patch_request.spatial_application is None

    def test_does_not_persist_result_when_application_update_fails(
        self,
        client: TestClient,
    ) -> None:
        append_mock = AsyncMock()
        with (
            patch(
                "app.services.intel_stream.report_store.get_report",
                AsyncMock(return_value=_sample_report()),
            ),
            patch(
                "app.services.intel_stream.report_store.update_report",
                AsyncMock(side_effect=RuntimeError("write failed")),
            ),
            patch("app.services.intel_stream.report_store.append_report_message", append_mock),
            patch(
                "app.services.intel_stream.httpx.AsyncClient",
                return_value=_SpatialMockHttpClient(),
            ),
        ):
            response = client.post(
                "/api/intel/query",
                json={"query": "scoped follow-up", "report_id": "r-044"},
            )

        assert response.status_code == 200
        assert "INTEL_ERROR" in response.text
        assert "event: result" not in response.text
        assert [call.args[1].role for call in append_mock.await_args_list] == ["user"]

    def test_persists_error_message_on_http_failure(self, client: TestClient) -> None:
        append_mock = AsyncMock()

        class _BoomClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return None

            async def post(self, *a, **k):
                raise httpx.ConnectError("down")

        with (
            patch(
                "app.services.intel_stream.report_store.get_report",
                AsyncMock(return_value=_sample_report()),
            ),
            patch("app.services.intel_stream.report_store.append_report_message", append_mock),
            patch("app.services.intel_stream.httpx.AsyncClient", return_value=_BoomClient()),
        ):
            resp = client.post(
                "/api/intel/query",
                json={"query": "x", "report_id": "r-044", "report_message": "x"},
            )

        assert "INTEL_SERVICE_ERROR" in resp.text
        roles = [c.args[1].role for c in append_mock.await_args_list]
        assert "user" in roles and "munin" in roles  # user message + persisted error munin message

    def test_persists_original_result_application_without_report_relabel(
        self,
        client: TestClient,
    ) -> None:
        report = _sample_report().model_copy(update={"scope_key": "country:POL"})
        update_mock = AsyncMock(return_value=report)
        with (
            patch(
                "app.services.intel_stream.report_store.get_report",
                AsyncMock(return_value=report),
            ),
            patch("app.services.intel_stream.report_store.update_report", update_mock),
            patch(
                "app.services.intel_stream.report_store.append_report_message",
                AsyncMock(),
            ),
            patch(
                "app.services.intel_stream.httpx.AsyncClient",
                return_value=_SpatialMockHttpClient(),
            ),
        ):
            response = client.post(
                "/api/intel/query",
                json={"query": "old run", "report_id": "r-044"},
            )

        assert response.status_code == 200
        application = update_mock.await_args.args[1].spatial_application
        assert application is not None
        assert application.scope.scope_key == "country:UKR"
