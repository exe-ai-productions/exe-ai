"""Client for MCP servers over HTTP ("Streamable HTTP", MCP 2025-06-18).

Hosted servers (GitHub, Notion, Recraft …) don't run as a subprocess but
somewhere on the network. The protocol is the same JSON-RPC as over
standard input, just as a POST to ONE address:

    POST <url>       one request; the answer comes directly as JSON or —
                     depending on the server — as text/event-stream (SSE)
    Mcp-Session-Id   assigned by the server at initialize and carried along
                     with every request from then on
    DELETE <url>     ends the session when stopping (best effort)

Deliberately NO permanently open connection:
request/response only. An open connection would be needed for a server to
report changes to its tool list on its own — but the list is captured at
connect time, so a report would go nowhere.

A server is reached without a sign-in, with headers of the entry's own
(a key from the .env goes into any header, ``Authorization: Bearer`` among
them), or with the access of a browser sign-in (OAuth), which docks on here
as ``api_key``.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import httpx

from app.tools.mcp_client import (
    CALL_TIMEOUT,
    MCPFehler,
    MCPWerkzeug,
    PROTOKOLL_VERSION,
    START_TIMEOUT,
    ergebnis_zu_text,
    start_time_limit_sentence,
    werkzeuge_aus_antwort,
    time_limit_sentence,
)
from app.tools.mcp_logo import logo_of

log = logging.getLogger(__name__)


def put_header(headers: dict[str, str], name: str, value: str) -> None:
    """Sets a header, replacing one of the same name in any case: a request
    carries one header of a name, never two."""
    for existing in [k for k in headers if k.lower() == name.lower()]:
        del headers[existing]
    headers[name] = value


class _SitzungVerfallen(Exception):
    """The server no longer knows the Mcp-Session-Id (404) — sign in again."""


class _NichtAngemeldet(Exception):
    """The server rejects the access (401/403)."""

    def __init__(self, status: int) -> None:
        super().__init__(status)
        self.status = status


class MCPHttpClient:
    """Talks to a hosted MCP server over Streamable HTTP."""

    def __init__(
        self,
        name: str,
        url: str,
        api_key: str | None = None,
        headers: dict[str, str] | None = None,
        timeout: float = CALL_TIMEOUT,
        transport: httpx.AsyncBaseTransport | None = None,
        token_erneuern=None,
    ) -> None:
        self.name = name
        self.url = url
        self.api_key = api_key
        # Headers of the entry's own, with every request: where a server
        # wants its key (``X-Goog-Api-Key``) or sets its own Bearer.
        self.headers = headers or {}
        # What one tool call may take, as a whole. The start keeps
        # ``START_TIMEOUT``.
        self.timeout = timeout
        # If the access dies mid-run (401), this callback fetches a fresh
        # one once — the registry's OAuth renewal. None means: fixed key,
        # there is nothing to renew.
        self.token_erneuern = token_erneuern
        # For tests only: an ASGITransport instead of a real network. This
        # way the proof runs against a real MCP server in the test process —
        # real protocol, no mock-up, no open port.
        self._transport = transport

        self._client: httpx.AsyncClient | None = None
        self._sitzung: str | None = None
        self._protokoll: str | None = None
        self._zaehler = 0
        self.werkzeuge: list[MCPWerkzeug] = []
        # The logo the server sent along, checked, as a data URL — or None
        # (app/tools/mcp_logo.py).
        self.logo: str | None = None

    @property
    def laeuft(self) -> bool:
        return self._client is not None

    # --- Connection ------------------------------------------------------

    async def starten(self) -> None:
        # The limit of each request is set where it is made: a call may take
        # as long as its server's entry says, the handshake and the list
        # keep the start's own.
        self._client = httpx.AsyncClient(
            timeout=START_TIMEOUT, transport=self._transport
        )
        try:
            antwort = await self._initialisieren()
        except (asyncio.TimeoutError, httpx.TimeoutException):
            raise MCPFehler(
                start_time_limit_sentence(self.name, "initialize", START_TIMEOUT)
            ) from None
        log.info(
            "MCP server '%s' connected (http): %s",
            self.name,
            (antwort.get("serverInfo") or {}).get("name", "unbekannt"),
        )
        # Fetched with a client of its own: the server's access (key, token)
        # never travels with a request for a picture. Only the server's own
        # origin may be asked.
        logo = asyncio.ensure_future(
            logo_of((antwort.get("serverInfo") or {}).get("icons"), self.url, self._transport)
        )
        try:
            self.werkzeuge = await self._werkzeuge_holen()
        except (asyncio.TimeoutError, httpx.TimeoutException):
            logo.cancel()
            raise MCPFehler(
                start_time_limit_sentence(self.name, "tools/list", START_TIMEOUT)
            ) from None
        except BaseException:
            logo.cancel()
            raise
        self.logo = await logo

    async def _initialisieren(self) -> dict[str, Any]:
        """The handshake: initialize, remember the session, report initialized."""
        try:
            antwort = await self._einmal_aufrufen(
                "initialize",
                {
                    "protocolVersion": PROTOKOLL_VERSION,
                    "capabilities": {},
                    "clientInfo": {"name": "exe-ai-terminal", "version": "0.1.0"},
                },
            )
        except _NichtAngemeldet as fehler:
            # At startup the registry supplies the access fresh — if the
            # server rejects it anyway, another attempt won't help.
            raise self._anmeldefehler(fehler.status) from None
        # From now on every request carries the negotiated version in its
        # header — not yet on initialize itself, that's where it is
        # negotiated in the first place.
        self._protokoll = antwort.get("protocolVersion") or PROTOKOLL_VERSION
        await self._benachrichtigen("notifications/initialized")
        return antwort

    async def stoppen(self) -> None:
        if self._client is None:
            return
        if self._sitzung:
            # Best effort — if the DELETE fails, the session simply
            # expires by itself on the server side.
            try:
                await self._client.delete(self.url, headers=self._koepfe())
            except httpx.HTTPError:
                pass
        await self._client.aclose()
        self._client = None
        self._sitzung = None
        self._protokoll = None

    # --- JSON-RPC over HTTP ----------------------------------------------

    def _koepfe(self) -> dict[str, str]:
        # The protocol's own headers win over the entry's.
        koepfe = dict(self.headers)
        put_header(koepfe, "Content-Type", "application/json")
        put_header(koepfe, "Accept", "application/json, text/event-stream")
        if self._protokoll:
            put_header(koepfe, "MCP-Protocol-Version", self._protokoll)
        if self._sitzung:
            put_header(koepfe, "Mcp-Session-Id", self._sitzung)
        if self.api_key:
            put_header(koepfe, "Authorization", f"Bearer {self.api_key}")
        return koepfe

    def _anmeldefehler(self, status: int) -> MCPFehler:
        return MCPFehler(
            f"MCP server '{self.name}': authentication required (HTTP {status}). Check the key "
            "or sign-in."
        )

    async def _aufrufen(
        self, methode: str, parameter: dict[str, Any], limit: float = START_TIMEOUT
    ) -> dict[str, Any]:
        """One request, renewed once where the session or the access ran
        out. ``limit`` is how long a stretch of the answer may take — the
        whole call is held to it by the caller."""
        sitzung_erneuert = False
        token_erneuert = False
        while True:
            try:
                return await self._einmal_aufrufen(methode, parameter, limit)
            except _SitzungVerfallen:
                # The server discarded the session (restart, timeout).
                # Sign in again completely once and repeat the request —
                # if that fails too, the error is real and becomes visible.
                if sitzung_erneuert:
                    raise MCPFehler(
                        f"MCP server '{self.name}': the session cannot be renewed."
                    ) from None
                sitzung_erneuert = True
                log.info("MCP '%s': session expired — signing in again", self.name)
                self._sitzung = None
                self._protokoll = None
                await self._initialisieren()
            except _NichtAngemeldet as fehler:
                # The access died mid-run (OAuth tokens usually last an
                # hour): renew silently once, then repeat. If that fails,
                # the CALLER gets the error text — the run does not die.
                if token_erneuert or self.token_erneuern is None:
                    raise self._anmeldefehler(fehler.status) from None
                token_erneuert = True
                neu = await self.token_erneuern()
                if not neu:
                    raise self._anmeldefehler(fehler.status) from None
                log.info("MCP '%s': access renewed after HTTP %d", self.name, fehler.status)
                self.api_key = neu

    async def _einmal_aufrufen(
        self, methode: str, parameter: dict[str, Any], limit: float = START_TIMEOUT
    ) -> dict[str, Any]:
        if self._client is None:
            raise MCPFehler(f"MCP server '{self.name}' is not running.")
        self._zaehler += 1
        kennung = self._zaehler
        nachricht = {"jsonrpc": "2.0", "id": kennung, "method": methode, "params": parameter}

        # stream instead of post: an SSE response may be ended as soon as
        # our answer was in it — a server that keeps the connection open
        # would otherwise pin us down until the timeout.
        async with self._client.stream(
            "POST",
            self.url,
            content=json.dumps(nachricht, ensure_ascii=False).encode("utf-8"),
            headers=self._koepfe(),
            # Connecting and sending keep the start's limit; waiting for the
            # server to answer is what a call may take.
            timeout=httpx.Timeout(limit, connect=START_TIMEOUT, write=START_TIMEOUT),
        ) as antwort:
            sitzung = antwort.headers.get("mcp-session-id")
            if sitzung:
                self._sitzung = sitzung

            if antwort.status_code in (401, 403):
                raise _NichtAngemeldet(antwort.status_code)
            if antwort.status_code == 404 and self._sitzung and methode != "initialize":
                raise _SitzungVerfallen()
            if antwort.status_code >= 400:
                text = (await antwort.aread())[:300].decode("utf-8", "replace")
                raise MCPFehler(
                    f"{self.name}/{methode}: HTTP {antwort.status_code} — {text.strip()}"
                )

            typ = antwort.headers.get("content-type", "")
            if typ.startswith("text/event-stream"):
                daten = await self._sse_antwort(antwort, kennung)
            else:
                daten = json.loads(await antwort.aread())

        if "error" in daten:
            fehler = daten["error"]
            raise MCPFehler(f"{self.name}/{methode}: {fehler.get('message', fehler)}")
        return daten.get("result") or {}

    async def _sse_antwort(self, antwort: httpx.Response, kennung: int) -> dict[str, Any]:
        """Reads the event stream until the answer to OUR request arrives.

        Other messages in the stream (notifications, requests from the
        server) are skipped over — this variant works strictly
        request/response.
        """
        datenzeilen: list[str] = []
        async for zeile in antwort.aiter_lines():
            if zeile.startswith("data:"):
                datenzeilen.append(zeile[5:].lstrip())
                continue
            if zeile.strip():
                continue  # event:, id:, retry:, comments — not of interest
            if not datenzeilen:
                continue
            try:
                nachricht = json.loads("\n".join(datenzeilen))
            except json.JSONDecodeError:
                nachricht = None
            datenzeilen = []
            if (
                isinstance(nachricht, dict)
                and nachricht.get("id") == kennung
                and ("result" in nachricht or "error" in nachricht)
            ):
                return nachricht
        raise MCPFehler(
            f"{self.name}: the event stream ended without a response to the request."
        )

    async def _benachrichtigen(self, methode: str, parameter: dict | None = None) -> None:
        if self._client is None:
            raise MCPFehler(f"MCP server '{self.name}' is not running.")
        antwort = await self._client.post(
            self.url,
            content=json.dumps(
                {"jsonrpc": "2.0", "method": methode, "params": parameter or {}},
                ensure_ascii=False,
            ).encode("utf-8"),
            headers=self._koepfe(),
        )
        # 202 Accepted is the spec's normal case.
        if antwort.status_code >= 400:
            raise MCPFehler(
                f"{self.name}/{methode}: HTTP {antwort.status_code} — "
                f"{antwort.text[:300].strip()}"
            )

    # --- Tools -----------------------------------------------------------

    async def _werkzeuge_holen(self) -> list[MCPWerkzeug]:
        ergebnis = await self._aufrufen("tools/list", {})
        return werkzeuge_aus_antwort(ergebnis, self.name)

    async def werkzeug_aufrufen(
        self, name: str, argumente: dict[str, Any], bild_senke=None
    ) -> str:
        """Executes a tool and returns the result as text."""
        try:
            # The limit of the call as a whole: the one above is a limit on
            # each stretch of the answer, and a server that keeps sending
            # a line now and then would never run into it.
            ergebnis = await asyncio.wait_for(
                self._aufrufen(
                    "tools/call", {"name": name, "arguments": argumente}, self.timeout
                ),
                timeout=self.timeout,
            )
        except (asyncio.TimeoutError, httpx.TimeoutException):
            raise MCPFehler(time_limit_sentence(self.name, name, self.timeout)) from None
        return ergebnis_zu_text(ergebnis, f"{self.name}/{name}", bild_senke)
