"""Each independent service image must contain the canonical orbital decoder."""

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize(
    "relative",
    [
        "services/backend/app/orbit_elements.py",
        "services/data-ingestion/orbit_elements.py",
    ],
)
def test_orbit_decoder_vendoring_is_byte_exact(relative: str) -> None:
    assert (ROOT / relative).read_bytes() == (ROOT / "shared/orbit_elements.py").read_bytes()


def test_orbit_decoders_are_in_independent_image_and_wheel_contexts() -> None:
    backend = (ROOT / "services/backend/Dockerfile").read_text()
    ingestion = (ROOT / "services/data-ingestion/Dockerfile").read_text()
    assert "COPY app/ app/" in backend
    assert "COPY services/data-ingestion/orbit_elements.py ." in ingestion
    assert 'packages = ["app"]' in (ROOT / "services/backend/pyproject.toml").read_text()
    assert '"*.py"' in (ROOT / "services/data-ingestion/pyproject.toml").read_text()
