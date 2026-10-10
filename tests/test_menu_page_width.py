"""How wide a menu page is (`frontend/src/teile/Menueseite.svelte`).

Every menu page stands in one column in the middle of the window: its head
and its content share one rule, so the two cannot drift apart, and no page
brings a width of its own. On a wide window a narrow column left the cards
of a page as a strip with empty ground on both sides.

What stands in the column fills it. A part with a limit of its own — the
window panel of the server and cloud pages once had one — ends short of the
head above it and leaves the rest of the column empty.
"""

from __future__ import annotations

import re
from pathlib import Path

PAGE = Path(__file__).resolve().parent.parent / "frontend/src/teile/Menueseite.svelte"
WINDOW_PANEL = PAGE.parent / "Fenstertafel.svelte"
CLOUD_PAGE = PAGE.parent / "ModelleCloud.svelte"


def _rules() -> list[str]:
    """The bodies of the rules the head and the content share: the column
    itself, and its smaller side room on a narrow window."""
    source = PAGE.read_text(encoding="utf-8")
    found = re.findall(r"\.kopf,\s*\.breite\s*\{(.*?)\}", source, re.S)
    assert len(found) == 2, f"{len(found)} rules for '.kopf, .breite'"
    return found


def _declarations(rule: str) -> dict[str, str]:
    rule = re.sub(r"/\*.*?\*/", "", rule, flags=re.S)
    pairs = (line.split(":", 1) for line in rule.split(";") if ":" in line)
    return {name.strip(): value.strip() for name, value in pairs}


def test_a_menu_page_is_1400_wide_at_most():
    """And the note beside the number says what is left for the content:
    the width less the two side paddings inside it."""
    assert _declarations(_rules()[0])["max-width"] == "1400px"
    assert "1336 of content" in _rules()[0]


def test_the_column_keeps_its_side_paddings_and_stands_in_the_middle():
    """The silence check: only the width moved. The paddings are inside it
    (border-box), so the content is the width less the two of them."""
    column = _declarations(_rules()[0])
    assert column["padding-left"] == column["padding-right"] == "32px"
    assert column["box-sizing"] == "border-box"
    assert column["margin"] == "0 auto"
    assert column["width"] == "100%"


def _width_limits(part: Path) -> list[str]:
    """Every `max-width` a part sets, in its style block or on an element.
    A media query sets none: it asks how wide the window is."""
    source = re.sub(r"/\*.*?\*/|<!--.*?-->", "", part.read_text(encoding="utf-8"), flags=re.S)
    return re.findall(r"(?<!\()max-width\s*(?:=|:\s*[^;{})\"']+)", source)


def test_no_page_brings_a_second_width():
    """One width for every menu page: the file sets a `max-width` once, in
    whatever unit, and the narrow-window rule only takes side room away."""
    assert len(_width_limits(PAGE)) == 1
    assert _declarations(_rules()[1]) == {"padding-left": "16px", "padding-right": "16px"}


def test_the_window_panel_fills_the_column():
    """The server windows and the cloud pages stand in the window panel; it
    is as wide as the head of the page above it."""
    assert _width_limits(WINDOW_PANEL) == []


def test_the_empty_tile_of_the_cloud_page_fills_the_column():
    """It stands in the column directly, without the panel around it."""
    tile = re.search(r"\.leerkachel\s*\{(.*?)\}", CLOUD_PAGE.read_text(encoding="utf-8"), re.S)
    assert tile, "the cloud page has no empty tile"
    declared = _declarations(tile.group(1))
    assert "max-width" not in declared
    assert declared["width"] == "100%"
    assert declared["min-height"] == "240px"
