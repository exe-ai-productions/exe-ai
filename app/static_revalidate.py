"""The static folder, with every file whose name does not change checked
back with the server.

The interface's bundles carry a checksum in their file name, so a changed
bundle has a new name and the old one may stay in the browser's memory for
good. Everything else under ``static/`` keeps its name from one version to
the next: the sounds, the signs, the manifest. Without a cache header a
browser takes a stored copy of such a file for fresh for a tenth of its
age, and after an update it plays the old sound for hours. ``no-cache``
means: use the stored copy, but only after asking the server — an answer
with a matching ETag is a 304 and costs next to nothing.
"""

from __future__ import annotations

from starlette.responses import Response
from starlette.staticfiles import StaticFiles
from starlette.types import Scope

# The folder the build writes its checksummed bundles to, below the static
# folder: what is in there may be kept for good.
HASHED_FOLDER = "app/assets/"


def is_hashed(path: str) -> bool:
    """Whether ``path`` — as the static mount hands it over, with the
    separators of the system — lies in the folder of the checksummed bundles."""
    return path.replace("\\", "/").startswith(HASHED_FOLDER)


class RevalidatingStaticFiles(StaticFiles):
    async def get_response(self, path: str, scope: Scope) -> Response:
        response = await super().get_response(path, scope)
        if response.status_code in (200, 304) and not is_hashed(path):
            response.headers["Cache-Control"] = "no-cache"
        return response
