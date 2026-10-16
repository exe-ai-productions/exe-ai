"""The logo an MCP server sends along (app/tools/mcp_logo.py).

The rules are tried one by one; then a real stub server — over the protocol,
as a program on this machine and as one reached over the network — hands its
logo over and it arrives in the server list of the API.
"""

from __future__ import annotations

import base64
import io
import json
import socket
import sys
import time
from pathlib import Path

import httpx
import pytest
from PIL import Image
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from app import public_host
from app.tools import mcp_logo
from app.tools.mcp_http import MCPHttpClient
from tests.conftest import png_bytes


def _png(width: int, height: int) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), (200, 30, 30)).save(buffer, "PNG")
    return buffer.getvalue()


def _data(raw: bytes, kind: str = "image/png") -> str:
    return f"data:{kind};base64," + base64.b64encode(raw).decode()


SVG = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"/></svg>'


@pytest.fixture(autouse=True)
def _offline_names(monkeypatch):
    """Names resolve from this table only; no test reaches the network."""
    names = {"logos.example": "93.184.216.34", "inside.example": "10.0.0.5"}

    def resolve(host, *_args, **_kwargs):
        address = names.get(host)
        if address is None:
            raise socket.gaierror(host)
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 0))]

    monkeypatch.setattr(public_host.socket, "getaddrinfo", resolve)


# --- The checks, one by one -----------------------------------------------------


def test_a_small_picture_passes_and_comes_back_as_a_data_url():
    assert mcp_logo.as_data_url(_png(48, 48)) == _data(_png(48, 48))


def test_the_kind_is_the_bytes_not_the_word():
    assert mcp_logo.as_data_url(b"<html><body>no picture</body></html>") is None
    assert mcp_logo.as_data_url(b"") is None


@pytest.mark.parametrize("size", [(600, 600), (513, 10), (10, 513)])
def test_silence_a_picture_above_the_edge_is_refused(size):
    assert mcp_logo.as_data_url(_png(*size)) is None


def test_the_edge_itself_passes():
    assert mcp_logo.as_data_url(_png(512, 512)) is not None


def test_a_picture_above_the_bytes_is_refused():
    big = png_bytes() + b"\0" * mcp_logo.MAX_BYTES
    assert mcp_logo.as_data_url(big) is None


def test_a_vector_passes_as_a_picture_and_a_large_one_does_not():
    assert mcp_logo.as_data_url(SVG.encode()) == _data(SVG.encode(), "image/svg+xml")
    large = SVG.replace("<svg ", '<svg width="600" height="600" ')
    assert mcp_logo.as_data_url(large.encode()) is None
    prolog = '<?xml version="1.0"?>\n<!-- logo -->\n' + SVG
    assert mcp_logo.as_data_url(prolog.encode()) is not None
    assert mcp_logo.as_data_url(b"<svgx>") is None


def test_a_long_run_of_comments_before_no_vector_is_answered_at_once():
    started = time.monotonic()

    assert mcp_logo.as_data_url(b"<!--a-->" * 24000 + b"x") is None
    assert mcp_logo.as_data_url(b"<!--" * 40000) is None

    assert time.monotonic() - started < 2


def test_silence_a_prolog_of_comments_and_a_doctype_still_leads_to_the_vector():
    text = '\ufeff<?xml version="1.0"?><!-- a --><!-- b --><!DOCTYPE svg>\n' + SVG

    assert mcp_logo.as_data_url(text.encode()) is not None


async def test_a_data_url_far_above_the_ceiling_is_not_decoded():
    assert await mcp_logo.logo_of([{"src": "data:image/png;base64," + "A" * (mcp_logo.MAX_BYTES * 4)}]) is None


# --- Which icon is taken --------------------------------------------------------


async def test_a_data_url_is_taken_as_it_is():
    icons = [{"src": _data(_png(48, 48)), "mimeType": "image/png"}]

    assert await mcp_logo.logo_of(icons) == _data(_png(48, 48))


