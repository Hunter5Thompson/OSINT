"""Async, local-only runtime access to reviewed spatial catalog revisions."""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import math
import re
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import structlog
from pydantic import ValidationError

from app.models.spatial import (
    CatalogAttribution,
    CatalogManifest,
    CatalogPointer,
    CatalogProblemCode,
    ManifestScope,
    ScopeKind,
    ScopeNode,
    SourceLock,
    SourceLockRecord,
    SpatialCatalogProblem,
    canonical_json_bytes,
    iter_manifest_descriptors,
    parse_scope_key,
    validate_asset_id_candidate,
    validate_catalog_revision_candidate,
)

_CATALOG_DIRECTORY = re.compile(r"^spatial-v[0-9]+-[a-f0-9]{12,64}$")
_logger = structlog.get_logger()
_GENERIC_UNAVAILABLE = SpatialCatalogProblem(
    code=CatalogProblemCode.CATALOG_UNAVAILABLE,
    message="Spatial catalog is unavailable",
    recoverable=True,
)


def _read_file(path: Path) -> bytes:
    return path.read_bytes()


def _emit_structured_event(event: str, fields: dict[str, object]) -> None:
    _logger.info(event, **fields)


@dataclass(frozen=True, slots=True)
class AttributionProjectionSource:
    source_id: str
    release: str
    license_id: str
    text: str


@dataclass(frozen=True, slots=True)
class AttributionProjection:
    catalog_revision: str
    representation_note: str
    sources: tuple[AttributionProjectionSource, ...]


@dataclass(frozen=True, slots=True)
class CatalogBootstrap:
    active_catalog_revision: str
    served_catalog_revisions: tuple[str, ...]
    boundary_policy: str
    root_scope_key: str
    max_enabled_kind: ScopeKind
    attributions: tuple[AttributionProjection, ...]


@dataclass(frozen=True, slots=True)
class ResolvedSpatialScope:
    catalog_revision: str
    boundary_policy: str
    canonicalized_from: str | None
    record: ManifestScope
    path: tuple[ScopeNode, ...]
    children: tuple[ScopeNode, ...]


@dataclass(frozen=True, slots=True)
class IncidentSpatialProjection:
    spatial_catalog_revision: str
    spatial_derivation_revision: str | None
    country_scope_key: str | None
    admin1_scope_key: str | None
    admin2_scope_key: str | None
    spatial_basis: str | None
    spatial_precision: str | None
    spatial_conflict: bool
    spatial_conflict_scope_keys: tuple[str, ...]
    spatial_derivation_status: str


@dataclass(frozen=True, slots=True)
class SpatialAsset:
    """Manifest-owned file identity; callers never supply its filesystem path."""

    catalog_revision: str
    asset_id: str
    media_type: str
    byte_length: int
    _path: Path = field(repr=False, compare=False)


@dataclass(frozen=True, slots=True)
class CatalogReadyState:
    active_catalog_revision: str
    served_catalog_revisions: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CatalogUnavailableState:
    problem: SpatialCatalogProblem


type CatalogState = CatalogReadyState | CatalogUnavailableState
type ScopeLookup = ManifestScope | SpatialCatalogProblem
type AssetLookup = SpatialAsset | SpatialCatalogProblem
type AssetRead = bytes | SpatialCatalogProblem
type CatalogBootstrapLookup = CatalogBootstrap | SpatialCatalogProblem
type ResolveLookup = ResolvedSpatialScope | SpatialCatalogProblem
type FileReader = Callable[[Path], bytes]
type MonotonicClock = Callable[[], float]
type EventSink = Callable[[str, dict[str, object]], None]


@dataclass(frozen=True, slots=True)
class _LoadedCatalog:
    directory: Path
    manifest: CatalogManifest
    scopes: dict[str, ManifestScope]
    assets: dict[str, SpatialAsset]
    attribution: AttributionProjection


