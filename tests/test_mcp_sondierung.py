"""The pre-connect probe: one unauthenticated `initialize`, real protocol.

Same philosophy as test_mcp_http.py -- a tiny MCP server as an ASGI
application in the test process (httpx.ASGITransport), not a mocked-up
response shape.
"""

from __future__ import annotations

import json

import httpx
import pytest
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from app.tools.mcp_client import MCPFehler
from app.tools.mcp_sondierung import sondieren


class SondierServer:
    """`modus`: 'offen' answers initialize outright, 'anmeldung' answers 401
    with a WWW-Authenticate header (RFC 9728), 'schluessel' answers a bare
    401 with none -- the one signal `sondieren()` tells them apart by."""

    def __init__(self, modus: str, name: str = "stub-server") -> None:
        self.modus = modus
        self.name = name

    def app(self) -> Starlette:
        return Starlette(routes=[Route("/mcp", self.mcp, methods=["POST"])])

    async def mcp(self, request: Request) -> Response:
        if self.modus == "anmeldung":
            return Response(
                status_code=401,
                headers={
                    "WWW-Authenticate": (
                        'Bearer resource_metadata='
                        '"https://stub/.well-known/oauth-protected-resource"'
                    )
                },
            )
        if self.modus == "schluessel":
            return Response(status_code=401)
        nachricht = json.loads(await request.body())
        return JSONResponse(
            {
                "jsonrpc": "2.0",
                "id": nachricht.get("id"),
                "result": {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": self.name},
                },
            }
        )


def _transport(modus: str, name: str = "stub-server") -> httpx.AsyncBaseTransport:
    return httpx.ASGITransport(app=SondierServer(modus, name).app())


async def test_ein_server_der_gleich_antwortet_nennt_seinen_namen():
    ergebnis = await sondieren(
        "http://testserver/mcp", transport=_transport("offen", name="Notion")
    )
    assert ergebnis == {"verlangt": None, "name": "Notion"}


async def test_401_mit_www_authenticate_heisst_anmeldung():
    """Fails without the header check: a bare 401 would read as
    'schluessel' even though the server names OAuth metadata."""
    ergebnis = await sondieren("http://testserver/mcp", transport=_transport("anmeldung"))
    assert ergebnis == {"verlangt": "anmeldung", "name": None}


async def test_401_ohne_www_authenticate_heisst_schluessel():
    """The silence probe for the test above: the same status code, no
    header, and the other path is taken."""
    ergebnis = await sondieren("http://testserver/mcp", transport=_transport("schluessel"))
    assert ergebnis == {"verlangt": "schluessel", "name": None}


async def test_ein_serverfehler_wird_gemeldet():
    class KaputterServer:
        def app(self) -> Starlette:
            return Starlette(routes=[Route("/mcp", self.mcp, methods=["POST"])])

        async def mcp(self, request: Request) -> Response:
            return Response("Ganz kaputt", status_code=500)

    with pytest.raises(MCPFehler, match="500"):
        await sondieren(
            "http://testserver/mcp",
            transport=httpx.ASGITransport(app=KaputterServer().app()),
        )


async def test_ein_nicht_json_koerper_wird_gemeldet_statt_abzustuerzen():
    """A 200 whose body is not JSON at all (a login page, a misconfigured
    proxy) must end as MCPFehler, not an unhandled JSONDecodeError."""

    class NichtJsonServer:
        def app(self) -> Starlette:
            return Starlette(routes=[Route("/mcp", self.mcp, methods=["POST"])])

        async def mcp(self, request: Request) -> Response:
            return Response("<html>nicht json</html>", status_code=200, media_type="text/html")

    with pytest.raises(MCPFehler, match="JSON"):
        await sondieren(
            "http://testserver/mcp",
            transport=httpx.ASGITransport(app=NichtJsonServer().app()),
        )


async def test_sse_ereignis_mit_fremder_kennung_wird_uebersprungen():
    """An event stream can carry an earlier, unrelated message before the
    real answer -- only the one whose id matches our own request is it."""

    class FremdeKennungServer:
        def app(self) -> Starlette:
            return Starlette(routes=[Route("/mcp", self.mcp, methods=["POST"])])

        async def mcp(self, request: Request) -> Response:
            koerper = (
                'data: {"jsonrpc": "2.0", "id": 99, '
                '"result": {"serverInfo": {"name": "Fremd"}}}\n\n'
                'data: {"jsonrpc": "2.0", "id": 1, '
                '"result": {"serverInfo": {"name": "Richtig"}}}\n\n'
            )
            return Response(koerper, status_code=200, media_type="text/event-stream")

    ergebnis = await sondieren(
        "http://testserver/mcp",
        transport=httpx.ASGITransport(app=FremdeKennungServer().app()),
    )
    assert ergebnis == {"verlangt": None, "name": "Richtig"}