async def test_a_plain_text_data_url_for_a_vector_is_taken():
    assert await mcp_logo.logo_of([{"src": "data:image/svg+xml," + SVG}]) == _data(
        SVG.encode(), "image/svg+xml"
    )


async def test_silence_no_icons_and_odd_shapes_give_nothing():
    for icons in (None, [], "x", {"src": "x"}, [1, None, {"src": 5}, {}, {"src": "data:"}]):
        assert await mcp_logo.logo_of(icons) is None


async def test_the_first_icon_that_passes_wins():
    icons = [{"src": _data(_png(600, 600))}, {"src": "data:image/png;base64,@@"}, {"src": _data(_png(48, 48))}]

    assert await mcp_logo.logo_of(icons) == _data(_png(48, 48))


class _Seen:
    def __init__(self, answer):
        self.answer = answer
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self.answer(request)

    @property
    def transport(self):
        return httpx.MockTransport(self)


def _ok(_request):
    return httpx.Response(200, content=_png(48, 48), headers={"content-type": "image/png"})


async def test_an_address_of_the_servers_own_origin_is_fetched_without_credentials():
    seen = _Seen(_ok)

    logo = await mcp_logo.logo_of(
        [{"src": "https://logos.example/icon.png"}], "https://logos.example/mcp", seen.transport
    )

    assert logo == _data(_png(48, 48))
    assert [str(r.url) for r in seen.requests] == ["https://logos.example/icon.png"]
    assert "authorization" not in seen.requests[0].headers
    assert "cookie" not in seen.requests[0].headers


@pytest.mark.parametrize(
    "src",
    [
        "https://other.example/icon.png",  # another host
        "https://logos.example:8443/icon.png",  # another port
        "http://logos.example/icon.png",  # not https
        "ftp://logos.example/icon.png",
        "file:///etc/hosts",
    ],
)
async def test_silence_a_foreign_origin_or_scheme_is_never_asked(src):
    seen = _Seen(_ok)

    logo = await mcp_logo.logo_of([{"src": src}], "https://logos.example/mcp", seen.transport)

    assert logo is None
    assert seen.requests == []


async def test_silence_a_redirect_is_not_followed_and_gives_nothing():
    def moved(_request):
        return httpx.Response(302, headers={"location": "https://logos.example/real.png"})

    seen = _Seen(moved)

    logo = await mcp_logo.logo_of(
        [{"src": "https://logos.example/icon.png"}], "https://logos.example/mcp", seen.transport
    )

    assert logo is None
    assert len(seen.requests) == 1


async def test_silence_an_error_answer_or_a_page_gives_nothing():
    for answer in (
        lambda _r: httpx.Response(404),
        lambda _r: httpx.Response(200, content=b"<html>x</html>", headers={"content-type": "image/png"}),
        lambda _r: (_ for _ in ()).throw(httpx.ConnectError("no route")),
    ):
        logo = await mcp_logo.logo_of(
            [{"src": "https://logos.example/icon.png"}], "https://logos.example/mcp", _Seen(answer).transport
        )
        assert logo is None


async def _chunks(body: bytes):
    yield body[:600]
    yield body[600:]


async def test_a_picture_above_the_bytes_is_not_read_to_the_end(monkeypatch):
    monkeypatch.setattr(mcp_logo, "MAX_BYTES", 1000)
    body = png_bytes() + b"\0" * 5000

    announced = await mcp_logo.logo_of(
        [{"src": "https://logos.example/a.png"}], "https://logos.example/mcp",
        _Seen(lambda _r: httpx.Response(200, content=body)).transport,
    )
    streamed = await mcp_logo.logo_of(
        [{"src": "https://logos.example/a.png"}], "https://logos.example/mcp",
        _Seen(lambda _r: httpx.Response(200, content=_chunks(body))).transport,
    )

    assert announced is None
    assert streamed is None


