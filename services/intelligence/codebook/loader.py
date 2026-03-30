"""Load and validate the event codebook YAML."""

from __future__ import annotations

from pathlib import Path
import yaml


_DEFAULT_PATH = Path(__file__).parent / "event_codebook.yaml"


def load_codebook(path: Path | None = None) -> dict:
    """Load the event codebook from YAML."""
    p = path or _DEFAULT_PATH
    with open(p) as f:
        return yaml.safe_load(f)


def get_all_event_types(codebook: dict) -> list[str]:
    """Flatten the codebook hierarchy into a sorted list of dotted type strings."""
    types = []
    for category in codebook.get("categories", {}).values():
        for entry in category.get("types", []):
            types.append(entry["type"])
    return sorted(types)


def validate_codebook(codebook: dict) -> None:
    """Validate codebook structure. Raises ValueError on failure."""
    if "version" not in codebook:
        raise ValueError("Codebook missing 'version' key")
    if "categories" not in codebook:
        raise ValueError("Codebook missing 'categories' key")
    all_types = get_all_event_types(codebook)
    if len(all_types) < 50:
        raise ValueError(f"Codebook has {len(all_types)} types, need >= 50")
    if "other.unclassified" not in all_types:
        raise ValueError("Codebook missing 'other.unclassified' fallback type")
