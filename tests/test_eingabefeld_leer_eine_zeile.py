"""The empty input field is one line high in every width.

Measured in the browser: a field that is narrow at the moment it is measured
wraps its placeholder, and `scrollHeight` counts the wrapped words — an empty
field then took the height of up to two fifths of the window and kept it
after the window grew again, because the height was measured only when the
text or the window changed, not when the field's own width did.

The bar is a component whose logic lives in its instance script, so — like
the other checks of this field in tests/test_dictation_mirror.py — the wiring
is read as source text.
"""

from __future__ import annotations

from pathlib import Path

BAR = (
    Path(__file__).resolve().parent.parent / "frontend/src/teile/Eingabeleiste.svelte"
).read_text(encoding="utf-8")


def _height_function() -> str:
    return BAR.split("function hoeheAnpassen()", 1)[1].split("\n  }\n", 1)[0]


def test_an_empty_field_is_measured_without_its_placeholder():
    body = _height_function()
    assert "const platzhalter = feld.placeholder" in body
    assert "if (!feld.value) feld.placeholder = ''" in body
    # Taken away before the measuring, handed back right after it.
    assert body.index("feld.placeholder = ''") < body.index("feld.scrollHeight")
    assert body.index("feld.scrollHeight") < body.index("feld.placeholder = platzhalter")
    assert body.index("feld.placeholder = platzhalter") < body.index("feld.style.height = groesse.height")


def test_the_height_is_measured_again_when_the_width_of_the_field_changes():
    assert "new ResizeObserver(" in BAR
    block = BAR.split("const beobachter = new ResizeObserver(", 1)[1].split("return () => beobachter.disconnect()", 1)[0]
    # Only a change of width counts: the field's own height changing is the
    # result of measuring, not a reason for it.
    assert "if (feld.clientWidth === breite) return" in block
    assert "hoeheAnpassen()" in block
    assert "beobachter.observe(feld)" in block


def test_silence_the_cap_and_the_dictation_floor_stay_as_they_were():
    body = _height_function()
    assert "fieldHeight: feld.scrollHeight," in body
    assert "windowHeight: window.innerHeight," in body
    assert "floorHeight: spiegel ? diktatHoehe : 0," in body
    assert "diktatHoehe = spiegel ? parseInt(groesse.height, 10) : 0" in body
    dictation = (BAR.split("onresize={hoeheAnpassen}", 1))
    assert len(dictation) == 2  # the window's own resize still measures
