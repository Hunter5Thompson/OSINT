import hashlib
import json
from pathlib import Path
from typing import Literal
from urllib.parse import quote

from app.models.recon import ReconManifest, ReconScene


class ReconManifestMissingError(FileNotFoundError):
    """Raised when the recon manifest JSON cannot be located on disk."""


class ReconManifestLoader:
    def __init__(self, path: Path):
        self._path = Path(path)
        self._by_id: dict[str, ReconScene] = {}
        self._loaded = False
        self.disabled_reason: Literal["not_configured", "operator_disabled"] | None = None

    def load(self, assets_dir: Path | None = None) -> None:
        self._loaded = False
        self._by_id = {}
        self.disabled_reason = None
        if not self._path.exists():
            raise ReconManifestMissingError(str(self._path))
        raw = json.loads(self._path.read_text())
        manifest = ReconManifest.model_validate(raw)
        if assets_dir is not None:
            directory = assets_dir.resolve()
            for scene in manifest.scenes:
                asset = (directory / scene.hf_filename).resolve()
                if asset.parent != directory or not asset.is_file():
                    raise ValueError("Recon scene asset is missing or outside its directory")
                expected_url = (
                    f"/static/recon/{quote(scene.hf_filename, safe='')}?sha={scene.ply_sha256}"
                )
                if scene.ply_url != expected_url:
                    raise ValueError("Recon scene URL does not address its local asset")
                if asset.stat().st_size != scene.ply_size_bytes:
                    raise ValueError("Recon scene asset size does not match the manifest")
                digest = hashlib.sha256()
                with asset.open("rb") as handle:
                    while chunk := handle.read(1024 * 1024):
                        digest.update(chunk)
                if digest.hexdigest() != scene.ply_sha256:
                    raise ValueError("Recon scene asset hash does not match the manifest")
        self._by_id = {s.scene_id: s for s in manifest.scenes}
        self._loaded = True

    @property
    def is_loaded(self) -> bool:
        return self._loaded

    def get_scene(self, scene_id: str) -> ReconScene | None:
        return self._by_id.get(scene_id)

    def list_scenes(self) -> list[ReconScene]:
        return list(self._by_id.values())
