"""While the question card stands over the chat, Tab must not run into what is
behind it: the chat head, the history and the part with the input bar are
`inert`, as they are under an open menu page. The card and its veil stay
operable (the veil moves itself into the chat column, outside those parts),
and a question pushed away with "later" makes nothing unreachable.

After an answer, "later" or a question brought back, the focus goes to the
field only once the bar is reachable again — in the render after the change.

The interface files are read as source; the module's own part is in
`test_questionbox_row.py`.
"""

from __future__ import annotations

import re
from pathlib import Path

FRONTEND = Path(__file__).resolve().parent.parent / "frontend" / "src"
APP = FRONTEND / "App.svelte"
BAR = FRONTEND / "teile" / "Eingabeleiste.svelte"
CARD = FRONTEND / "teile" / "QuestionBox.svelte"


def _open_tag(source: str, css_class: str) -> str:
    match = re.search(r'<div class="%s"[^>]*?>' % css_class, source, re.S)
    assert match, f"no div with class {css_class}"
    return match.group(0)


def test_head_history_and_bar_are_inert_while_the_card_stands():
    source = APP.read_text(encoding="utf-8")
    for css_class in ("chatkopf", "verlauf", "anlauf"):
        assert "inert={seiteOffen || studioAn || kartenSteht}" in _open_tag(source, css_class), css_class
    assert "const kartenSteht = $derived(questionCardStands(zustand.aktiverChat))" in source


def test_the_menu_page_keeps_its_own_inert_and_the_card_does_not_reach_it():
    source = APP.read_text(encoding="utf-8")
    assert re.search(r'<div class="untermseite"[^>]*inert=\{seiteOffen\}>', source)
    assert "kartenSteht" not in _open_tag(source, "untermseite")


def test_the_bar_and_the_app_ask_the_same_place_whether_the_card_stands():
    app = APP.read_text(encoding="utf-8")
    bar = BAR.read_text(encoding="utf-8")
    assert "questionCardStands(zustand.aktiverChat)" in app
    assert "const cardStands = $derived(questionCardStands(zustand.aktiverChat))" in bar
    assert "{#if cardStands}" in bar


def test_the_veil_leaves_the_inert_parts_for_the_chat_column():
    card = CARD.read_text(encoding="utf-8")
    assert "const column = node.closest('main')" in card
    assert "column?.appendChild(node)" in card
    assert '<div class="veil" use:intoColumn' in card


def test_the_field_takes_the_focus_only_in_the_render_after_the_change():
    bar = BAR.read_text(encoding="utf-8")
    helper = re.search(r"function focusFieldAfterRender\(\) \{\n(.*?)\n  \}", bar, re.S)
    assert helper and "tick().then(() => feld?.focus())" in helper.group(1)
    for name in ("answerTool", "answerAsk", "later", "resume"):
        body = re.search(r"  function %s\(.*?\n  \}\n" % name, bar, re.S)
        assert body, name
        assert "focusFieldAfterRender()" in body.group(0), name
        assert "feld?.focus()" not in body.group(0), name
