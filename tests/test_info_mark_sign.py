"""The small info mark beside a setting shows the house's i, not an exclamation mark.

`InfoMark.svelte` used to draw its own sign: a circle with a stroke above and a
dot below, which reads as an exclamation mark. The house sign `info`
(`Hauszeichen.svelte`) has the dot above and the stroke below, which reads as
an i; the mark now carries that sign, so it is one drawing wherever it stands.
"""

from __future__ import annotations

import re
from pathlib import Path

TEILE = Path(__file__).resolve().parent.parent / "frontend" / "src" / "teile"


def _source(name: str) -> str:
    return (TEILE / name).read_text(encoding="utf-8")


def test_the_info_mark_wears_the_house_i():
    mark = _source("InfoMark.svelte").split("<style>", 1)[0]
    assert "import Hauszeichen from './Hauszeichen.svelte'" in mark
    assert re.search(r'<Hauszeichen\s+zeichen="info"\s+groesse=\{14\}\s*/>', mark)
    # No drawing of its own: the stroke above the dot was the exclamation mark.
    assert "M12 8v5" not in mark and "<svg" not in mark


def test_the_house_sign_has_the_dot_above_and_the_stroke_below():
    sign = _source("Hauszeichen.svelte").split("{:else if zeichen === 'info'}", 1)[1].split("{:else if", 1)[0]
    assert '<circle cx="12" cy="12" r="9" />' in sign
    stroke = re.search(r'd="M12\s+([\d.]+)\s*v', sign)
    dot = re.search(r"M12\s+([\d.]+)\s*h\.01", sign)
    assert stroke and dot, sign
    # The dot stands higher (smaller y) than where the stroke begins: an i.
    # The dot of an exclamation mark stands below the end of its stroke.
    assert float(dot.group(1)) < float(stroke.group(1))


def test_silence_the_mark_keeps_its_name_its_states_and_its_keys():
    mark = _source("InfoMark.svelte")
    for kept in (
        'role="button"',
        "aria-label={t('bild.info')}",
        "aria-expanded={open}",
        'tabindex="0"',
        "event.key === 'Enter' || event.key === ' '",
        "event.key === 'Escape' && open",
        'role="note"',
    ):
        assert kept in mark, kept
    # Size, colours and focus stand as they were.
    style = mark.split("<style>", 1)[1]
    assert "width: 14px;" in style and "height: 14px;" in style
    assert "color: var(--text-still);" in style
    assert ".mark:focus-visible" in style


def test_the_five_places_still_carry_the_mark():
    for name in (
        "Serverabschnitt.svelte",
        "StudioDetails.svelte",
        "ImageSwitchRows.svelte",
        "BildGeraete.svelte",
        "StudioBasics.svelte",
    ):
        assert "<InfoMark" in _source(name), name
    # The picture server's model card hands its sentence to the head's mark.
    assert "modellInfo={t('bildserver.info_standardmodell')}" in _source("Bildserver.svelte")
