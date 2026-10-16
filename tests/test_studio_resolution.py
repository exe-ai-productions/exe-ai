"""The resolution of the picture in the area stands above the area's name.

Only while a picture lies in the area: the picture's own width × height, in
whole pixels, in a row of the same style over the row "Generation area · W ×
H". Without a picture, or after the picture was taken away, there is only the
area's row. The surface is read off its source
(`frontend/src/teile/StudioCanvas.svelte`); what the browser draws of it is
measured in the report of the order.
"""

from __future__ import annotations

import re
from pathlib import Path

CANVAS = (
    Path(__file__).resolve().parent.parent / "frontend/src/teile/StudioCanvas.svelte"
).read_text(encoding="utf-8")

FRONTEND = Path(__file__).resolve().parent.parent / "frontend"

AREA_ROW = (
    '<div class="bereichsname" style="left:{bereich.x}px;top:{bereich.y - 36}px">'
)


def _picture_row() -> str:
    found = re.search(
        r"\{#if natur\.w\}\n(?:    <!--.*?-->\n)?    <div class=\"bereichsname\".*?\n  \{/if\}\n",
        CANVAS,
        re.S,
    )
    assert found, "the row of the picture's resolution is gone"
    return found.group(0)


def test_the_resolution_row_stands_only_while_a_picture_lies_in_the_area():
    row = _picture_row()
    # `natur` is the measured size of the picture the area shows now: zero
    # without a picture and for one that did not load.
    assert row.startswith("{#if natur.w}")
    assert "const natur = $derived(\n    bildUrl && gemessen.url === bildUrl" in CANVAS


def test_the_row_names_the_pictures_own_size_in_whole_pixels():
    row = _picture_row()
    assert "<span>{natur.w} × {natur.h}</span>" in row
    # The area's size is not what it shows.
    assert "{gw}" not in row and "{gh}" not in row


def test_the_row_is_the_areas_row_in_the_same_style_one_row_higher():
    row = _picture_row()
    assert 'class="bereichsname"' in row
    # The area's row is 26 px high and stands 36 above the area; this one
    # stands 30 above that, with a gap of four.
    assert "top:{bereich.y - 66}px" in row
    assert "left:{bereich.x}px" in row
    # And the area's row itself is as it was, always there.
    assert AREA_ROW in CANVAS
    assert CANVAS.index(row) < CANVAS.index(AREA_ROW)


def test_the_row_takes_a_sign_and_a_label_the_house_has():
    row = _picture_row()
    assert '<Hauszeichen zeichen="bild" groesse={14} />' in row
    assert "aria-label={t('bild.startbild')}" in row


def test_the_row_stands_clear_of_the_bar_of_the_brush():
    """The bar ends 52 px from the top; the area stands at least TOP_ROOM
    from it, so the row — 66 above the area — keeps a gap to the bar even
    when the area is as high as it can be."""
    area = (FRONTEND / "src/lib/studioArea.js").read_text(encoding="utf-8")
    margin = int(re.search(r"const TOP_ROOM = (\d+)", area).group(1))
    assert margin - 66 >= 52 + 4