async def test_a_long_list_costs_one_request_and_what_is_handed_over_comes_first():
    seen = _Seen(_ok)
    icons = [{"src": f"https://logos.example/{n}.png"} for n in range(40)]

    assert await mcp_logo.logo_of(icons, "https://logos.example/mcp", seen.transport) == _data(_png(48, 48))
    assert len(seen.requests) == 1

    seen = _Seen(_ok)
    mixed = [{"src": "https://logos.example/a.png"}, {"src": _data(_png(20, 20))}]
    assert await mcp_logo.logo_of(mixed, "https://logos.example/mcp", seen.transport) == _data(_png(20, 20))
    assert seen.requests == []


async def test_silence_an_unexpected_error_leaves_no_logo_and_no_exception(monkeypatch):
    def broken(_data):
        raise RuntimeError("boom")

    monkeypatch.setattr(mcp_logo, "as_data_url", broken)

    assert await mcp_logo.logo_of([{"src": _data(_png(48, 48))}]) is None


async def test_a_program_on_this_machine_may_name_a_public_address_only():
    seen = _Seen(_ok)

    public = await mcp_logo.logo_of([{"src": "https://logos.example/icon.png"}], None, seen.transport)
    inside = await mcp_logo.logo_of([{"src": "https://inside.example/icon.png"}], None, seen.transport)
    local = await mcp_logo.logo_of([{"src": "https://127.0.0.1/icon.png"}], None, seen.transport)

    assert public == _data(_png(48, 48))
    assert inside is None
    assert local is None
    assert [r.url.host for r in seen.requests] == ["logos.example"]


# --- A real server hands its logo over ------------------------------------------


class _LogoServer:
    def __init__(self, icons):
        self.icons = icons

    def app(self) -> Starlette:
        return Starlette(
            routes=[
                Route("/mcp", self.mcp, methods=["POST", "DELETE"]),
                Route("/icon.png", self.icon, methods=["GET"]),
            ]
        )

    async def icon(self, _request: Request) -> Response:
        return Response(_png(32, 32), media_type="image/png")

    async def mcp(self, request: Request) -> Response:
        if request.method == "DELETE":
            return Response(status_code=204)
        message = json.loads(await request.body())
        method, ident = message.get("method"), message.get("id")
        if method == "initialize":
            info = {"name": "logo-server"}
            if self.icons is not None:
                info["icons"] = self.icons
            return JSONResponse(
                {"jsonrpc": "2.0", "id": ident, "result": {
                    "protocolVersion": "2025-06-18", "capabilities": {"tools": {}}, "serverInfo": info}},
                headers={"Mcp-Session-Id": "s1"},
            )
        if method == "notifications/initialized":
            return Response(status_code=202)
        if method == "tools/list":
            return JSONResponse({"jsonrpc": "2.0", "id": ident, "result": {"tools": []}})
        return JSONResponse({"jsonrpc": "2.0", "id": ident, "error": {"code": -32601, "message": "no"}})


async def _http_logo(icons) -> str | None:
    server = _LogoServer(icons)
    client = MCPHttpClient(
        name="logo", url="https://logos.example/mcp", transport=httpx.ASGITransport(app=server.app())
    )
    await client.starten()
    try:
        return client.logo
    finally:
        await client.stoppen()


async def test_a_server_over_the_network_hands_over_its_logo():
    assert await _http_logo([{"src": _data(_png(48, 48))}]) == _data(_png(48, 48))


async def test_a_server_over_the_network_may_point_to_its_own_address():
    # The logo's request goes through the same in-process application, as the
    # server's own origin would.
    server = _LogoServer([{"src": "https://logos.example/icon.png"}])
    client = MCPHttpClient(
        name="logo", url="https://logos.example/mcp", transport=httpx.ASGITransport(app=server.app())
    )
    await client.starten()
    try:
        assert client.logo == _data(_png(32, 32))
    finally:
        await client.stoppen()


async def test_silence_a_server_without_icons_or_with_a_large_one_has_no_logo():
    assert await _http_logo(None) is None
    assert await _http_logo([{"src": _data(_png(600, 600))}]) is None