class SpatialCatalogLoader:
    """Load at most the active and previous immutable local catalog revisions."""

    def __init__(
        self,
        path: Path,
        *,
        asset_max_concurrency: int = 8,
        asset_acquire_timeout_s: float = 0.05,
        file_reader: FileReader = _read_file,
        monotonic: MonotonicClock = time.monotonic,
        event_sink: EventSink = _emit_structured_event,
    ) -> None:
        if (
            isinstance(asset_max_concurrency, bool)
            or not isinstance(asset_max_concurrency, int)
            or not 1 <= asset_max_concurrency <= 64
        ):
            raise ValueError("asset_max_concurrency must be between 1 and 64")
        if (
            isinstance(asset_acquire_timeout_s, bool)
            or not isinstance(asset_acquire_timeout_s, (int, float))
            or not math.isfinite(asset_acquire_timeout_s)
            or not 0 < asset_acquire_timeout_s <= 5
        ):
            raise ValueError("asset_acquire_timeout_s must be greater than 0 and at most 5")
        self._path = Path(path)
        self._asset_semaphore = asyncio.Semaphore(asset_max_concurrency)
        self._asset_acquire_timeout_s = float(asset_acquire_timeout_s)
        self._file_reader = file_reader
        self._monotonic = monotonic
        self._event_sink = event_sink
        self._inflight_file_reads: set[asyncio.Task[bytes]] = set()
        self._catalogs: dict[str, _LoadedCatalog] = {}
        self._state: CatalogState = CatalogUnavailableState(_GENERIC_UNAVAILABLE)
        self._verified_assets: set[tuple[str, str]] = set()
        self._containment_cache: dict[
            tuple[str, str],
            tuple[tuple[tuple[tuple[float, float], ...], ...], ...],
        ] = {}
        self._diagnostic: str | None = None

    @property
    def state(self) -> CatalogState:
        return self._state

    @property
    def is_available(self) -> bool:
        return isinstance(self._state, CatalogReadyState)

    @property
    def verified_asset_count(self) -> int:
        return len(self._verified_assets)

    @property
    def diagnostic(self) -> str | None:
        """Server-internal load diagnostic; never serialize this into HTTP."""

        return self._diagnostic

    async def load(self) -> CatalogState:
        """Validate local metadata and indexes without blocking the event loop."""

        started = self._monotonic()
        try:
            loaded = await asyncio.to_thread(self._load_sync)
        except (OSError, UnicodeError, ValueError, ValidationError) as exc:
            self._catalogs.clear()
            self._verified_assets.clear()
            self._containment_cache.clear()
            self._diagnostic = f"{type(exc).__name__}: {exc}"
            self._state = CatalogUnavailableState(_GENERIC_UNAVAILABLE)
            self._emit(
                "spatial_catalog_readiness",
                cause="unavailable",
                duration_ms=self._duration_ms(started),
                cache_status="empty",
            )
            return self._state

        self._catalogs = {catalog.manifest.catalog_revision: catalog for catalog in loaded}
        self._verified_assets.clear()
        self._containment_cache.clear()
        self._diagnostic = None
        revisions = tuple(catalog.manifest.catalog_revision for catalog in loaded)
        self._state = CatalogReadyState(
            active_catalog_revision=revisions[0],
            served_catalog_revisions=revisions,
        )
        self._emit(
            "spatial_catalog_readiness",
            catalog_revision=revisions[0],
            cause="ready",
            duration_ms=self._duration_ms(started),
            cache_status="loaded",
        )
        return self._state

    async def close(self) -> None:
        """Dispose all immutable verification and lookup caches."""

        if self._inflight_file_reads:
            await asyncio.gather(*tuple(self._inflight_file_reads), return_exceptions=True)
        self._catalogs.clear()
        self._verified_assets.clear()
        self._containment_cache.clear()
        self._diagnostic = None
        self._state = CatalogUnavailableState(_GENERIC_UNAVAILABLE)

    def bootstrap(self) -> CatalogBootstrapLookup:
        if not isinstance(self._state, CatalogReadyState):
            return _GENERIC_UNAVAILABLE
        catalogs = tuple(
            self._catalogs[revision] for revision in self._state.served_catalog_revisions
        )
        active = catalogs[0]
        return CatalogBootstrap(
            active_catalog_revision=self._state.active_catalog_revision,
            served_catalog_revisions=self._state.served_catalog_revisions,
            boundary_policy=active.manifest.boundary_policy,
            root_scope_key=active.manifest.root_scope_key,
            max_enabled_kind=_max_scope_kind(active.manifest),
            attributions=tuple(catalog.attribution for catalog in catalogs),
        )

    def resolve_scope(
        self,
        scope_key: str | None,
        catalog_revision: str | None,
    ) -> ResolveLookup:
        started = self._monotonic()
        try:
            if scope_key is None:
                raise ValueError("INVALID_SCOPE_KEY")
            parsed = parse_scope_key(scope_key)
        except (TypeError, ValueError):
            self._emit(
                "spatial_catalog_resolve",
                cause="invalid_scope_key",
                duration_ms=self._duration_ms(started),
                cache_status="rejected",
            )
            return SpatialCatalogProblem(
                code=CatalogProblemCode.INVALID_SCOPE_KEY,
                message="Invalid spatial scope key",
                recoverable=False,
                active_catalog_revision=self._active_revision(),
            )

        revision = catalog_revision
        if revision is not None:
            try:
                revision = validate_catalog_revision_candidate(revision)
            except ValueError:
                self._emit(
                    "spatial_catalog_resolve",
                    scope_key=parsed.canonical,
                    cause="invalid_catalog_revision",
                    duration_ms=self._duration_ms(started),
                    cache_status="rejected",
                )
                return SpatialCatalogProblem(
                    code=CatalogProblemCode.INVALID_CATALOG_REVISION,
                    message="Invalid spatial catalog revision",
                    recoverable=False,
                    active_catalog_revision=self._active_revision(),
                )

        if not isinstance(self._state, CatalogReadyState):
            self._emit(
                "spatial_catalog_resolve",
                scope_key=parsed.canonical,
                cause="catalog_unavailable",
                duration_ms=self._duration_ms(started),
                cache_status="unavailable",
            )
            return _GENERIC_UNAVAILABLE
        selected_revision = revision or self._state.active_catalog_revision
        catalog = self._catalogs.get(selected_revision)
        if catalog is None:
            self._emit(
                "spatial_catalog_resolve",
                scope_key=parsed.canonical,
                catalog_revision=selected_revision,
                cause="revision_unavailable",
                duration_ms=self._duration_ms(started),
                cache_status="miss",
            )
            return self._revision_problem(selected_revision)
        record = catalog.scopes.get(parsed.canonical)
        if record is None:
            self._emit(
                "spatial_catalog_resolve",
                scope_key=parsed.canonical,
                catalog_revision=selected_revision,
                cause="unknown_scope",
                duration_ms=self._duration_ms(started),
                cache_status="miss",
            )
            return SpatialCatalogProblem(
                code=CatalogProblemCode.UNKNOWN_SCOPE,
                message="Spatial scope was not found",
                target=parsed.canonical,
                recoverable=False,
                active_catalog_revision=self._active_revision(),
            )
        resolved = ResolvedSpatialScope(
            catalog_revision=selected_revision,
            boundary_policy=catalog.manifest.boundary_policy,
            canonicalized_from=(scope_key if parsed.canonical != scope_key else None),
            record=record,
            path=tuple(catalog.scopes[key].scope for key in record.path),
            children=tuple(sorted(
                (
                    candidate.scope
                    for candidate in catalog.scopes.values()
                    if candidate.scope.parent_key == record.scope.key
                ),
                key=lambda child: (child.label.casefold(), child.key),
            )),
        )
        self._emit(
            "spatial_catalog_resolve",
            scope_key=parsed.canonical,
            catalog_revision=selected_revision,
            cause="resolved",
            duration_ms=self._duration_ms(started),
            cache_status="hit",
        )
        return resolved

    def resolve_country_identifiers(
        self,
        identifiers: Sequence[str],
        catalog_revision: str | None = None,
    ) -> ResolveLookup:
        """Resolve a validated Almanac identity against catalog-owned country keys."""

        normalized = {
            value.strip().casefold()
            for value in identifiers
            if isinstance(value, str) and 0 < len(value.strip().encode("utf-8")) <= 128
        }
        if not normalized:
            return SpatialCatalogProblem(
                code=CatalogProblemCode.INVALID_SCOPE_KEY,
                message="Invalid country identity",
                recoverable=False,
                active_catalog_revision=self._active_revision(),
            )
        if not isinstance(self._state, CatalogReadyState):
            return _GENERIC_UNAVAILABLE
        revision = catalog_revision or self._state.active_catalog_revision
        try:
            revision = validate_catalog_revision_candidate(revision)
        except ValueError:
            return SpatialCatalogProblem(
                code=CatalogProblemCode.INVALID_CATALOG_REVISION,
                message="Invalid spatial catalog revision",
                recoverable=False,
                active_catalog_revision=self._active_revision(),
            )
        catalog = self._catalogs.get(revision)
        if catalog is None:
            return self._revision_problem(revision)

        matches = []
        for record in catalog.scopes.values():
            parsed = parse_scope_key(record.scope.key)
            if (
                parsed.kind is ScopeKind.COUNTRY
                and parsed.canonical_code is not None
                and parsed.canonical_code.casefold() in normalized
            ):
                matches.append(record.scope.key)
        if len(matches) != 1:
            return SpatialCatalogProblem(
                code=CatalogProblemCode.UNKNOWN_SCOPE,
                message="Country identity has no unique spatial scope",
                recoverable=False,
                active_catalog_revision=self._active_revision(),
            )
        return self.resolve_scope(matches[0], revision)

    def get_asset_by_id(self, asset_id: str) -> AssetLookup:
        try:
            validated = validate_asset_id_candidate(asset_id)
        except ValueError:
            return SpatialCatalogProblem(
                code=CatalogProblemCode.INVALID_ASSET_ID,
                message="Invalid spatial asset ID",
                recoverable=False,
                active_catalog_revision=self._active_revision(),
            )
        if not isinstance(self._state, CatalogReadyState):
            return _GENERIC_UNAVAILABLE
        for revision in self._state.served_catalog_revisions:
            asset = self._catalogs[revision].assets.get(validated)
            if asset is not None:
                return asset
        return SpatialCatalogProblem(
            code=CatalogProblemCode.UNKNOWN_ASSET,
            message="Spatial asset was not found",
            target=validated,
            recoverable=False,
            active_catalog_revision=self._active_revision(),
        )

    def get_scope(self, catalog_revision: str, scope_key: str) -> ScopeLookup:
        catalog = self._catalogs.get(catalog_revision)
        if catalog is None:
            return self._revision_problem(catalog_revision)
        scope = catalog.scopes.get(scope_key)
        if scope is None:
            return SpatialCatalogProblem(
                code=CatalogProblemCode.UNKNOWN_SCOPE,
                message="Spatial scope was not found",
                target=scope_key,
                recoverable=False,
                active_catalog_revision=self._active_revision(),
            )
        return scope

    def get_asset(self, catalog_revision: str, asset_id: str) -> AssetLookup:
        catalog = self._catalogs.get(catalog_revision)
        if catalog is None:
            return self._revision_problem(catalog_revision)
        asset = catalog.assets.get(asset_id)
        if asset is None:
            return SpatialCatalogProblem(
                code=CatalogProblemCode.UNKNOWN_ASSET,
                message="Spatial asset was not found",
                target=asset_id,
                recoverable=False,
                active_catalog_revision=self._active_revision(),
            )
        return asset

    async def project_incident_point(
        self,
        *,
        latitude: float,
        longitude: float,
    ) -> IncidentSpatialProjection | SpatialCatalogProblem:
        """Project one precise incident point through the active immutable catalog."""

        if (
            not math.isfinite(latitude)
            or not math.isfinite(longitude)
            or not -90 <= latitude <= 90
            or not -180 <= longitude <= 180
        ):
            raise ValueError("incident coordinate is outside the geographic domain")
        if not isinstance(self._state, CatalogReadyState):
            return _GENERIC_UNAVAILABLE
        revision = self._state.active_catalog_revision
        catalog = self._catalogs[revision]
        matches: dict[str, bool] = {}
        for record in catalog.scopes.values():
            if record.scope.kind is ScopeKind.WORLD:
                continue
            geometry = await self._containment_geometry(catalog, record)
            if isinstance(geometry, SpatialCatalogProblem):
                return geometry
            if geometry is None:
                continue
            on_boundary, inside = _classify_point(
                geometry,
                longitude=longitude,
                latitude=latitude,
            )
            if on_boundary or inside:
                matches[record.scope.key] = on_boundary

        terminal = tuple(sorted(
            scope_key
            for scope_key in matches
            if not any(
                scope_key in catalog.scopes[other].path[:-1]
                for other in matches
                if other != scope_key
            )
        ))
        selected: str | None
        conflicts: tuple[str, ...]
        if len(terminal) == 1 and not matches[terminal[0]]:
            selected = terminal[0]
            conflicts = ()
        elif len(terminal) == 1:
            parent = catalog.scopes[terminal[0]].scope.parent_key
            selected = None if parent == "world" else parent
            conflicts = terminal
        elif terminal:
            lineages = tuple(catalog.scopes[key].path for key in terminal)
            common: str | None = None
            for candidates in zip(*lineages, strict=False):
                if len(set(candidates)) != 1:
                    break
                common = candidates[0]
            selected = None if common == "world" else common
            conflicts = terminal
        else:
            selected = None
            conflicts = ()

        lineage = catalog.scopes[selected].path if selected is not None else ()
        by_kind = {
            catalog.scopes[key].scope.kind: key
            for key in lineage
            if key != "world"
        }
        return IncidentSpatialProjection(
            spatial_catalog_revision=revision,
            spatial_derivation_revision=(
                catalog.scopes[selected].derivation_revision
                if selected is not None and not conflicts
                else None
            ),
            country_scope_key=by_kind.get(ScopeKind.COUNTRY),
            admin1_scope_key=by_kind.get(ScopeKind.ADMIN1),
            admin2_scope_key=by_kind.get(ScopeKind.ADMIN2),
            spatial_basis="coordinate" if selected is not None else None,
            spatial_precision="point",
            spatial_conflict=bool(conflicts),
            spatial_conflict_scope_keys=conflicts,
            spatial_derivation_status=(
                "conflict" if conflicts else "resolved" if selected is not None else "unresolved"
            ),
        )

    async def _containment_geometry(
        self,
        catalog: _LoadedCatalog,
        record: ManifestScope,
    ) -> tuple[tuple[tuple[tuple[float, float], ...], ...], ...] | None | SpatialCatalogProblem:
        descriptor = record.presentation.containment
        if descriptor is None:
            return None
        key = (catalog.manifest.catalog_revision, descriptor.asset_id)
        cached = self._containment_cache.get(key)
        if cached is not None:
            return cached
        asset = catalog.assets[descriptor.asset_id]
        payload = await self.read_asset(asset)
        if isinstance(payload, SpatialCatalogProblem):
            return payload
        try:
            geometry = _decode_containment_geometry(payload)
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            return self._asset_corrupt(exc)
        self._containment_cache[key] = geometry
        return geometry

    def get_catalog(self, catalog_revision: str) -> _LoadedCatalog | SpatialCatalogProblem:
        catalog = self._catalogs.get(catalog_revision)
        if catalog is None:
            return self._revision_problem(catalog_revision)
        return catalog

    async def read_asset(self, asset: SpatialAsset) -> AssetRead:
        """Read and lazily hash an indexed asset; an injected path is never honored."""

        indexed = self.get_asset(asset.catalog_revision, asset.asset_id)
        if not isinstance(indexed, SpatialAsset):
            return indexed
        started = self._monotonic()
        try:
            await asyncio.wait_for(
                self._asset_semaphore.acquire(),
                timeout=self._asset_acquire_timeout_s,
            )
        except TimeoutError:
            self._emit(
                "spatial_asset_rejected_busy",
                catalog_revision=indexed.catalog_revision,
                cause="asset_semaphore_timeout",
                duration_ms=self._duration_ms(started),
                cache_status="rejected",
            )
            return SpatialCatalogProblem(
                code=CatalogProblemCode.ASSET_BUSY,
                message="Spatial asset reader is busy",
                target=indexed.asset_id,
                recoverable=True,
                active_catalog_revision=self._active_revision(),
            )

        try:
            read_task = asyncio.create_task(
                asyncio.to_thread(self._file_reader, indexed._path),
                name=f"spatial-asset-{indexed.asset_id[:12]}",
            )
            self._inflight_file_reads.add(read_task)
            try:
                payload = await asyncio.shield(read_task)
            except asyncio.CancelledError:
                await _wait_for_file_read_after_cancellation(read_task)
                self._emit(
                    "spatial_asset_load",
                    catalog_revision=indexed.catalog_revision,
                    cause="cancelled",
                    duration_ms=self._duration_ms(started),
                    cache_status="cancelled",
                )
                raise
            except OSError:
                return self._asset_io_unavailable(indexed)
            finally:
                self._inflight_file_reads.discard(read_task)

            if len(payload) != indexed.byte_length:
                return self._asset_corrupt(ValueError("asset byte length changed"))

            cache_key = (indexed.catalog_revision, indexed.asset_id)
            cache_status = "hit" if cache_key in self._verified_assets else "miss"
            if cache_key not in self._verified_assets:
                if _sha256_bytes(payload) != indexed.asset_id:
                    return self._asset_corrupt(ValueError("asset hash mismatch"))
                self._verified_assets.add(cache_key)
                self._emit(
                    "spatial_asset_hash_verified",
                    catalog_revision=indexed.catalog_revision,
                    cause="sha256_match",
                    duration_ms=self._duration_ms(started),
                    cache_status="miss",
                )
            self._emit(
                "spatial_asset_load",
                catalog_revision=indexed.catalog_revision,
                cause="served",
                duration_ms=self._duration_ms(started),
                cache_status=cache_status,
            )
            return payload
        finally:
            self._asset_semaphore.release()

    def _load_sync(self) -> tuple[_LoadedCatalog, ...]:
        directories = self._discover_served_directories()
        source_lock_path = self._source_lock_path(directories[0])
        source_lock = SourceLock.model_validate_json(source_lock_path.read_bytes())
        source_by_id = {source.source_id: source for source in source_lock.sources}
        loaded = tuple(self._load_catalog(directory) for directory in directories)
        _validate_active_source_lock(loaded[0], source_by_id=source_by_id)
        _validate_cross_catalog_assets(loaded)
        return loaded

    def _discover_served_directories(self) -> tuple[Path, ...]:
        if (self._path / "manifest.json").is_file():
            if self._path.is_symlink():
                raise ValueError("catalog directory must not be a symlink")
            return (self._path,)

        catalogs_root = self._path / "catalogs"
        if not catalogs_root.is_dir():
            raise FileNotFoundError("spatial catalog directory is missing")
        pointer_path = self._path / "catalog-pointer.json"
        if pointer_path.is_symlink() or not pointer_path.is_file():
            raise FileNotFoundError("spatial catalog pointer is missing")
        pointer_bytes = pointer_path.read_bytes()
        pointer = CatalogPointer.model_validate_json(pointer_bytes)
        canonical_pointer = canonical_json_bytes(pointer)
        if pointer_bytes not in {canonical_pointer, canonical_pointer + b"\n"}:
            raise ValueError("catalog pointer is not canonical JSON")
        directories: list[Path] = []
        for revision in pointer.served_catalog_revisions:
            candidate = catalogs_root / revision
            if (
                not _CATALOG_DIRECTORY.fullmatch(candidate.name)
                or candidate.is_symlink()
                or not candidate.is_dir()
            ):
                raise ValueError("served catalog revision is not installed")
            directories.append(candidate)
        return tuple(directories)

    def _source_lock_path(self, catalog_directory: Path) -> Path:
        candidates = (
            self._path / "source-lock.json",
            catalog_directory.parent / "source-lock.json",
            catalog_directory.parent.parent / "source-lock.json",
        )
        for candidate in candidates:
            if candidate.is_file() and not candidate.is_symlink():
                return candidate
        raise FileNotFoundError("spatial source lock is missing")

    def _load_catalog(
        self,
        directory: Path,
    ) -> _LoadedCatalog:
        manifest_path = directory / "manifest.json"
        manifest_bytes = manifest_path.read_bytes()
        manifest = CatalogManifest.model_validate_json(manifest_bytes)
        if canonical_json_bytes(manifest) != manifest_bytes:
            raise ValueError("manifest is not canonical JSON")
        if directory.name != manifest.catalog_revision:
            raise ValueError("catalog directory and manifest revision differ")

        attribution_path = directory / "attribution.json"
        attribution_bytes = attribution_path.read_bytes()
        attribution = CatalogAttribution.model_validate_json(attribution_bytes)
        if canonical_json_bytes(attribution) != attribution_bytes:
            raise ValueError("attribution is not canonical JSON")
        if attribution.catalog_revision != manifest.catalog_revision:
            raise ValueError("attribution and manifest revision differ")
        attribution_sources_sha256 = _sha256_bytes(
            canonical_json_bytes(attribution.sources)
        )
        if attribution_sources_sha256 != manifest.attribution_sources_sha256:
            raise ValueError("attribution sources do not match manifest hash")
        projection = _project_attribution(
            attribution,
            manifest=manifest,
        )

        descriptor_by_id: dict[str, tuple[str, int]] = {}
        for descriptor in iter_manifest_descriptors(manifest):
            identity = (descriptor.media_type, descriptor.byte_length)
            existing = descriptor_by_id.setdefault(descriptor.asset_id, identity)
            if existing != identity:
                raise ValueError("one asset has conflicting descriptors")

        assets_dir = directory / "assets"
        if assets_dir.is_symlink() or not assets_dir.is_dir():
            raise ValueError("catalog assets path must be a regular directory")
        expected_names = {f"{asset_id}.json" for asset_id in manifest.assets}
        actual_entries = tuple(assets_dir.iterdir())
        actual_names = {entry.name for entry in actual_entries}
        if actual_names != expected_names:
            raise ValueError("catalog assets do not match manifest declarations")

        assets_root = assets_dir.resolve(strict=True)
        assets: dict[str, SpatialAsset] = {}
        for asset_id in manifest.assets:
            path = assets_dir / f"{asset_id}.json"
            if path.is_symlink() or not path.is_file():
                raise ValueError("catalog asset must be a regular file")
            resolved = path.resolve(strict=True)
            if resolved.parent != assets_root:
                raise ValueError("catalog asset path escapes its manifest directory")
            asset_metadata = descriptor_by_id.get(asset_id)
            if asset_metadata is None:
                raise ValueError("manifest asset has no descriptor")
            media_type, byte_length = asset_metadata
            if path.stat().st_size != byte_length:
                raise ValueError("catalog asset byte length differs from descriptor")
            assets[asset_id] = SpatialAsset(
                catalog_revision=manifest.catalog_revision,
                asset_id=asset_id,
                media_type=media_type,
                byte_length=byte_length,
                _path=path,
            )

        return _LoadedCatalog(
            directory=directory,
            manifest=manifest,
            scopes={record.scope.key: record for record in manifest.scopes},
            assets=assets,
            attribution=projection,
        )

    def _revision_problem(self, revision: str) -> SpatialCatalogProblem:
        if not self.is_available:
            return _GENERIC_UNAVAILABLE
        return SpatialCatalogProblem(
            code=CatalogProblemCode.CATALOG_REVISION_UNAVAILABLE,
            message="Requested spatial catalog revision is not served",
            target=revision,
            recoverable=True,
            active_catalog_revision=self._active_revision(),
        )

    def _asset_corrupt(self, exc: Exception) -> SpatialCatalogProblem:
        self._catalogs.clear()
        self._verified_assets.clear()
        self._containment_cache.clear()
        self._diagnostic = f"{type(exc).__name__}: {exc}"
        self._state = CatalogUnavailableState(_GENERIC_UNAVAILABLE)
        self._emit(
            "spatial_asset_hash_failed",
            cause=type(exc).__name__,
            cache_status="invalid",
        )
        return _GENERIC_UNAVAILABLE

    def _asset_io_unavailable(self, asset: SpatialAsset) -> SpatialCatalogProblem:
        self._emit(
            "spatial_asset_load",
            catalog_revision=asset.catalog_revision,
            cause="io_error",
            cache_status="error",
        )
        return SpatialCatalogProblem(
            code=CatalogProblemCode.CATALOG_UNAVAILABLE,
            message="Spatial asset is temporarily unavailable",
            target=asset.asset_id,
            recoverable=True,
            active_catalog_revision=self._active_revision(),
        )

    def _active_revision(self) -> str | None:
        if isinstance(self._state, CatalogReadyState):
            return self._state.active_catalog_revision
        return None

    def _duration_ms(self, started: float) -> float:
        return max(0.0, (self._monotonic() - started) * 1000.0)

    def _emit(self, event: str, **fields: object) -> None:
        try:
            self._event_sink(event, fields)
        except Exception:  # noqa: BLE001
            _logger.exception("spatial_observability_sink_failed", event=event)


