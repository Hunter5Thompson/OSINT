"""Safe HTTP projection of the local, manifest-owned spatial catalog."""

from __future__ import annotations

import hashlib
import re
from typing import Final

from fastapi import APIRouter, Query, Request
from starlette.responses import Response

from app.models.spatial import (
    BootstrapAttribution,
    BootstrapAttributionSource,
    BoundaryPackRenderDescriptor,
    BoundaryRenderDescriptor,
    CatalogBootstrapResponse,
    CatalogCapabilities,
    CatalogProblemCode,
    GeometryDescriptor,
    ScopeBundleResponse,
    ScopePresentationResponse,
    ScopeProblemDetail,
    ScopeProblemResponse,
    SpatialCatalogProblem,
    canonical_json_bytes,
)
from app.services.spatial_catalog import (
    CatalogBootstrap,
    ResolvedSpatialScope,
    SpatialCatalogLoader,
)
from app.static.cached_static import IMMUTABLE_CACHE_CONTROL

router = APIRouter(prefix="/spatial", tags=["spatial"])
# V1 is a trusted on-prem/LAN read surface. Authentication and per-IP limiting are
# deployment-edge gates before external exposure; the global read semaphore below is
# resource protection, not an authorization boundary.

_METADATA_CACHE_CONTROL = "public, max-age=60, must-revalidate"
_NO_STORE = "no-store"
_RANGE = re.compile(r"^bytes=(\d*)-(\d*)$")
_PROBLEM_STATUS: Final[dict[CatalogProblemCode, int]] = {
    CatalogProblemCode.CATALOG_UNAVAILABLE: 503,
    CatalogProblemCode.CATALOG_REVISION_UNAVAILABLE: 409,
    CatalogProblemCode.INVALID_CATALOG_REVISION: 422,
    CatalogProblemCode.INVALID_SCOPE_KEY: 422,
    CatalogProblemCode.INVALID_ASSET_ID: 422,
    CatalogProblemCode.UNKNOWN_SCOPE: 404,
    CatalogProblemCode.UNKNOWN_ASSET: 404,
    CatalogProblemCode.ASSET_BUSY: 429,
    CatalogProblemCode.ASSET_CORRUPT: 503,
}
if set(_PROBLEM_STATUS) != set(CatalogProblemCode):
    raise RuntimeError("spatial problem status mapping must be exhaustive")


@router.get("/catalog")
async def catalog(request: Request) -> Response:
    loader = _loader(request)
    value = loader.bootstrap() if loader is not None else _unavailable_problem()
    if isinstance(value, SpatialCatalogProblem):
        return _problem_response(value)
    response = _catalog_response(value)
    return _metadata_response(response, request.headers.get("if-none-match"))


@router.get("/scope")
async def scope(
    request: Request,
    scope_key: str | None = Query(default=None),
    catalog_revision: str | None = Query(default=None),
) -> Response:
    loader = _loader(request)
    value = (
        loader.resolve_scope(scope_key, catalog_revision)
        if loader is not None
        else _unavailable_problem()
    )
    if isinstance(value, SpatialCatalogProblem):
        return _problem_response(value)
    response = _scope_response(value)
    return _metadata_response(response, request.headers.get("if-none-match"))


@router.get("/assets/{asset_id}")
async def asset(request: Request, asset_id: str) -> Response:
    return await _serve_asset(request, asset_id)


@router.get("/assets/{asset_id:path}", include_in_schema=False)
async def invalid_asset_path(request: Request, asset_id: str) -> Response:
    """Route decoded slash/traversal candidates through the same strict validator."""

    return await _serve_asset(request, asset_id)


async def _serve_asset(request: Request, asset_id: str) -> Response:
    loader = _loader(request)
    if loader is None:
        return _problem_response(_unavailable_problem())
    value = loader.get_asset_by_id(asset_id)
    if isinstance(value, SpatialCatalogProblem):
        return _problem_response(value)
    etag = f'"{value.asset_id}"'
    common_headers = {
        "Accept-Ranges": "bytes",
        "Cache-Control": IMMUTABLE_CACHE_CONTROL,
        "Content-Encoding": "identity",
        "ETag": etag,
    }
    if _etag_matches(request.headers.get("if-none-match"), etag):
        return Response(status_code=304, headers=common_headers)

    payload = await loader.read_asset(value)
    if isinstance(payload, SpatialCatalogProblem):
        return _problem_response(payload)

    range_header = request.headers.get("range")
    if range_header is None:
        return Response(
            content=payload,
            media_type=value.media_type,
            headers=common_headers,
        )
    try:
        start, end = _parse_range(range_header, len(payload))
    except ValueError:
        return Response(
            status_code=416,
            headers={**common_headers, "Content-Range": f"bytes */{len(payload)}"},
        )
    partial = payload[start : end + 1]
    return Response(
        content=partial,
        status_code=206,
        media_type=value.media_type,
        headers={
            **common_headers,
            "Content-Range": f"bytes {start}-{end}/{len(payload)}",
        },
    )


