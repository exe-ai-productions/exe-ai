"""Guards every ``/api/v1`` call behind a key that lives only in memory
 — minted fresh on every start, the same pattern the local
model servers already use (``app/modellrunner.py``: ``LLAMA_API_KEY``,
the source of the "Invalid API-Key" message ``app/main.py``'s own
docstring mentions).

Measured against the running service: ``GET /api/v1/chats``
answered 200 with no login, no token, nothing — any program on this
machine could read every chat. ``app/herkunftswaechter.py`` does not help
here; it turns away a foreign web PAGE, not a foreign PROCESS making its
own direct HTTP calls. That is why reading is checked here too, not only
writing: reading is exactly what that attacker wants.

The key never touches disk — a key that outlives the process could be read
by anyone who was ever able to read the disk, which defeats the point of
minting a new one on every start.
"""

from __future__ import annotations

import logging
import secrets

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from app import sprachwahl
from app.i18n import t

log = logging.getLogger(__name__)

# The one place a browser is meant to reach this API without ever having
# read the key: it lands here straight from the OAuth provider's own
# redirect, which knows nothing of this session and cannot be made to
# send it. Secured instead by its own one-time, time-limited state token
# (app/api/v1/werkzeuge.py).
AUSGENOMMEN = frozenset({"/api/v1/tools/oauth/callback"})

# The header the app's own frontend sends on every fetch; the query
# parameter is the fallback for the places a browser cannot attach a header
# at all — EventSource and a plain <img src>/href. Exactly these five, each
# GET, each a segment after the ``{}``; the last is a chat document's file,
# fetched by the doc folder's download link and by the app shell's
# preview. Every other route only accepts the header — a query
# parameter lands in server logs and browser history, the header does not.
HEADER = "X-Sitzungsschluessel"
ABFRAGEPARAMETER = "schluessel"
ABFRAGE_ERLAUBT = (
    "/api/v1/agentendock/{}",
    "/api/v1/laeufe/{}/stream",
    "/api/v1/events/stream",
    "/api/v1/images/{}",
    "/api/v1/documents/{}/file",
)

# The dock route shares its prefix with a literal listing route
# (GET .../agentendock/alle) — FastAPI's own routing tells them apart by
# registration order, but this guard runs ahead of routing and sees only the
# raw path. Without this, "alle" would read as a valid {} value too, and the
# listing would take the parameter it never needed.
KEIN_WERT = {
    "/api/v1/agentendock/{}": {"alle"},
}


def _abfrageparameter_erlaubt(weg: str) -> bool:
    teile = weg.split("/")
    for muster in ABFRAGE_ERLAUBT:
        muster_teile = muster.split("/")
        if len(muster_teile) != len(teile):
            continue
        if not all(m == "{}" or m == t for m, t in zip(muster_teile, teile, strict=True)):
            continue
        if "{}" in muster_teile:
            wert = teile[muster_teile.index("{}")]
            if not wert or wert in KEIN_WERT.get(muster, frozenset()):
                continue
        return True
    return False


def neuer_schluessel() -> str:
    return secrets.token_urlsafe(32)


class Sitzungswaechter(BaseHTTPMiddleware):
    """Rejects any ``/api/v1`` request that does not carry this run's own
    key — the check reads it fresh from ``request.app.state`` each time,
    so a test app and the real service never share one by accident."""

    async def dispatch(self, request: Request, call_next):
        weg = request.url.path
        if not weg.startswith("/api/v1") or weg in AUSGENOMMEN:
            return await call_next(request)
        mitgeschickt = request.headers.get(HEADER)
        if not mitgeschickt and request.method == "GET" and _abfrageparameter_erlaubt(weg):
            mitgeschickt = request.query_params.get(ABFRAGEPARAMETER)
        # ``compare_digest`` needs two strings — asked first so a missing
        # key never reaches it as ``None``, and so every rejection still
        # takes the same, constant time regardless of which character of a
        # present-but-wrong key differs: an ordinary ``!=``
        # returns at the first mismatch, and that timing difference is
        # enough to guess the key one character at a time.
        if not mitgeschickt:
            gueltig = False
            grund = "missing key"
        else:
            gueltig = secrets.compare_digest(
                mitgeschickt, request.app.state.sitzungsschluessel
            )
            grund = "wrong key"
        if not gueltig:
            log.warning("Rejected %s (%s)", weg, grund)
            # The one sentence of this guard, in the language the request
            # asked for — an English window reads it in English too
            # (app/sprachwahl.language_from_headers, the same rule every
            # route follows).
            sprache = sprachwahl.request_language(request)
            return JSONResponse(
                {"detail": t("fehler.sitzungsschluessel", sprache)},
                status_code=401,
            )
        return await call_next(request)