def _project_attribution(
    attribution: CatalogAttribution,
    *,
    manifest: CatalogManifest,
) -> AttributionProjection:
    manifest_sources = _manifest_source_metadata(manifest)
    sources: list[AttributionProjectionSource] = []
    for item in attribution.sources:
        manifest_source = manifest_sources.get(item.source_id)
        if manifest_source is not None:
            release, license_id, text = manifest_source
            if (
                release != item.release
                or license_id != item.license_id
                or text != item.attribution
            ):
                raise ValueError("attribution does not match revision provenance")
        sources.append(
            AttributionProjectionSource(
                source_id=item.source_id,
                release=item.release,
                license_id=item.license_id,
                text=item.attribution,
            )
        )
    return AttributionProjection(
        catalog_revision=attribution.catalog_revision,
        representation_note="ODIN reference boundary representation",
        sources=tuple(sources),
    )


def _manifest_source_metadata(
    manifest: CatalogManifest,
) -> dict[str, tuple[str, str, str]]:
    sources: dict[str, tuple[str, str, str]] = {}
    for record in manifest.scopes:
        provenance = record.provenance
        metadata = (
            provenance.source_release,
            provenance.license_id,
            provenance.attribution,
        )
        existing = sources.setdefault(provenance.source_id, metadata)
        if existing != metadata:
            raise ValueError("one revision has conflicting source provenance")
    return sources


