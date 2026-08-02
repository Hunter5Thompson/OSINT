from starlette.responses import Response
from starlette.staticfiles import StaticFiles
from starlette.types import Scope

IMMUTABLE_CACHE_CONTROL = "public, max-age=31536000, immutable"


class CachedStaticFiles(StaticFiles):
    """StaticFiles subclass that adds immutable Cache-Control headers.

    Range requests are inherited from Starlette's FileResponse, which already
    returns 206 Partial Content when a Range header is present.
    """

    async def get_response(self, path: str, scope: Scope) -> Response:
        response = await super().get_response(path, scope)
        if response.status_code in (200, 206):
            response.headers["Cache-Control"] = IMMUTABLE_CACHE_CONTROL
        return response
