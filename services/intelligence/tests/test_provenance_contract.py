"""The intelligence read-side must agree with the shared provenance contract."""
from __future__ import annotations

import json
from pathlib import Path

_CONTRACT = (
    Path(__file__).resolve().parents[3] / "contracts" / "qdrant-provenance-v1.json"
)


def _load() -> dict:
    return json.loads(_CONTRACT.read_text(encoding="utf-8"))


def test_contract_file_exists_and_is_versioned():
    data = _load()
    assert data["contract_version"] == 1


def test_required_and_optional_fields():
    data = _load()
    assert data["required"] == ["source_type", "provider", "ingested_at"]
    assert data["optional"] == ["published_at"]


def test_write_source_types_do_not_include_unknown():
    data = _load()
    assert "unknown" not in data["source_types"]
    assert set(data["source_types"]) == {
        "rss", "telegram", "gdelt", "notebooklm", "dataset",
    }
