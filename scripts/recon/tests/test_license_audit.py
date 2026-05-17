import pytest
from pathlib import Path
from scripts.recon.license_audit import (
    LicenseUnverifiedError,
    resolve_attribution,
    load_license_records,
)


def _seed_records(tmp_path: Path) -> Path:
    import json
    licenses_dir = tmp_path / "licenses"
    licenses_dir.mkdir()
    (licenses_dir / "spacenet-4.txt").write_text("REAL UPSTREAM LICENSE TEXT FOR SPACENET 4\n...")
    (licenses_dir / "spacenet-2.txt").write_text("")  # intentionally empty
    (licenses_dir / "records.json").write_text(json.dumps({
        "records": {
            "SpaceNet 4": {
                "slug": "spacenet-4",
                "spdx": "CC-BY-SA-4.0",
                "upstream_url": "https://spacenet.ai/off-nadir-building-detection/",
                "verified_by": "RT",
                "verified_at": "2026-05-17",
            }
        }
    }))
    return licenses_dir


def test_resolve_attribution_passes_for_fully_verified_source(tmp_path):
    base = _seed_records(tmp_path)
    text = resolve_attribution(source_group="SpaceNet 4", licenses_dir=base)
    assert "Skyfall-GS" in text
    assert "Apache 2.0" in text
    assert "SpaceNet 4" in text
    assert "CC-BY-SA-4.0" in text
    assert "verified" in text.lower()


def test_resolve_attribution_fails_when_license_file_empty(tmp_path):
    import json
    base = _seed_records(tmp_path)
    # SpaceNet 2 has empty license text; add a record too so only the empty file fails
    payload = json.loads((base / "records.json").read_text())
    payload["records"]["SpaceNet 2"] = {
        "slug": "spacenet-2",
        "spdx": "CC-BY-SA-4.0",
        "upstream_url": "https://spacenet.ai/spacenet-buildings-dataset-v2/",
        "verified_by": "RT",
        "verified_at": "2026-05-17",
    }
    (base / "records.json").write_text(json.dumps(payload))
    with pytest.raises(LicenseUnverifiedError, match="empty license file"):
        resolve_attribution(source_group="SpaceNet 2", licenses_dir=base)


def test_resolve_attribution_fails_when_no_record(tmp_path):
    base = _seed_records(tmp_path)
    with pytest.raises(LicenseUnverifiedError, match="no record"):
        resolve_attribution(source_group="SpaceNet 2", licenses_dir=base)


def test_resolve_attribution_fails_for_unknown_source(tmp_path):
    base = _seed_records(tmp_path)
    with pytest.raises(LicenseUnverifiedError):
        resolve_attribution(source_group="Made Up Dataset", licenses_dir=base)


def test_load_license_records_returns_dict(tmp_path):
    base = _seed_records(tmp_path)
    records = load_license_records(base)
    assert "SpaceNet 4" in records
    assert records["SpaceNet 4"]["spdx"] == "CC-BY-SA-4.0"