STDIO_SERVER = '''
import json, sys, base64
ICONS = json.loads(sys.argv[1])
for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    message = json.loads(line)
    method, ident = message.get("method"), message.get("id")
    if method == "initialize":
        info = {"name": "logo-stdio"}
        if ICONS is not None:
            info["icons"] = ICONS
        out = {"jsonrpc": "2.0", "id": ident, "result": {
            "protocolVersion": "2025-06-18", "capabilities": {"tools": {}}, "serverInfo": info}}
    elif method == "tools/list":
        out = {"jsonrpc": "2.0", "id": ident, "result": {"tools": []}}
    else:
        continue
    sys.stdout.write(json.dumps(out) + "\\n")
    sys.stdout.flush()
'''


def _put_stub(client, config, tmp_path: Path, name: str, icons) -> None:
    script = tmp_path / f"{name}.py"
    script.write_text(STDIO_SERVER, encoding="utf-8")
    client.app.state.config.features.mcp = True
    config.mcp.servers_file = str(tmp_path / "mcp_servers.json")
    (tmp_path / "mcp_servers.json").write_text('{"mcpServers": {}}', encoding="utf-8")
    response = client.put(
        f"/api/v1/tools/servers/{name}",
        json={"type": "stdio", "command": sys.executable, "args": [str(script), json.dumps(icons)], "enabled": True},
    )
    assert response.status_code == 200, response.text


def _listed(client, name: str) -> dict:
    deadline = time.monotonic() + 20
    entry = {}
    while time.monotonic() < deadline:
        entry = next((e for e in client.get("/api/v1/tools/servers").json() if e["name"] == name), {})
        if entry.get("laeuft"):
            return entry
        time.sleep(0.2)
    return entry


def test_the_logo_arrives_in_the_server_list(client, config, tmp_path):
    _put_stub(client, config, tmp_path, "logostub", [{"src": _data(_png(48, 48))}])

    entry = _listed(client, "logostub")

    assert entry["laeuft"] is True
    assert entry["logo"] == _data(_png(48, 48))


def test_silence_a_server_with_a_large_logo_or_none_is_listed_without_one(client, config, tmp_path):
    _put_stub(client, config, tmp_path, "bigstub", [{"src": _data(_png(600, 600))}])
    assert _listed(client, "bigstub")["logo"] is None

    _put_stub(client, config, tmp_path, "plainstub", None)
    assert _listed(client, "plainstub")["logo"] is None


# --- The interface reads it ---------------------------------------------------

SRC = Path(__file__).resolve().parent.parent / "frontend" / "src"


def _source(*parts: str) -> str:
    return SRC.joinpath(*parts).read_text(encoding="utf-8")


def test_the_card_and_the_menu_head_of_a_server_of_ones_own_wear_its_logo():
    source = _source("teile", "Verbindungen.svelte")

    # Never for a shipped server's card: it keeps its maker's vector.
    assert "const eigenLogoVon = (k) => (!k.katalog && k.eintrag?.logo) || null" in source
    assert source.count("{:else if eigenLogoVon(k)}") == 2
    assert source.count("src={eigenLogoVon(k)}") == 2


def test_the_tool_rows_and_notices_hand_the_servers_logo_to_the_mark():
    mark = _source("teile", "Werkzeugzeichen.svelte")
    assert "logo = null" in mark
    assert '<img class="zeichen serverlogo" class:laeuft={animiert} src={logo} alt="" />' in mark
    for window in ("ModulTerminal.svelte", "Meldungen.svelte"):
        source = _source("teile", window)
        assert "serverLogo(" in source
        assert "import { serverLogo } from '../lib/serverlogo.svelte.js'" in source


def test_a_shipped_name_never_takes_a_logo_from_the_list():
    source = _source("lib", "serverlogo.svelte.js")

    assert "const KATALOGNAMEN = new Set(SERVERKATALOG.map((k) => k.name))" in source
    assert "if (!name || KATALOGNAMEN.has(name)) return null" in source
