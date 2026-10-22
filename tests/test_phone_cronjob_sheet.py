"""The day, a schedule and its form on the phone: a sheet from the bottom edge
over the whole width, not the desktop's pop-up beside a day.

The page is shared between the desktop and the phone, so what these checks
read is the wiring: the phone hands the page its sheet, the page puts the
views into that sheet when it has one and into the pop-up otherwise, and the
desktop never hands it one.
"""

from __future__ import annotations

import re
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "frontend" / "src"
PAGE = SRC / "teile" / "SettingsCronjobs.svelte"
PHONE_PAGE = SRC / "phone" / "settings" / "Cronjobs.svelte"
DESKTOP_WINDOW = SRC / "teile" / "SystemPrompt.svelte"
SHEET = SRC / "phone" / "Sheet.svelte"


def _markup() -> str:
    """The page without its script and its styles."""
    source = PAGE.read_text(encoding="utf-8")
    source = re.sub(r"<script>.*?</script>", "", source, flags=re.S)
    return re.sub(r"<style>.*?</style>", "", source, flags=re.S)


def _branches() -> tuple[str, str]:
    """The markup of the page where it has a sheet, and where it has none."""
    markup = _markup()
    start = markup.index("{#if Blatt}")
    middle = markup.index("{:else}", start)
    end = markup.index("{/if}", middle)
    return markup[start:middle], markup[middle:end]


def test_the_phone_hands_the_page_its_own_sheet():
    source = PHONE_PAGE.read_text(encoding="utf-8")
    assert "import Sheet from '../Sheet.svelte'" in source
    assert re.search(r"<SettingsCronjobs\b[^\n]*\bBlatt=\{Sheet\}", source)
    assert SHEET.is_file()


def test_with_a_sheet_the_views_stand_in_it_and_not_in_a_pop_up():
    with_sheet, _ = _branches()
    # The day, the schedule and the form are one snippet both places draw.
    assert "<Blatt" in with_sheet and "{@render viewContent(own)}" in with_sheet
    assert "<ScheduleForm" in _markup()
    assert "popover" not in with_sheet
    # The veil of the sheet closes the form like the Cancel button does.
    assert re.search(r"<Blatt\b[^\n]*onclose=\{\(\) => geschlossen\(\)\}", with_sheet)
    assert "onclick={onclose}" in SHEET.read_text(encoding="utf-8")


def test_a_sheet_has_no_opener_to_stand_beside():
    script = re.search(r"<script>(.*?)</script>", PAGE.read_text(encoding="utf-8"), re.S).group(1)
    opening = script[script.index("async function zeigen("):]
    opening = opening[: opening.index("\n  }\n")]
    assert opening.index("if (Blatt) return") < opening.index("showPopover()")


def test_silence_without_a_sheet_the_views_stay_in_the_pop_up():
    _, without_sheet = _branches()
    assert 'popover="auto"' in without_sheet and "{@render viewContent(own)}" in without_sheet
    assert "showPopover()" in PAGE.read_text(encoding="utf-8")


def test_silence_the_desktop_never_hands_the_page_a_sheet():
    source = DESKTOP_WINDOW.read_text(encoding="utf-8")
    usage = re.search(r"<SettingsCronjobs\b[^\n]*", source)
    assert usage is not None
    assert "Blatt" not in usage.group(0)
