"""The main buttons of the menu pages, masks and windows are button glass.

Only Send in the input bar stays filled with the text colour. Every other
main button (`.wichtig`) wears the glass of the start button: the glass
ground, its fine edge and the text colour. Read off the source.

The same holds for the two main buttons that carry a class of their own and
for the switch: off it is glass, on it fills with the colour of "switched
on", and there is one switch in the house.
"""

from __future__ import annotations

import re
from pathlib import Path

TEILE = Path(__file__).resolve().parent.parent / "frontend/src/teile"
# The files whose main button is a rule of their own. The foot buttons of the
# settings, the server mask and the provider mask are the house button of
# the global stylesheet (below).
DATEIEN = [
    "Modellkarte.svelte", "Modelldetail.svelte", "Modellserver.svelte",
    "Skillmaske.svelte", "Frage.svelte", "Protokollfenster.svelte",
]
GLOBAL = TEILE.parent / "stil" / "global.css"
HOUSE_BUTTON_FILES = [
    "SystemPrompt.svelte", "MCPMaske.svelte", "Anbietermaske.svelte",
    "Auftragfenster.svelte", "AuftragStarten.svelte", "Erststart.svelte",
]


def _style(name: str) -> str:
    return (TEILE / name).read_text(encoding="utf-8").split("<style>", 1)[1]


def _rules(css: str, selector_re: str) -> list[str]:
    """The bodies of every rule whose selector list matches the pattern."""
    return [m.group(2) for m in re.finditer(r"\n  ([^{\n]+)\{([^}]*)\}", css) if re.search(selector_re, m.group(1).strip())]


def test_jeder_hauptknopf_ist_knopfglas():
    for name in DATEIEN:
        css = (TEILE / name).read_text(encoding="utf-8").split("<style>", 1)[1]
        rules = _rules(css, r"\.wichtig(?![-\w])")
        assert rules, name
        for body in rules:
            assert "background: var(--text)" not in body, (name, body)
        ground = [b for b in rules if "background: var(--glass-button)" in b]
        assert ground, name
        assert any("var(--glass-button-edge)" in b for b in ground), name
        assert any("color: var(--text)" in b for b in ground), name


def _global_rule(selector: str) -> str:
    """The declarations of the one global rule with exactly this selector."""
    css = GLOBAL.read_text(encoding="utf-8")
    opener = f"\n{selector} {{"
    assert css.count(opener) == 1, selector
    return css.split(opener, 1)[1].split("}", 1)[0]


def test_the_house_button_is_button_glass_in_both_forms():
    quiet = _global_rule(".button")
    assert "background: var(--glass-button)" in quiet
    assert "color: var(--text)" in quiet
    # No border: the edge is a ring ON the edge, so it adds no height.
    assert "border: none" in quiet
    assert "box-shadow: inset 0 0 0 1px var(--feldstrich)" in quiet
    # The whole face in one line: weight, size and family, nothing inherited.
    assert "font: 400 13px var(--schrift)" in quiet
    main = _global_rule(".button.primary")
    assert "box-shadow: inset 0 0 0 1px var(--glass-button-edge)" in main
    assert "font-weight: 500" in main
    # The main form changes edge and weight only — never the ground.
    assert "background" not in main and "padding" not in main and "font-size" not in main
    assert "background: var(--glass-hover)" in _global_rule(".button:hover:not(:disabled)")
    assert "opacity: 0.5" in _global_rule(".button:disabled")


def test_the_six_masks_use_the_house_button_and_keep_no_copy():
    for name in HOUSE_BUTTON_FILES:
        source = (TEILE / name).read_text(encoding="utf-8")
        markup, css = source.split("<style>", 1)
        assert re.search(r'class="button(?: primary)?"', markup), name
        assert not re.search(r'class="knopf[ "]', markup), name
        # No copy of the button is left: no ground, no size, no edge of its own.
        for body in _rules(css, r"\.button(?![-\w])"):
            for word in ("background", "padding", "font", "box-shadow", "border"):
                assert word not in body, (name, body)
        assert not _rules(css, r"\.knopf(?![-\w])"), name
        assert not _rules(css, r"\.wichtig(?![-\w])"), name
        assert "background: var(--text)" not in css, name
    # Each of the six shows a main button except the job-start form, whose
    # own two are the quiet ways to what is missing.
    for name in HOUSE_BUTTON_FILES:
        markup = (TEILE / name).read_text(encoding="utf-8").split("<style>", 1)[0]
        assert ('class="button primary"' in markup) == (name != "AuftragStarten.svelte"), name


