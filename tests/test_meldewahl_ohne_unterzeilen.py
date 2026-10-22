"""The page of the sounds and notices (Settings > Notices) shows its rows
with their label alone: no line of explanation stands under them.

The five rows that carried one — sounds, volume, sounds only in the
background, listen, popup display time — stand like the rows of the groups
below them. Read off the source and the two language files."""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PAGE = ROOT / "frontend" / "src" / "teile" / "Meldewahl.svelte"
LOCALES = ROOT / "app" / "locales"

HINTS = (
    "toene_hinweis",
    "lautstaerke_hinweis",
    "nur_hintergrund_hinweis",
    "probe_hinweis",
    "popup_hinweis",
)
LABELS = ("toene", "lautstaerke", "nur_hintergrund", "probe", "popup")


def _source() -> str:
    return PAGE.read_text(encoding="utf-8")


def test_the_page_reads_no_key_that_ends_in_hint_and_carries_no_hint_rule():
    source = _source()
    assert not re.search(r"meldewesen\.\w*_hinweis", source)
    assert "hinweis" not in source
    style = source.split("<style>", 1)[1]
    assert ".hinweis" not in style


def test_the_five_hints_are_gone_from_both_language_files():
    for locale in ("de", "en"):
        texts = json.loads((LOCALES / f"{locale}.json").read_text(encoding="utf-8"))
        for hint in HINTS:
            assert hint not in texts["meldewesen"], (locale, hint)


def test_the_labels_of_the_five_rows_stay_in_the_page_and_in_both_files():
    """Silence probe: only the lines under them go."""
    source = _source()
    for locale in ("de", "en"):
        texts = json.loads((LOCALES / f"{locale}.json").read_text(encoding="utf-8"))
        for label in LABELS:
            assert texts["meldewesen"][label], (locale, label)
    for label in LABELS:
        assert f"t('meldewesen.{label}')" in source, label


def test_a_row_without_a_line_is_one_text_in_its_cell():
    """Each of the four labels that still head a row stands alone in its
    cell, like the rows of the group below them; the two that carry an info
    mark have the mark right after the label and nothing else. The fifth,
    the word of the test buttons, is the label of a button in each row of
    the table and no longer the label of a row of its own."""
    source = _source()
    for label in ("lautstaerke", "popup"):
        assert f"<div class=\"zeilentext\">{{t('meldewesen.{label}')}}</div>" in source, label
    for label in ("toene", "nur_hintergrund"):
        assert (
            f"<div class=\"zeilentext mitmarke\">{{t('meldewesen.{label}')}}"
            f"<InfoMark text={{t('meldewesen.info_{label}')}} /></div>"
        ) in source, label
