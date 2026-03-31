"""Shared test fixtures and app state setup."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.main import app


@pytest.fixture(autouse=True)
def set_app_state() -> None:
    """Set dummy app state so routers that access request.app.state don't raise AttributeError."""
    app.state.proxy = MagicMock()
    app.state.cache = AsyncMock()
