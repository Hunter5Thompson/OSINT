import pytest

from gdelt_raw.cameo_mapping import map_cameo_root


@pytest.mark.parametrize("root,expected", [
    (14, "civil.protest"),
    (15, "posture.military"),
    (17, "conflict.coercion"),
    (18, "conflict.assault"),
    (19, "conflict.armed"),
    (20, "conflict.mass_violence"),
])
def test_mapped_roots(root, expected):
    assert map_cameo_root(root) == expected


@pytest.mark.parametrize("root", [1, 2, 13, 16, 99])
def test_unmapped_roots_return_none(root):
    assert map_cameo_root(root) is None


def test_all_allowlisted_roots_are_mapped():
    """The default allowlist {15,18,19,20} MUST have mappings — otherwise Events
    silently get codebook_type=None and become invisible to downstream tools."""
    from gdelt_raw.config import GDELTSettings
    s = GDELTSettings(_env_file=None)
    for root in s.cameo_root_allowlist:
        assert map_cameo_root(root) is not None, f"root {root} is allowlisted but unmapped"


def test_cameo_targets_subset_of_codebook_types():
    """Every CAMEO root must map to a type that exists in event_codebook.yaml.

    Without this guard, the GDELT collector silently writes codebook_types
    that the LLM prompt and downstream filters reject."""
    from pathlib import Path

    import yaml

    from gdelt_raw.cameo_mapping import CAMEO_ROOT_TO_CODEBOOK

    codebook_path = (
        Path(__file__).parents[2]
        / "intelligence"
        / "codebook"
        / "event_codebook.yaml"
    )
    codebook = yaml.safe_load(codebook_path.read_text())
    types = {
        entry["type"]
        for category in codebook["categories"].values()
        for entry in category["types"]
    }
    missing = set(CAMEO_ROOT_TO_CODEBOOK.values()) - types
    assert not missing, (
        f"CAMEO mapping references codebook types that don't exist: {missing}"
    )
