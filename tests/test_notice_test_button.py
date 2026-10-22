"""The test button of each notification (Settings > Notices) is a loudspeaker.

One square sign with no colour and no word; the word stays as the tooltip and
the label for assistive tools. The sign is the catalogue's own `volume-2`,
three paths unchanged, and its licence is named with the others. Read off the
sources."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PAGE = (ROOT / "frontend" / "src" / "teile" / "Meldewahl.svelte").read_text(encoding="utf-8")
SIGNS = (ROOT / "frontend" / "src" / "teile" / "Hauszeichen.svelte").read_text(encoding="utf-8")
NOTICES = (ROOT / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")

# The three paths of Lucide's volume-2, as the catalogue draws them.
VOLUME_2 = (
    "M11 4.702a.705.705 0 0 0-1.203-.498L6.413 7.587A1.4 1.4 0 0 1 5.416 8H3a1 1 0 0 0-1 1v6a1 1 0 0 0 1 1h2.416"
    "a1.4 1.4 0 0 1 .997.413l3.383 3.384A.705.705 0 0 0 11 19.298z",
    "M16 9a5 5 0 0 1 0 6",
    "M19.364 18.364a9 9 0 0 0 0-12.728",
)


def _button() -> str:
    found = re.search(r'<button class="probe".*?</button>', PAGE, re.S)
    assert found, "the test button is gone"
    return found.group(0)


def _speaker_branch() -> str:
    found = re.search(r"zeichen === 'speaker'\}(.*?)\{:else if", SIGNS, re.S)
    assert found, "the house signs know no speaker"
    return found.group(1)


def test_the_test_button_wears_the_speaker_and_no_dot_and_no_word():
    button = _button()
    assert '<Hauszeichen zeichen="speaker" groesse={20} />' in button
    assert "Leuchtpunkt" not in button and "FARBEN" not in PAGE
    assert "Leuchtpunkt" not in PAGE
    # The word is the tooltip and the label, not text in the button.
    assert "title={t('meldewesen.probe')}" in button and "aria-label={t('meldewesen.probe')}" in button
    assert ">\n            {t('meldewesen.probe')}" not in button


def test_the_button_is_a_square_of_32_and_the_header_leaves_the_same_room():
    style = PAGE.split("<style>", 1)[1]
    probe = re.search(r"\.probe \{(.*?)\}", style, re.S)
    space = re.search(r"\.test-space \{(.*?)\}", style, re.S)
    assert probe and space
    assert "width: 32px;" in probe.group(1) and "height: 32px;" in probe.group(1)
    assert "width: 32px;" in space.group(1)
    assert "color: var(--text);" in probe.group(1)


def test_the_house_sign_is_the_catalogue_drawing_with_its_three_paths_unchanged():
    branch = _speaker_branch()
    assert re.findall(r'<path d="([^"]+)"', branch) == list(VOLUME_2)
    assert "stroke-width" not in branch and "fill=" not in branch


def test_the_licence_notice_names_the_new_sign():
    lucide = NOTICES.split("## Lucide", 1)[1].split("```", 1)[0]
    assert "`speaker`" in lucide and "`volume-2`" in lucide
