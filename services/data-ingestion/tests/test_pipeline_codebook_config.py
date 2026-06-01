from pathlib import Path

import pytest

from config import Settings
from pipeline import (
    CodebookConfigError,
    ExtractionConfigError,
    _build_system_prompt,
    _get_codebook_types,
    _load_codebook,
)


def _write(path: Path, text: str) -> Path:
    path.write_text(text)
    return path


def test_settings_default_codebook_path_exists():
    assert Settings(_env_file=None).event_codebook_path.is_file()


def test_settings_codebook_path_is_env_overridable(tmp_path, monkeypatch):
    path = tmp_path / "event-codebook.yaml"
    monkeypatch.setenv("EVENT_CODEBOOK_PATH", str(path))

    assert Settings(_env_file=None).event_codebook_path == path


def test_valid_codebook_loads_types_and_prompt(tmp_path):
    path = _write(
        tmp_path / "event-codebook.yaml",
        "categories:\n"
        "  military:\n"
        "    types:\n"
        "      - type: military.airstrike\n"
        "        description: Airstrike\n",
    )

    codebook = _load_codebook(path)

    assert _get_codebook_types(codebook) == frozenset({"military.airstrike"})
    assert "military.airstrike: Airstrike" in _build_system_prompt(codebook)


@pytest.mark.parametrize(
    "text",
    [
        "",
        "categories: [unterminated",
        "categories: {}",
        "categories:\n  military:\n    types: []\n",
    ],
)
def test_invalid_codebook_raises(tmp_path, text):
    path = _write(tmp_path / "event-codebook.yaml", text)

    with pytest.raises(CodebookConfigError):
        _load_codebook(path)


def test_missing_codebook_raises(tmp_path):
    with pytest.raises(CodebookConfigError):
        _load_codebook(tmp_path / "missing.yaml")


def test_codebook_error_is_not_extraction_config_error():
    assert not issubclass(CodebookConfigError, ExtractionConfigError)
