"""Settings > Notices: the popups stand in a block of their own.

The rows of the group "Meldungen" carry the test button and one switch, the
sound; the popup switches stand below in their own block, one switch to a row:
first "turn popups off", then the display time, then the four occurrences.
Read off the source."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PAGE = (ROOT / "frontend" / "src" / "teile" / "Meldewahl.svelte").read_text(encoding="utf-8")


def _markup() -> str:
    return PAGE.split("<style>", 1)[0]


def _sections() -> list[str]:
    return re.findall(r'<section class="block[^"]*">.*?</section>', _markup(), re.S)


def _popup_block() -> str:
    found = [s for s in _sections() if 'class="block popup-block"' in s]
    assert len(found) == 1, "one popup block"
    return found[0]


def _rows(block: str) -> list[str]:
    return re.findall(r'<div class="einstellkachel[^"]*"[^>]*>.*?(?=<div class="einstellkachel|</div>\s*</section>)', block, re.S)


def test_the_rows_with_the_test_button_carry_exactly_one_switch_the_sound():
    meldungen = _sections()[1]
    assert "meldewesen.gruppe_meldungen" in meldungen
    row = meldungen.split("{#each MELDER as name (name)}", 1)[1].split("{/each}", 1)[0]
    assert row.count("<Schalter") == 1 and "setSound(name, an)" in row and 'class="probe"' in row
    assert "melderSchalten" not in row and "spalte_popup" not in meldungen


def test_the_column_head_shows_only_the_sound_over_the_switch():
    head = re.search(r'<div class="einstellkachel table-head".*?</div>', _markup(), re.S)
    assert head
    assert head.group(0).count('class="column"') == 1 and "meldewesen.spalte_ton" in head.group(0)


def test_the_popup_block_has_its_title_from_the_existing_text():
    block = _popup_block()
    assert "{t('meldewesen.spalte_popup')}" in block.split("kachelliste", 1)[0]


def test_the_block_runs_popups_off_then_the_display_time_then_the_four_occurrences():
    block = _popup_block()
    off = block.index("popupsAusSchalten")
    seconds = block.index("bind:wert={sekunden}")
    each = block.index("{#each MELDER as name (name)}")
    assert off < seconds < each


def test_the_popup_switches_stand_only_in_the_block_one_switch_to_a_row():
    markup = _markup()
    assert markup.count("melderSchalten(name, an)") == 1
    block = _popup_block()
    assert block.count("melderSchalten(name, an)") == 1
    loop = block.split("{#each MELDER as name (name)}", 1)[1].split("{/each}", 1)[0]
    assert loop.count("<Schalter") == 1
    # The block's other rows are a switch and a number field: popups off, the display time.
    assert block.count("<Schalter") == 2 and block.count("<Zahlenfeld") == 1


def test_the_display_time_still_greys_out_with_popups_off():
    block = _popup_block()
    assert "class:grau={meldewesen.popupsAus}" in block and "gesperrt={meldewesen.popupsAus}" in block


def test_the_switch_column_is_as_wide_as_the_switch_so_it_stands_on_the_line_of_the_others():
    style = PAGE.split("<style>", 1)[1]
    column = re.search(r"\.column \{(.*?)\}", style, re.S)
    assert column and "width: 34px;" in column.group(1)


def test_sound_block_is_called_notification_sounds():
    """After the popups moved into their own block, the group above them holds
    only the test button and the sound switch of each occurrence, and its
    heading says so, in both languages. The neighbours keep their words."""
    import json

    texts = {
        name: json.loads((ROOT / "app" / "locales" / f"{name}.json").read_text(encoding="utf-8"))["meldewesen"]
        for name in ("de", "en")
    }
    assert texts["de"]["gruppe_meldungen"] == "Benachrichtigungstöne"
    assert texts["en"]["gruppe_meldungen"] == "Notification sounds"
    assert texts["de"]["gruppe_toene"] != texts["de"]["gruppe_meldungen"]
    assert texts["de"]["spalte_popup"] == texts["en"]["spalte_popup"] == "Popup"
    assert texts["de"]["gruppe_visuell"] == "Visuelles Feedback"
    # The page still reads the one key for its group heading.
    assert "meldewesen.gruppe_meldungen" in PAGE
