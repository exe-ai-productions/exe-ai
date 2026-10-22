"""The view of a chosen schedule on the phone: its four facts stand two by two
and a word breaks only where it does not fit a line, and its three buttons
stand one under the other.

The page is shared with the desktop, so the phone's rules are written
under `html[data-phone]`; what these checks read is the style block of the
page — the phone's rules say what they must, and the rules without that
prefix, the desktop's, stay as they were.
"""

from __future__ import annotations

from tests.cronjob_style import FRONTEND, PHONE, base_rules, declared, without_comments
from tests.cronjob_style import rules as read_rules


def test_on_the_phone_the_four_facts_stand_two_by_two():
    # The pop-up is one column wide on both, so the one base rule serves the
    # phone too and no rule of its own is left.
    rules = base_rules()
    assert declared(rules[".raster"], "grid-template-columns") == "repeat(2, minmax(0, 1fr))"
    assert f"{PHONE} .raster" not in rules


def test_on_the_phone_a_word_breaks_only_where_it_does_not_fit_a_line():
    rules = base_rules()
    assert declared(rules[f"{PHONE} .zelle"], "overflow-wrap") == "break-word"


def test_on_the_phone_the_three_buttons_stand_one_under_the_other_over_the_whole_width():
    rules = base_rules()
    row = rules[f"{PHONE} .knoepfe"]
    assert declared(row, "display") == "grid"
    assert declared(row, "grid-template-columns") == "minmax(0, 1fr)"
    assert declared(row, "grid-auto-flow") == "row"


def test_on_the_phone_a_button_is_44_px_high():
    rules = base_rules()
    assert declared(rules[f"{PHONE} .knopf"], "height") == "44px"


def test_a_button_wears_the_face_of_the_other_buttons_on_the_phone_and_the_desktop():
    # The same surface and the same edge as `.button`, the one class of the
    # buttons of every phone page, in every look; the glass is the page's own
    # face, so the phone's rule only sets the height.
    shared = read_rules(without_comments((FRONTEND / "stil" / "global.css").read_text(encoding="utf-8")))[".button"]
    mine = base_rules()[".knopf"]
    assert declared(mine, "background") == declared(shared, "background") == "var(--glass-button)"
    assert declared(mine, "box-shadow") == declared(shared, "box-shadow") == "inset 0 0 0 1px var(--feldstrich)"
    hover = base_rules()[".knopf:hover:not(:disabled)"]
    assert declared(hover, "background") == "var(--glass-hover)"
    phone = base_rules()[f"{PHONE} .knopf"]
    assert declared(phone, "background") is None and declared(phone, "box-shadow") is None


def test_silence_without_the_phone_the_desktop_keeps_the_row_of_buttons_and_their_size():
    rules = base_rules()
    assert declared(rules[".knoepfe"], "display") == "flex"
    assert declared(rules[".knoepfe"], "justify-content") == "space-between"
    assert declared(rules[".knopf"], "min-width") == "140px"
    assert declared(rules[".knopf"], "height") == "36px"
