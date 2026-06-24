from app.config import settings
from app.main import app


def test_cors_origins_are_loaded_from_settings() -> None:
    cors = next(m for m in app.user_middleware if m.cls.__name__ == "CORSMiddleware")

    assert cors.kwargs["allow_origins"] == settings.cors_origins
