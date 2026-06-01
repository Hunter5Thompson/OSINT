"""Guard: no backend route is mounted under the legacy /api/v1 prefix.

The /api/v1 back-compat aliases were removed; every route lives under /api.
This snapshot keeps the legacy prefix from creeping back in.
"""

from app.main import app


def test_no_route_uses_legacy_v1_prefix() -> None:
    v1_routes = sorted(
        str(getattr(route, "path", ""))
        for route in app.router.routes
        if str(getattr(route, "path", "")).startswith("/api/v1")
    )
    assert v1_routes == [], v1_routes
