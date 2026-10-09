"""Read immutable image metadata once; caller environment is not build provenance."""

import re
from pathlib import Path


def read_image_revision(path: Path) -> str | None:
    """Missing, invalid or development metadata is explicitly unknown."""
    try:
        with path.open("rb") as handle:
            raw = handle.read(129)
            if len(raw) > 128:
                return None
            value = raw.decode("ascii").strip()
    except (OSError, UnicodeError):
        return None
    return value if re.fullmatch(r"[0-9a-f]{40}", value) else None


BUILD_REVISION = read_image_revision(Path(__file__).resolve().parent / ".build-revision")
