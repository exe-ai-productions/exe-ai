"""What a fresh installation shows from the first picture on.

The window, its splash and the interface open on one look, and the right
column stands open on the CLI tab, wide enough for the whole wordmark. Where
anything is stored — a layout, a chosen look, a kept frame colour — that wins,
as it always did.
"""

from __future__ import annotations

import re
from pathlib import Path

from app import layoutwahl, moduswahl
from cli import render

ROOT = Path(__file__).resolve().parent.parent
ANZEIGE = ROOT / "frontend/src/lib/anzeige.js"
RAIL = ROOT / "frontend/src/lib/arbeitsleiste.svelte.js"


def _interface_source() -> str:
    return ANZEIGE.read_text(encoding="utf-8")


def test_a_fresh_installation_follows_the_device_in_both_copies():
    """The interface's copy and the service's answer agree on Auto, so the look
    does not change on the way up."""
    held = re.search(r"^export const VORGABE_MODUS = '(\w+)'$", _interface_source(), re.M)
    assert held, "anzeige.js names no VORGABE_MODUS"
    assert held.group(1) == "auto"
    assert moduswahl.VORGABE == {"modus": "auto"}
    assert moduswahl.aufgeloest(None) == {"modus": "auto"}


def test_a_chosen_look_still_wins_over_the_default(client):
    """Silence probe: whoever chose Exe, Pearl or Snow keeps it."""
    for modus in ("dunkel", "hell", "snow", "auto"):
        client.put("/api/v1/settings/global/modus", json={"wert": {"modus": modus}})
        assert client.get("/api/v1/settings/resolved/modus").json()["wert"] == {"modus": modus}


def test_the_right_column_opens_on_the_cli_tab_at_the_width_of_the_whole_wordmark():
    assert layoutwahl.VORGABE["leiste_offen"] is True
    assert layoutwahl.VORGABE["leiste_modul"] == "cli"
    assert layoutwahl.VORGABE["leiste_breite"] == layoutwahl.PANEL_DEFAULT_WIDTH
    # The tab the column opens on is one the column has.
    assert "'cli'" in re.search(r"export const MODULE = \[(.*?)\]", RAIL.read_text(encoding="utf-8")).group(1)
    # The width stands where a drag can put it, and the narrowest drag stays.
    assert layoutwahl.LEISTE_MIN == 364
    assert layoutwahl.LEISTE_MIN <= layoutwahl.PANEL_DEFAULT_WIDTH <= layoutwahl.LEISTE_MAX
    # The whole wordmark is what the width is measured for: 60 columns.
    assert render.WORDMARK_FROM == 60


def test_the_interface_and_the_service_hold_one_width():
    named = re.search(r"^export const PANEL_DEFAULT_WIDTH = (\d+)$", _interface_source(), re.M)
    assert named, "anzeige.js names no PANEL_DEFAULT_WIDTH"
    assert int(named.group(1)) == layoutwahl.PANEL_DEFAULT_WIDTH
    layout = re.search(r"export const VORGABE_LAYOUT = \{\n(.*?)\n\}", _interface_source(), re.S)
    assert layout
    assert "leiste_breite: PANEL_DEFAULT_WIDTH," in layout.group(1)
    assert "leiste_offen: true," in layout.group(1)
    assert "leiste_modul: 'cli'," in layout.group(1)


def test_a_stored_layout_wins_over_the_open_column():
    """Silence probe: a column the user folded stays folded, on the tab and at
    the width they left it; what was never stored comes from the defaults."""
    stored = {"leiste_offen": False, "leiste_modul": "vorschau", "leiste_breite": 400}
    resolved = layoutwahl.aufgeloest(stored)
    assert resolved["leiste_offen"] is False
    assert resolved["leiste_modul"] == "vorschau"
    assert resolved["leiste_breite"] == 400
    assert resolved["seitenleiste_zu"] is True
    # A narrow width stored long ago is not widened to the new default.
    assert layoutwahl.aufgeloest({"leiste_breite": 364})["leiste_breite"] == 364
