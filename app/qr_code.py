"""The QR code of an address, as a vector graphic.

The settings page of the web app shows it beside the address, so a phone
reads the address with its camera. A vector graphic in one colour: a code
is read dark on light, so it stays black and the page gives it a light ground
in every look. The code carries no quiet zone of its own: the light ground the
page draws around it is the zone.
"""

from __future__ import annotations

import io
from functools import lru_cache

import segno


@lru_cache(maxsize=8)
def svg(address: str) -> str:
    """The code of ``address`` as the text of an SVG: modules as one path,
    black, with no border (``border=0``): the page lets the code run to a few
    pixels of the edge of its light ground.
    The size is left to the page: the drawing carries a view box and scales."""
    code = segno.make(address, error="m")
    out = io.BytesIO()
    code.save(out, kind="svg", xmldecl=False, nl=False, scale=1, border=0, dark="#000000", light=None, omitsize=True)
    return out.getvalue().decode("utf-8")
