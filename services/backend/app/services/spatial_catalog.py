"""Async, local-only runtime access to reviewed spatial catalog revisions."""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import math
import re
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path

import structlog
from pydantic import ValidationError

from app.models.spatial import (
    CatalogAttribution,
    CatalogManifest,
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
        ordered = _order_loaded_catalogs(loaded)
        _validate_active_source_lock(ordered[0], source_by_id=source_by_id)
        _validate_cross_catalog_assets(ordered)
        return ordered

    def _discover_served_directories(self) -> tuple[Path, ...]:
        if (self._path / "manifest.json").is_file():
            if self._path.is_symlink():
                raise ValueError("catalog directory must not be a symlink")
            return (self._path,)

        catalogs_root = self._path / "catalogs"
        if not catalogs_root.is_dir():
            raise FileNotFoundError("spatial catalog directory is missing")
        candidates: list[Path] = []
        for candidate in catalogs_root.iterdir():
            if not _CATALOG_DIRECTORY.fullmatch(candidate.name):
                continue
            if candidate.is_symlink() or not candidate.is_dir():
                raise ValueError("catalog revision path must be a regular directory")
            candidates.append(candidate)
        if not candidates:
            raise FileNotFoundError("no spatial catalog revision is installed")
        candidates.sort(
            key=lambda candidate: (candidate.stat().st_mtime_ns, candidate.name),
            reverse=True,
        )
        return tuple(candidates[:2])

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


def _order_loaded_catalogs(
    loaded: tuple[_LoadedCatalog, ...],
) -> tuple[_LoadedCatalog, ...]:
    """Prefer the manifest carry-forward relation over filesystem timestamp order."""

    if len(loaded) < 2:
        return loaded
    loaded_revisions = {catalog.manifest.catalog_revision for catalog in loaded}
    referenced_revisions = {
        record.carry_forward_from
        for catalog in loaded
        for record in catalog.manifest.scopes
        if record.carry_forward_from in loaded_revisions
    }
    active_candidates = tuple(
        catalog
        for catalog in loaded
        if catalog.manifest.catalog_revision not in referenced_revisions
    )
    if len(active_candidates) != 1:
        return loaded
    active = active_candidates[0]
    return (active, *(catalog for catalog in loaded if catalog is not active))


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
