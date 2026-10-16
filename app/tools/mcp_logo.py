"""The logo an MCP server sends along when it connects.

``serverInfo.icons`` (MCP specification 2025-11-25, ``Implementation.icons``)
lists pictures a client may show for the server. The specification asks the
client to look at them before it does: only ``https:`` or ``data:``, from the
server's own origin where the server is reached over the network, fetched
without credentials, the kind decided on the bytes and never on the word of
the server, and the size kept small.

What leaves this module is one ``data:`` URL or nothing — never an address.
The interface draws it as a picture (``<img>``), so a vector one cannot run
anything and no page ever loads a foreign address. Whatever fails here leaves
the house's own mark in place; a logo must never keep a server from
connecting.
"""

from __future__ import annotations

import asyncio
import base64
import io
import logging
import re
from typing import Any
from urllib.parse import unquote_to_bytes

import httpx
from PIL import Image

from app.public_host import is_public

log = logging.getLogger(__name__)

# The largest picture taken, in bytes, and the longest side it may have.
MAX_BYTES = 196_608
MAX_EDGE = 512

_SVG_TAG = re.compile(r"<svg\b", re.IGNORECASE)
_SVG_ROOT = re.compile(r"<svg\b[^>]*>", re.IGNORECASE | re.DOTALL)
_PLAIN_NUMBER = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*(?:px)?\s*$", re.IGNORECASE)


def _decoded(source: str) -> bytes | None:
    """The bytes of a ``data:`` URL, or None where it is none."""
    header, comma, payload = source[5:].partition(",")
    # Base64 is a third larger than what it carries, a percent-encoded text
    # three times at most: more than that cannot fit the ceiling, and is not
    # decoded to find out.
    if not comma or len(payload) > MAX_BYTES * 3:
        return None
    try:
        if ";base64" in header.lower():
            return base64.b64decode(payload, validate=False)
        return unquote_to_bytes(payload)
    except ValueError:
        return None


def _starts_like_svg(text: str) -> bool:
    """Whether the text opens, after an optional prolog (XML declaration,
    comments, a document type), with the ``<svg`` tag. Walked with plain
    searches: a pattern with a lazy dot in a repeated group backtracks
    without end on a long run of comments."""
    index = 1 if text.startswith("\ufeff") else 0
    while True:
        while index < len(text) and text[index].isspace():
            index += 1
        for opening, closing in (("<?xml", "?>"), ("<!--", "-->"), ("<!doctype", ">")):
            if text[index:index + len(opening)].lower() == opening:
                end = text.find(closing, index + len(opening))
                if end < 0:
                    return False
                index = end + len(closing)
                break
        else:
            return _SVG_TAG.match(text, index) is not None


def _svg_edge_ok(text: str) -> bool:
    """Whether the vector says no more than the longest side it may have. A
    vector without sizes is as large as it is drawn, so it passes."""
    root = _SVG_ROOT.search(text)
    if root is None:
        return False
    tag = root.group(0)
    sizes = []
    for attribute in ("width", "height"):
        found = re.search(rf'\b{attribute}\s*=\s*"([^"]*)"', tag, re.IGNORECASE)
        number = _PLAIN_NUMBER.match(found.group(1)) if found else None
        if number:
            sizes.append(float(number.group(1)))
    box = re.search(r'\bviewBox\s*=\s*"([^"]*)"', tag, re.IGNORECASE)
    if not sizes and box:
        parts = box.group(1).replace(",", " ").split()
        if len(parts) == 4:
            try:
                sizes = [float(parts[2]), float(parts[3])]
            except ValueError:
                return False
    return all(size <= MAX_EDGE for size in sizes)


def as_data_url(data: bytes) -> str | None:
    """The picture as a ``data:`` URL where it passes the checks, else None."""
    # Read here and not at the top: the file reader imports the client this
    # module is imported by.
    from app.tools.datei_lesen import medientyp

    if not data or len(data) > MAX_BYTES:
        return None
    kind = medientyp(data)
    if kind is not None:
        try:
            with Image.open(io.BytesIO(data)) as image:
                width, height = image.size
        except Exception:  # noqa: BLE001 - whatever cannot be read is no logo
            return None
        if width > MAX_EDGE or height > MAX_EDGE:
            return None
    else:
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            return None
        if not _starts_like_svg(text) or not _svg_edge_ok(text):
            return None
        kind = "image/svg+xml"
    return f"data:{kind};base64," + base64.b64encode(data).decode("ascii")


async def _fetched(
    source: str, origin: str | None, transport: httpx.AsyncBaseTransport | None
) -> bytes | None:
    """The bytes behind an ``https:`` address, or None where it may not or
    cannot be fetched."""
    address = httpx.URL(source)
    if address.scheme != "https" or not address.host:
        return None
    if origin is not None:
        # A server reached over the network vouches for its own origin only.
        own = httpx.URL(origin)
        if (own.scheme, own.host, own.port or 0) != (address.scheme, address.host, address.port or 0):
            return None
    elif not await asyncio.to_thread(is_public, address.host):
        # A program on this machine has no origin; a public place is the
        # only one it may name.
        return None
    # No credentials, no cookies, no proxy from the environment, and no
    # redirect: a server that points its logo elsewhere has none.
    async with httpx.AsyncClient(
        follow_redirects=False, trust_env=False, transport=transport
    ) as client, client.stream("GET", source) as response:
        if response.status_code != 200:
            return None
        announced = response.headers.get("content-length", "")
        if announced.isdigit() and int(announced) > MAX_BYTES:
            return None
        body = bytearray()
        async for chunk in response.aiter_bytes():
            body.extend(chunk)
            if len(body) > MAX_BYTES:
                return None
    return bytes(body)


async def logo_of(
    icons: Any, origin: str | None = None, transport: httpx.AsyncBaseTransport | None = None
) -> str | None:
    """The first icon of ``icons`` that passes, as a ``data:`` URL.

    The pictures the server hands over itself are tried first, in the order
    it listed them; of the addresses only the first is asked, so a long list
    costs no more than one request. ``origin`` is the address of a server
    reached over the network; a server started on this machine has none.
    ``transport`` is for tests. Never raises: a logo is an extra, and a
    server must connect without it."""
    if not isinstance(icons, list):
        return None
    sources = [
        icon["src"] for icon in icons if isinstance(icon, dict) and isinstance(icon.get("src"), str)
    ]
    handed = [src for src in sources if src[:5].lower() == "data:"]
    named = [src for src in sources if src[:5].lower() != "data:"][:1]
    for source in handed + named:
        try:
            if source in handed:
                data = _decoded(source)
            else:
                data = await _fetched(source, origin, transport)
            logo = as_data_url(data) if data is not None else None
        except Exception:  # noqa: BLE001 - a logo must never keep a server from connecting
            log.info("A server's logo is not taken: it could not be read", exc_info=True)
            continue
        if logo is not None:
            return logo
    return None
