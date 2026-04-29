import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]


def _compose_service_block(compose: str, service: str) -> str:
    match = re.search(
        rf"^  {re.escape(service)}:\n(?P<block>.*?)(?=^  \S|\Z)",
        compose,
        re.M | re.S,
    )
    assert match is not None
    return match.group("block")


def test_data_ingestion_image_copies_gdelt_raw_package():
    dockerfile = (REPO_ROOT / "services" / "data-ingestion" / "Dockerfile").read_text()

    assert "COPY gdelt_raw/ gdelt_raw/" in dockerfile


def test_data_ingestion_image_exposes_venv_scripts_on_path():
    dockerfile = (REPO_ROOT / "services" / "data-ingestion" / "Dockerfile").read_text()

    assert 'ENV PATH="/app/.venv/bin:$PATH"' in dockerfile


def test_wheel_includes_gdelt_raw_package():
    pyproject = (REPO_ROOT / "services" / "data-ingestion" / "pyproject.toml").read_text()

    assert "gdelt_raw/**/*.py" in pyproject


def test_compose_data_ingestion_separates_bolt_driver_and_http_tx_url():
    compose = (REPO_ROOT / "docker-compose.yml").read_text()

    for service in ("data-ingestion", "data-ingestion-spark"):
        block = _compose_service_block(compose, service)
        assert "NEO4J_URL=bolt://neo4j:7687" in block
        assert "NEO4J_URL=http://neo4j:7474" not in block
        assert "NEO4J_HTTP_URL=http://neo4j:7474" in block