def test_senden_bleibt_gefuellt():
    """Silence probe: the one filled button of the house keeps its ground."""
    css = (TEILE / "Eingabeleiste.svelte").read_text(encoding="utf-8").split("<style>", 1)[1]
    # The send button is the `.aktion` rule of the bar.
    assert re.search(r"\n  \.aktion[^{]*\{[^}]*background: var\(--text\)", css)


WINDOW_BUTTONS = [("Arbeitsordner.svelte", r"\.knopf\.stark"), ("Layoutmodus.svelte", r"\.knopf\.voll")]


def test_the_main_buttons_with_a_class_of_their_own_are_button_glass():
    for name, selector in WINDOW_BUTTONS:
        css = _style(name)
        rules = _rules(css, selector + r"(?![-\w])")
        assert rules, name
        # No button rule of the file fills with the text colour any more.
        for body in _rules(css, r"\.knopf(?![-\w])"):
            assert "background: var(--text)" not in body, (name, body)
        ground = [b for b in rules if "background: var(--glass-button)" in b]
        assert ground, name
        assert any("var(--glass-button-edge)" in b for b in ground), name
        assert any("color: var(--text)" in b for b in ground), name
        # Under the pointer the glass darkens a little; it does not fade.
        hover = _rules(css, selector + r":hover")
        assert hover and "color-mix(in srgb, var(--text) 6%, var(--glass-button))" in hover[0], name
        assert "opacity" not in hover[0], name


def test_the_quiet_buttons_beside_them_are_as_they_were():
    """Silence probe: the order of the row is told by the main button alone."""
    cancel = _rules(_style("Arbeitsordner.svelte"), r"^\.knopf$")
    assert cancel and "background: none" in cancel[0] and "var(--linie-stark)" in cancel[0]
    quiet = _rules(_style("Layoutmodus.svelte"), r"^\.knopf\.leise$")
    assert quiet and "background: none" in quiet[0]
    # A main button that cannot be pressed yet stays dimmed.
    locked = _rules(_style("Arbeitsordner.svelte"), r"^\.knopf\.stark:disabled$")
    assert locked and "opacity: 0.4" in locked[0]


def test_the_switch_is_glass_when_off_and_filled_when_on():
    css = _style("Schalter.svelte")
    assert "background: var(--text)" not in css
    off = _rules(css, r"^\.schalter$")
    assert off and "background: var(--glass-button)" in off[0]
    assert "inset 0 0 0 1px var(--glass-button-edge)" in off[0]
    # On: the colour of "switched on", full, with no edge around it.
    on = _rules(css, r"^\.schalter\[aria-checked='true'\]$")
    assert on and "background: var(--blau)" in on[0] and "box-shadow: none" in on[0]
    # Taking something away keeps its red.
    taking = _rules(css, r"^\.schalter\.eingriff\[aria-checked='true'\]$")
    assert taking and "background: var(--rot)" in taking[0]
    # The knob: quiet on the glass; on the colour the opaque ground of the
    # look, never the raised ground a menu page turns into glass. It travels.
    knob_off = _rules(css, r"^\.schalter i$")
    assert knob_off and "background: var(--text-still)" in knob_off[0]
    knob_on = _rules(css, r"^\.schalter\[aria-checked='true'\] i$")
    assert knob_on and "background: var(--bg)" in knob_on[0] and "translateX(14px)" in knob_on[0]
    assert "var(--bg-hoch)" not in css


def test_the_server_gallery_draws_no_switch_of_its_own():
    """One switch, one way: the menu of a server card uses the house switch,
    so its colours cannot drift apart from every other switch again."""
    source = (TEILE / "Verbindungen.svelte").read_text(encoding="utf-8")
    assert "import Schalter from './Schalter.svelte'" in source
    assert source.count("<Schalter") == 1, "the menu of a server card carries one switch"
    use = source.split("<Schalter", 1)[1].split("/>", 1)[0]
    assert "an={k.eintrag.enabled}" in use
    assert "beschriftung={t('verbindungen.aktiv')}" in use
    assert "onschalten={() => kippen(k.eintrag)}" in use
    assert 'class="schalter"' not in source and "aria-pressed" not in source
    assert ".schalter" not in source.split("<style>", 1)[1]

