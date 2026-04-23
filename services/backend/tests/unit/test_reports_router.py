"""Tests for report CRUD + report-scoped message router."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models.report import (
    DossierMetric,
    MarginEntry,
    ReportMessage,
    ReportRecord,
)


def _sample_report(report_id: str = "r-044") -> ReportRecord:
    now = datetime.now(UTC)
    return ReportRecord(
        id=report_id,
        paragraph_num=44,
        stamp="14·IV",
        title="Sinjar Ridge · Escalation Pattern",
        status="Draft",
        confidence=0.87,
        location="Sinjar ridge",
        coords="36.34N 41.87E",
        findings=["A", "B", "C"],
        metrics=[DossierMetric(label="clusters", value="17", sub="delta", tone="sentinel")],
        context="Pattern context",
        body_title="Body title",
        body_paragraphs=["Paragraph"],
        margin=[MarginEntry(label="window", value="22:14Z")],
        sources=["firms·1"],
        created_at=now,
        updated_at=now,
    )


class TestReportsRouter:
    @pytest.fixture
    def client(self) -> TestClient:
        return TestClient(app)

    def test_list_reports(self, client: TestClient) -> None:
        with patch("app.routers.reports.report_store.list_reports", AsyncMock(return_value=[_sample_report()])):
            resp = client.get("/api/v1/reports")

        assert resp.status_code == 200
        body = resp.json()
        assert len(body) == 1
        assert body[0]["id"] == "r-044"

    def test_create_report(self, client: TestClient) -> None:
        report = _sample_report("r-045")
        with patch("app.routers.reports.report_store.create_report", AsyncMock(return_value=report)):
            resp = client.post("/api/v1/reports", json={"title": "Untitled Dossier"})

        assert resp.status_code == 201
        body = resp.json()
        assert body["id"] == "r-045"

    def test_get_report_404(self, client: TestClient) -> None:
        with patch("app.routers.reports.report_store.get_report", AsyncMock(return_value=None)):
            resp = client.get("/api/v1/reports/r-missing")

        assert resp.status_code == 404

    def test_patch_report(self, client: TestClient) -> None:
        patched = _sample_report("r-044").model_copy(update={"title": "Updated title"})
        with patch("app.routers.reports.report_store.update_report", AsyncMock(return_value=patched)):
            resp = client.patch("/api/v1/reports/r-044", json={"title": "Updated title"})

        assert resp.status_code == 200
        assert resp.json()["title"] == "Updated title"

    def test_delete_report_204(self, client: TestClient) -> None:
        with patch("app.routers.reports.report_store.delete_report", AsyncMock(return_value=True)):
            resp = client.delete("/api/v1/reports/r-044")

        assert resp.status_code == 204

    def test_list_report_messages(self, client: TestClient) -> None:
        msg = ReportMessage(
            id="msg-1",
            role="munin",
            text="Signal synthesis",
            ts=datetime.now(UTC),
            refs=["firms·1"],
        )

        with (
            patch("app.routers.reports.report_store.get_report", AsyncMock(return_value=_sample_report())),
            patch("app.routers.reports.report_store.list_report_messages", AsyncMock(return_value=[msg])),
        ):
            resp = client.get("/api/v1/reports/r-044/messages")

        assert resp.status_code == 200
        body = resp.json()
        assert len(body) == 1
        assert body[0]["role"] == "munin"

    def test_create_report_message(self, client: TestClient) -> None:
        msg = ReportMessage(
            id="msg-2",
            role="user",
            text="Brief me on Sinjar",
            ts=datetime.now(UTC),
            refs=[],
        )
        with (
            patch("app.routers.reports.report_store.get_report", AsyncMock(return_value=_sample_report())),
            patch("app.routers.reports.report_store.append_report_message", AsyncMock(return_value=msg)),
        ):
            resp = client.post(
                "/api/v1/reports/r-044/messages",
                json={"role": "user", "text": "Brief me on Sinjar"},
            )

        assert resp.status_code == 201
        body = resp.json()
        assert body["id"] == "msg-2"
        assert body["text"] == "Brief me on Sinjar"
