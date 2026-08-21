"""Shared test fixtures and app state setup."""

import os
from unittest.mock import AsyncMock, MagicMock

import pytest

os.environ.update(
    {
        "NEO4J_PASSWORD": "test-neo4j-password",
        "REPORTS_ADMIN_TOKEN": "",
        "INCIDENTS_ADMIN_TOKEN": "",
    }
)

from app.config import settings  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def assert_test_app_has_no_admin_tokens() -> None:
    """Keep backend tests independent from caller and dotenv admin tokens."""
    if settings.reports_admin_token or settings.incidents_admin_token:
        raise AssertionError("backend test app loaded an admin token from host state")


@pytest.fixture(autouse=True)
def set_app_state() -> None:
    """Set dummy app state so routers that access request.app.state don't raise AttributeError."""
    app.state.proxy = MagicMock()
    app.state.cache = AsyncMock()
    app.state.cluster_store = None  # router code uses getattr(..., None); explicit for clarity