def _catalog_response(value: CatalogBootstrap) -> CatalogBootstrapResponse:
    return CatalogBootstrapResponse(
        active_catalog_revision=value.active_catalog_revision,
        served_catalog_revisions=value.served_catalog_revisions,
        boundary_policy=value.boundary_policy,  # type: ignore[arg-type]
        root_scope_key=value.root_scope_key,
        capabilities=CatalogCapabilities(
            max_enabled_kind=value.max_enabled_kind,
            timeline_scope="bbox_approximate",
            intelligence_scope="unavailable",
        ),
        attributions=tuple(
            BootstrapAttribution(
                catalog_revision=attribution.catalog_revision,
                representation_note=attribution.representation_note,
                sources=tuple(
                    BootstrapAttributionSource(
                        source_id=source.source_id,
                        release=source.release,
                        license_id=source.license_id,
                        text=source.text,
                    )
                    for source in attribution.sources
                ),
            )
            for attribution in value.attributions
        ),
    )


def _scope_response(value: ResolvedSpatialScope) -> ScopeBundleResponse:
    presentation = value.record.presentation
    return ScopeBundleResponse(
        catalog_revision=value.catalog_revision,
        boundary_policy=value.boundary_policy,  # type: ignore[arg-type]
        canonicalized_from=value.canonicalized_from,
        scope=value.record.scope,
        path=value.path,
        presentation=ScopePresentationResponse(
            preferred_lod=presentation.preferred_lod,
            outline_lods={
                lod: _render_descriptor(descriptor)
                for lod, descriptor in presentation.outline_lods.items()
            },
            children_lods={
                lod: _render_descriptor(descriptor)
                for lod, descriptor in presentation.children_lods.items()
            },
        ),
        containment=presentation.containment,
        provenance_ref=value.record.provenance_ref,
    )


def _render_descriptor(
    descriptor: GeometryDescriptor,
) -> BoundaryRenderDescriptor | BoundaryPackRenderDescriptor:
    values = {
        "asset_id": descriptor.asset_id,
        "media_type": descriptor.media_type,
        "byte_length": descriptor.byte_length,
        "vertex_count": descriptor.vertex_count,
        "role": descriptor.role,
        "lod": descriptor.lod,
    }
    if descriptor.feature_count is None:
        return BoundaryRenderDescriptor.model_validate(values)
    return BoundaryPackRenderDescriptor.model_validate(
        {**values, "feature_count": descriptor.feature_count}
    )


def _metadata_response(
    model: CatalogBootstrapResponse | ScopeBundleResponse,
    if_none_match: str | None,
) -> Response:
    content = canonical_json_bytes(model)
    etag = f'"{hashlib.sha256(content).hexdigest()}"'
    headers = {"Cache-Control": _METADATA_CACHE_CONTROL, "ETag": etag}
    if _etag_matches(if_none_match, etag):
        return Response(status_code=304, headers=headers)
    return Response(content=content, media_type="application/json", headers=headers)


def _problem_response(problem: SpatialCatalogProblem) -> Response:
    body = ScopeProblemResponse(
        detail=ScopeProblemDetail(
            code=problem.code,
            message=problem.message,
            target=problem.target,
            recoverable=problem.recoverable,
            active_catalog_revision=problem.active_catalog_revision,
        )
    )
    headers = {"Cache-Control": _NO_STORE}
    if problem.code is CatalogProblemCode.ASSET_BUSY:
        headers["Retry-After"] = "1"
    return Response(
        content=canonical_json_bytes(body),
        status_code=_PROBLEM_STATUS[problem.code],
        media_type="application/json",
        headers=headers,
    )


def _loader(request: Request) -> SpatialCatalogLoader | None:
    candidate = getattr(request.app.state, "spatial_catalog", None)
    return candidate if isinstance(candidate, SpatialCatalogLoader) else None


def _unavailable_problem() -> SpatialCatalogProblem:
    return SpatialCatalogProblem(
        code=CatalogProblemCode.CATALOG_UNAVAILABLE,
        message="Spatial catalog is unavailable",
        recoverable=True,
    )


def _etag_matches(candidate: str | None, current: str) -> bool:
    if candidate is None:
        return False
    for raw_token in candidate.split(","):
        token = raw_token.strip()
        if token == "*":
            return True
        if token.startswith("W/"):
            token = token[2:].strip()
        if token == current:
            return True
    return False


def _parse_range(value: str, size: int) -> tuple[int, int]:
    if "," in value:
        raise ValueError("multiple ranges are not supported")
    match = _RANGE.fullmatch(value.strip())
    if match is None or size <= 0:
        raise ValueError("invalid range")
    start_text, end_text = match.groups()
    if not start_text and not end_text:
        raise ValueError("empty range")
    if not start_text:
        suffix_length = int(end_text)
        if suffix_length <= 0:
            raise ValueError("invalid suffix range")
        start = max(size - suffix_length, 0)
        return start, size - 1
    start = int(start_text)
    if start >= size:
        raise ValueError("range starts after content")
    end = size - 1 if not end_text else min(int(end_text), size - 1)
    if end < start:
        raise ValueError("range ends before it starts")
    return start, end
