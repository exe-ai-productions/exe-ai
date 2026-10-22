"""The layout mode: every control beside its slider is a number field.

A slider alone never lands on an exact value such as 900 or 32. Each row
carries the house's number field on the same value as the slider: type the
number, press the arrows in the field or ↑/↓ on the keyboard, in steps of
one, inside the limits of the row. Read off the source.
"""

from __future__ import annotations

import re
from pathlib import Path

SOURCE = (Path(__file__).resolve().parent.parent / "frontend/src/teile/Layoutmodus.svelte").read_text(encoding="utf-8")
MARKUP = SOURCE.split("</script>", 1)[1].split("<style>", 1)[0]
SLIDER_ROW = MARKUP.split("{#each regler as r (r.id)}", 1)[1].split("{/each}", 1)[0]


def test_every_slider_row_has_a_number_field_on_the_same_value():
    slider = re.search(r"<Schieberegler\s+bind:wert=\{werte\[r\.id\]\}", SLIDER_ROW)
    field = re.search(r"<Zahlenfeld\s+bind:wert=\{werte\[r\.id\]\}", SLIDER_ROW)
    assert slider and field
    assert slider.start() < field.start()


def test_the_number_field_takes_the_limits_of_its_row_and_whole_numbers_only():
    field = re.search(r"<Zahlenfeld[^>]*>", SLIDER_ROW, re.S).group(0)
    assert "min={r.von}" in field
    assert "max={r.bis}" in field
    assert "ganzzahlig" in field
    assert "schritt" not in field, "the step stays the field's own one"


def test_the_slider_and_the_field_share_the_limits_of_the_row():
    slider = re.search(r"<Schieberegler[^>]*>", SLIDER_ROW, re.S).group(0)
    assert "min={r.von}" in slider
    assert "max={r.bis}" in slider


def test_no_read_only_figure_is_left_beside_the_slider():
    assert "<output" not in MARKUP
    assert "mit_zahl={false}" in SLIDER_ROW


def test_the_percent_sign_stays_beside_the_number():
    assert re.search(r"\{#if r\.einheit\}<span class=\"unit\">\{r\.einheit\}</span>\{/if\}", SLIDER_ROW)


def test_the_font_row_keeps_its_own_field_and_the_foot_its_buttons():
    """Silence: the font row, the default / cancel / save foot and the table
    of limits stay as they were."""
    font_row = MARKUP.split("{#each regler", 1)[0]
    assert "bind:wert={werte.schrift} min={schrift.von} max={schrift.bis} ganzzahlig" in font_row
    for call in ("onclick={standard}", "onclick={schliessen}", "onclick={sichern}"):
        assert call in MARKUP


def test_the_window_keeps_its_width_and_the_unit_hangs_in_the_padding():
    style = SOURCE.split("<style>", 1)[1]
    assert re.search(r"\.layoutmodus \{[^}]*width: 440px;", style, re.S)
    unit = re.search(r"\.unit \{[^}]*\}", style, re.S).group(0)
    assert "position: absolute" in unit
    assert "left: 100%" in unit
