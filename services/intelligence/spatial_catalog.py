"""Local, server-owned resolver for internal spatial query references."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from spatial import SpatialScopeTokenV1

_CATALOG_REVISION = re.compile(r"^spatial-v[0-9]+-[a-f0-9]{12,64}$")
_SCOPE_KEY = re.compile(r"^[A-Za-z0-9:._-]{1,128}$")
_POINTER_NAME = "catalog-pointer.json"


class SpatialScopeRefV1(BaseModel):
    """The only spatial identity accepted from the backend transport."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    scope_key: str = Field(min_length=1, max_length=128, pattern=_SCOPE_KEY.pattern)
    catalog_revision: str = Field(
        min_length=23,
        max_length=79,
        pattern=_CATALOG_REVISION.pattern,
    )


class SpatialCatalogResolutionError(RuntimeError):
    """A reference cannot be resolved through the installed served set."""


class _CatalogPointer(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    schema_version: Literal[1]
    active_catalog_revision: str = Field(pattern=_CATALOG_REVISION.pattern)
    served_catalog_revisions: tuple[str, ...] = Field(min_length=1, max_length=2)


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


class IntelligenceSpatialCatalog:
    """Resolve a minimal ref into immutable derivation data owned by the server."""

    def __init__(self, root: Path) -> None:
        self._root = Path(root)
        self._tokens: dict[tuple[str, str], SpatialScopeTokenV1] = {}
        self._active_revision: str | None = None

    @property
    def is_available(self) -> bool:
        return self._active_revision is not None

    def load(self) -> None:
        pointer_path = self._root / _POINTER_NAME
        pointer_bytes = pointer_path.read_bytes()
        pointer_value = json.loads(pointer_bytes)
        canonical_pointer = _canonical_json(pointer_value)
        if pointer_bytes not in {canonical_pointer, canonical_pointer + b"\n"}:
            raise SpatialCatalogResolutionError("catalog pointer is not canonical JSON")
        pointer = _CatalogPointer.model_validate_json(pointer_bytes)
        if pointer.served_catalog_revisions[0] != pointer.active_catalog_revision:
            raise SpatialCatalogResolutionError("catalog pointer active revision is not first")
        if len(set(pointer.served_catalog_revisions)) != len(
            pointer.served_catalog_revisions
        ):
            raise SpatialCatalogResolutionError("catalog pointer revisions are not unique")

        tokens: dict[tuple[str, str], SpatialScopeTokenV1] = {}
        for revision in pointer.served_catalog_revisions:
            directory = self._root / "catalogs" / revision
            if directory.is_symlink() or not directory.is_dir():
                raise SpatialCatalogResolutionError("served catalog directory is unavailable")
            manifest_bytes = (directory / "manifest.json").read_bytes()
            manifest = json.loads(manifest_bytes)
            if _canonical_json(manifest) != manifest_bytes:
                raise SpatialCatalogResolutionError("catalog manifest is not canonical JSON")
            if manifest.get("catalog_revision") != revision:
                raise SpatialCatalogResolutionError("catalog manifest revision mismatch")
            boundary_policy = manifest.get("boundary_policy")
            scopes = manifest.get("scopes")
            if not isinstance(boundary_policy, str) or not isinstance(scopes, list):
                raise SpatialCatalogResolutionError("catalog manifest shape is invalid")
            for record in scopes:
                if not isinstance(record, dict) or not isinstance(record.get("scope"), dict):
                    raise SpatialCatalogResolutionError("catalog scope record is invalid")
                scope = record["scope"]
                token = SpatialScopeTokenV1.model_validate_json(_canonical_json({
                    "scope_key": scope.get("key"),
                    "kind": scope.get("kind"),
                    "catalog_revision": revision,
                    "derivation_revision": record.get("derivation_revision"),
                    "boundary_policy": boundary_policy,
                    "compatible_derivation_revisions": record.get(
                        "compatible_derivation_revisions"
                    ),
                }))
                identity = (revision, token.scope_key)
                if identity in tokens:
                    raise SpatialCatalogResolutionError("duplicate catalog scope identity")
                tokens[identity] = token

        self._tokens = tokens
        self._active_revision = pointer.active_catalog_revision

    def resolve(self, reference: SpatialScopeRefV1) -> SpatialScopeTokenV1:
        if self._active_revision is None:
            raise SpatialCatalogResolutionError("spatial catalog is unavailable")
        try:
            return self._tokens[(reference.catalog_revision, reference.scope_key)]
        except KeyError as exc:
            raise SpatialCatalogResolutionError(
                "spatial scope or served revision is unavailable"
            ) from exc


__all__ = [
    "IntelligenceSpatialCatalog",
    "SpatialCatalogResolutionError",
    "SpatialScopeRefV1",
]
