"""The instructions page of the settings: the order of the rows under the
prompt field, the switch for suspending without a colour of its own, and the
foot's two signs that stand only for a changed text.

The phone reads the order: the form of address, the greeting, the suspension,
then the three rounds and limits. The desktop page has no suspension any more:
the switch lives in the plus menu of the input bar (`Eingabeleiste.svelte`).
"""

from __future__ import annotations

import re
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "frontend" / "src"
DESKTOP = SRC / "teile" / "SystemPrompt.svelte"
PHONE = SRC / "phone" / "settings" / "TextFile.svelte"

ORDER = [
    "editor.anrede_titel",
    "editor.anrede_schalter",
    "systemprompt.aussetzen",
    "editor.werkzeugrunden_titel",
    "editor.befehlszeit_titel",
    "editor.kontextkomprimierung_titel",
]


DESKTOP_ORDER = [key for key in ORDER if key != "systemprompt.aussetzen"]


def _positions(source: str, order: list[str] = ORDER) -> list[int]:
    """Where each row's first label stands, in the order of the rows."""
    return [source.index(f"t('{key}')") for key in order]


def test_the_desktop_rows_follow_the_order_under_the_prompt_field():
    source = DESKTOP.read_text(encoding="utf-8")
    field = source.index("<WachsendesFeld")
    rows = source.index("{#if istSystem}", field)
    block = source[rows : source.index('<div class="fuss">', rows)]
    positions = _positions(block, DESKTOP_ORDER)
    assert positions == sorted(positions)
    assert "systemprompt.aussetzen" not in block, "the switch moved into the plus menu"


def test_the_phone_rows_follow_the_same_order():
    source = PHONE.read_text(encoding="utf-8")
    block = source.split("{#if kind === 'system'}\n  <Group>", 1)[1].split("</Group>", 1)[0]
    positions = _positions(block)
    assert positions == sorted(positions)


def test_the_suspension_switch_carries_no_colour_of_its_own_on_the_phone():
    source = PHONE.read_text(encoding="utf-8")
    assert "eingriff" not in source
    element = re.search(r"<Toggle\b[^\n]*(?:systemprompt\.aussetzen|ausgesetzt)", source)
    assert element
    tag = source[element.start() : source.index("/>", element.start())]
    assert " art=" not in tag


def test_the_desktop_settings_page_has_no_suspension_switch_and_the_search_finds_none():
    source = DESKTOP.read_text(encoding="utf-8")
    assert "systemprompt.aussetzen" not in source and "aussetzen(" not in source
    assert "systemprompt.aussetzen" not in (SRC / "lib" / "einstellungsliste.js").read_text(encoding="utf-8")


def test_the_number_fields_keep_their_own_width_and_do_not_stretch():
    desktop = DESKTOP.read_text(encoding="utf-8").split("<style>", 1)[1]
    assert re.search(r"\.zahlfeld \{\s*width: 108px;\s*flex: none;", desktop)
    phone = PHONE.read_text(encoding="utf-8").split("<style>", 1)[1]
    assert re.search(r"\.digits \{\s*width: 140px;\s*flex: none;", phone)
