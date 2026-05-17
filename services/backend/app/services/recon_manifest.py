import json
from pathlib import Path

from app.models.recon import ReconManifest, ReconScene


class ReconManifestMissingError(FileNotFoundError):
    """Raised when the recon manifest JSON cannot be located on disk."""


class ReconManifestLoader:
    def __init__(self, path: Path):
        self._path = Path(path)
        self._by_id: dict[str, ReconScene] = {}
        self._loaded = False

    def load(self) -> None:
        if not self._path.exists():
            raise ReconManifestMissingError(str(self._path))
        raw = json.loads(self._path.read_text())
        manifest = ReconManifest.model_validate(raw)
        self._by_id = {s.scene_id: s for s in manifest.scenes}
        self._loaded = True

    @property
    def is_loaded(self) -> bool:
        return self._loaded

    def get_scene(self, scene_id: str) -> ReconScene | None:
        return self._by_id.get(scene_id)

    def list_scenes(self) -> list[ReconScene]:
        return list(self._by_id.values())