def _validate_active_source_lock(
    catalog: _LoadedCatalog,
    *,
    source_by_id: Mapping[str, SourceLockRecord],
) -> None:
    projected_by_id = {
        source.source_id: source for source in catalog.attribution.sources
    }
    if set(projected_by_id) != set(source_by_id):
        raise ValueError("active attribution source set differs from source lock")
    for projected in catalog.attribution.sources:
        source = source_by_id.get(projected.source_id)
        if source is None:
            raise ValueError("active attribution source is absent from source lock")
        expected = (source.release, source.license_id, source.attribution)
        actual = (projected.release, projected.license_id, projected.text)
        if actual != expected:
            raise ValueError("active attribution differs from source lock")


async def _wait_for_file_read_after_cancellation(read_task: asyncio.Task[bytes]) -> None:
    """Keep the semaphore slot until a shielded thread read really finishes."""

    while not read_task.done():
        try:
            await asyncio.shield(read_task)
        except asyncio.CancelledError:
            continue
        except Exception:  # the cancelled caller no longer consumes the result
            break
    if not read_task.cancelled():
        with contextlib.suppress(Exception):
            read_task.result()


def _decode_containment_geometry(
    payload: bytes,
) -> tuple[tuple[tuple[tuple[float, float], ...], ...], ...]:
    value = json.loads(payload)
    if not isinstance(value, dict) or set(value) != {
        "schema_version",
        "geometry_type",
        "polygons",
    }:
        raise ValueError("containment geometry shape is invalid")
    if value["schema_version"] != 1 or value["geometry_type"] != "MultiPolygon":
        raise ValueError("containment geometry version is unsupported")
    raw_polygons = value["polygons"]
    if not isinstance(raw_polygons, list) or not raw_polygons:
        raise ValueError("containment geometry polygons are invalid")
    polygons: list[tuple[tuple[tuple[float, float], ...], ...]] = []
    for raw_polygon in raw_polygons:
        if not isinstance(raw_polygon, list) or not raw_polygon:
            raise ValueError("containment polygon is invalid")
        rings: list[tuple[tuple[float, float], ...]] = []
        for raw_ring in raw_polygon:
            if not isinstance(raw_ring, list) or len(raw_ring) < 4:
                raise ValueError("containment ring is invalid")
            ring: list[tuple[float, float]] = []
            for raw_position in raw_ring:
                if (
                    not isinstance(raw_position, list)
                    or len(raw_position) != 2
                    or any(
                        isinstance(coordinate, bool)
                        or not isinstance(coordinate, int | float)
                        for coordinate in raw_position
                    )
                ):
                    raise ValueError("containment position is invalid")
                longitude, latitude = (float(raw_position[0]), float(raw_position[1]))
                if (
                    not math.isfinite(longitude)
                    or not math.isfinite(latitude)
                    or not -180 <= longitude <= 180
                    or not -90 <= latitude <= 90
                ):
                    raise ValueError("containment position is outside the geographic domain")
                ring.append((longitude, latitude))
            if ring[0] != ring[-1]:
                raise ValueError("containment ring is not closed")
            rings.append(tuple(ring))
        polygons.append(tuple(rings))
    return tuple(polygons)


