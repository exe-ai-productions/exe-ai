"""What a brand-new MCP address wants, before anything is written down.

Typing a URL and asking the server is what every checked program does
instead of a "how do you sign in" switch (`frontend/src/teile/MCPMaske.svelte`).
The one unauthenticated ``initialize`` call this module makes answers three
questions at once:

    the server answers outright        nothing to ask for, here is its name
    401/403 with ``WWW-Authenticate``   it follows the MCP authorization
                                        spec (2025-06-18, RFC 9728) and can be
                                        walked through the browser sign-in
                                        ``mcp_auth.py`` already knows how to do
    401/403 without that header        an older server checking a plain
                                        bearer value nobody can discover —
                                        the API Key field is for this one

No session is kept and no tools are listed: that is what happens once the
sheet writes the entry and the registry connects for real
(``app/tools/mcp_http.py``, a separate, stateful client this module does not
share code with on purpose — a probe that is abandoned mid-flow leaves
nothing open to close).
"""

from __future__ import annotations

import json
from typing import Any

import httpx

from app.tools.mcp_client import MCPFehler, PROTOKOLL_VERSION

# The id the one `initialize` call in `sondieren()` sends — an SSE stream can
# carry an earlier, unrelated event first, so an event is only the answer
# once it carries this same id back (the same check `mcp_http.py`'s
# `_sse_antwort` makes on its own request/response pairs).
_ANFRAGE_ID = 1


def _json_laden(text: str) -> dict[str, Any]:
    try:
        return json.loads(text)
    except json.JSONDecodeError as fehler:
        raise MCPFehler(f"The server did not return valid JSON: {fehler}") from fehler


def _antwort_lesen(text: str, content_type: str) -> dict[str, Any]:
    if content_type.startswith("text/event-stream"):
        zeilen: list[str] = []
        for zeile in text.splitlines():
            if zeile.startswith("data:"):
                zeilen.append(zeile[len("data:") :].lstrip())
            elif not zeile.strip() and zeilen:
                daten = _json_laden("\n".join(zeilen))
                if daten.get("id") == _ANFRAGE_ID and ("result" in daten or "error" in daten):
                    return daten
                zeilen = []
        if zeilen:
            daten = _json_laden("\n".join(zeilen))
            if daten.get("id") == _ANFRAGE_ID and ("result" in daten or "error" in daten):
                return daten
        raise MCPFehler("The server did not respond to initialize.")
    return _json_laden(text)


async def sondieren(
    url: str,
    timeout: float = 10.0,
    transport: httpx.AsyncBaseTransport | None = None,
) -> dict[str, Any]:
    """One unauthenticated ``initialize`` call. Returns ``{"verlangt":
    None|"schluessel"|"anmeldung", "name": str|None}`` — ``name`` is only
    set once the server has actually answered ``initialize``, so it is
    ``None`` on both the key and the sign-in path.

    ``transport``: for tests only, an ASGITransport onto a stub server in
    the test process — the same convention ``mcp_http.py`` uses, real
    protocol and no open port."""
    nachricht = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": PROTOKOLL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "exe-ai-terminal", "version": "0.1.0"},
        },
    }
    try:
        async with httpx.AsyncClient(timeout=timeout, transport=transport) as client:
            antwort = await client.post(
                url,
                content=json.dumps(nachricht, ensure_ascii=False).encode("utf-8"),
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json, text/event-stream",
                },
            )
    except httpx.HTTPError as fehler:
        # German on purpose: this sentence has exactly one reader, the MCP
        # mask in the window, and it shows it in the language of the page.
        # No model ever sees this text — the probe is a person typing an
        # address, not a tool result.
        raise MCPFehler(f"The server is unreachable: {fehler}") from fehler

    if antwort.status_code in (401, 403):
        verlangt = "anmeldung" if antwort.headers.get("www-authenticate") else "schluessel"
        return {"verlangt": verlangt, "name": None}
    if antwort.status_code >= 400:
        text = antwort.text[:300].strip()
        raise MCPFehler(f"HTTP {antwort.status_code} — {text}")

    daten = _antwort_lesen(antwort.text, antwort.headers.get("content-type", ""))
    if "error" in daten:
        rpc_fehler = daten["error"]
        raise MCPFehler(str(rpc_fehler.get("message", rpc_fehler)))
    ergebnis = daten.get("result") or {}
    name = (ergebnis.get("serverInfo") or {}).get("name")
    return {"verlangt": None, "name": name}
