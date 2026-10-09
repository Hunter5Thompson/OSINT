"""READ-ONLY recon scene router — `/api/recon/scenes`.

Serves the in-memory `ReconManifestLoader` cache populated at app startup.
No writes, no LLM calls, no upstream fetches — this is a hard read-only
surface. The dual-prefix mount happens in `app/main.py`; the router itself
declares paths without a prefix so it can be included twice.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from app.models.recon import ReconScene, ReconScenesResponse
from app.services.recon_manifest import ReconManifestLoader

router = APIRouter(tags=["recon"])


def _loader(request: Request) -> ReconManifestLoader:
    loader: ReconManifestLoader | None = getattr(
        request.app.state, "recon_manifest", None
    )
    if loader is not None and loader.disabled_reason is not None:
        raise HTTPException(status_code=404, detail="Recon is inactive")
    if loader is None or not loader.is_loaded:
        raise HTTPException(
            status_code=503,
            detail="Recon scene data is unavailable",
        )
    return loader


@router.get("/recon/scenes", response_model=ReconScenesResponse)
async def list_scenes(request: Request) -> ReconScenesResponse:
    optional: ReconManifestLoader | None = getattr(request.app.state, "recon_manifest", None)
    if optional is not None and optional.disabled_reason is not None:
        return ReconScenesResponse(
            scenes=[], availability="disabled", reason=optional.disabled_reason,
        )
    loader = _loader(request)
    return ReconScenesResponse(scenes=loader.list_scenes())


@router.get("/recon/scenes/{scene_id}", response_model=ReconScene)
async def get_scene(scene_id: str, request: Request) -> ReconScene:
    loader = _loader(request)
    scene = loader.get_scene(scene_id)
    if scene is None:
        raise HTTPException(status_code=404, detail="scene not found")
    return scene