def _classify_point(
    geometry: tuple[tuple[tuple[tuple[float, float], ...], ...], ...],
    *,
    longitude: float,
    latitude: float,
) -> tuple[bool, bool]:
    for polygon in geometry:
        outer_query, outer = _unwrap_ring(longitude, polygon[0])
        if _point_on_ring(outer_query, latitude, outer):
            return True, False
        if not _point_in_ring(outer_query, latitude, outer):
            continue
        inside_hole = False
        for hole in polygon[1:]:
            hole_query, unwrapped_hole = _unwrap_ring(longitude, hole)
            if _point_on_ring(hole_query, latitude, unwrapped_hole):
                return True, False
            if _point_in_ring(hole_query, latitude, unwrapped_hole):
                inside_hole = True
                break
        if not inside_hole:
            return False, True
    return False, False


def _unwrap_ring(
    query_longitude: float,
    ring: tuple[tuple[float, float], ...],
) -> tuple[float, tuple[tuple[float, float], ...]]:
    unwrapped = [ring[0]]
    for raw_longitude, latitude in ring[1:]:
        candidate = raw_longitude
        while candidate - unwrapped[-1][0] > 180:
            candidate -= 360
        while candidate - unwrapped[-1][0] < -180:
            candidate += 360
        unwrapped.append((candidate, latitude))
    mean = sum(point[0] for point in unwrapped[:-1]) / (len(unwrapped) - 1)
    query = query_longitude + round((mean - query_longitude) / 360) * 360
    return query, tuple(unwrapped)


def _point_in_ring(
    longitude: float,
    latitude: float,
    ring: tuple[tuple[float, float], ...],
) -> bool:
    inside = False
    for left, right in zip(ring, ring[1:], strict=False):
        crosses = (left[1] > latitude) != (right[1] > latitude)
        if crosses:
            crossing = left[0] + (latitude - left[1]) * (
                right[0] - left[0]
            ) / (right[1] - left[1])
            if longitude < crossing:
                inside = not inside
    return inside


def _point_on_ring(
    longitude: float,
    latitude: float,
    ring: tuple[tuple[float, float], ...],
) -> bool:
    for left, right in zip(ring, ring[1:], strict=False):
        cross = (longitude - left[0]) * (right[1] - left[1]) - (
            latitude - left[1]
        ) * (right[0] - left[0])
        if not math.isclose(cross, 0.0, abs_tol=1e-10):
            continue
        if (
            min(left[0], right[0]) - 1e-10 <= longitude <= max(left[0], right[0]) + 1e-10
            and min(left[1], right[1]) - 1e-10
            <= latitude
            <= max(left[1], right[1]) + 1e-10
        ):
            return True
    return False


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _max_scope_kind(manifest: CatalogManifest) -> ScopeKind:
    rank = {
        ScopeKind.WORLD: 0,
        ScopeKind.COUNTRY: 1,
        ScopeKind.ADMIN1: 2,
        ScopeKind.ADMIN2: 3,
    }
    return max((record.scope.kind for record in manifest.scopes), key=rank.__getitem__)


def _validate_cross_catalog_assets(catalogs: tuple[_LoadedCatalog, ...]) -> None:
    metadata_by_id: dict[str, tuple[str, int]] = {}
    for catalog in catalogs:
        for asset in catalog.assets.values():
            metadata = (asset.media_type, asset.byte_length)
            existing = metadata_by_id.setdefault(asset.asset_id, metadata)
            if existing != metadata:
                raise ValueError("shared content-addressed asset metadata differs by revision")
