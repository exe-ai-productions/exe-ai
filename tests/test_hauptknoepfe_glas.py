"""The main buttons of the menu pages, masks and windows are button glass.

Only Send in the input bar stays filled with the text colour. Every other
main button (`.wichtig`) wears the glass of the start button: the glass
ground, its fine edge and the text colour. Read off the source.

The foot of the folder window and of the layout window is the house button
too, and the same holds for the switch: off it is glass, on it fills with
the colour of "switched on", and there is one switch in the house.
"""

from __future__ import annotations

import re
from pathlib import Path

TEILE = Path(__file__).resolve().parent.parent / "frontend/src/teile"
# The files whose main button is a rule of their own. The foot buttons of the
# settings, the server mask and the provider mask are the house button of
# the global stylesheet (below); the foot of the settings' text pages is two
# signs (see `test_the_foot_of_the_text_pages_is_two_signs`); the foot of the
# skill form is two signs as well (tests/test_skillseite.py).
DATEIEN = [
    "Modellserver.svelte", "Frage.svelte", "Protokollfenster.svelte",
]
# The cards and rows of the catalogue have no text button any more: their main
# button is a sign button (download, cancel), button glass as well; the one
# component that draws them is the download row.
SIGN_BUTTONS = ["DownloadRow.svelte"]
GLOBAL = TEILE.parent / "stil" / "global.css"
HOUSE_BUTTON_FILES = [
    "MCPMaske.svelte", "Anbietermaske.svelte",
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


def test_the_sign_button_of_the_catalogue_is_button_glass():
    for name in SIGN_BUTTONS:
        css = (TEILE / name).read_text(encoding="utf-8").split("<style>", 1)[1]
        rules = _rules(css, r"\.sign-button(?![-\w:])")
        assert rules, name
        for body in rules:
            assert "background: var(--text)" not in body, (name, body)
        assert any("background: var(--glass-button)" in b for b in rules), name
        assert any("var(--glass-button-edge)" in b for b in rules), name
        assert any("color: var(--text)" in b for b in rules), name


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
    assert "font: 400 13px/1.19 var(--schrift)" in quiet
    main = _global_rule(".button.primary")
    assert "box-shadow: inset 0 0 0 1px var(--glass-button-edge)" in main
    assert "font-weight: 500" in main
    # The main form changes edge and weight only — never the ground.
    assert "background" not in main and "padding" not in main and "font-size" not in main
    assert "background: var(--glass-hover)" in _global_rule(".button:hover:not(:disabled)")
    assert "opacity: 0.5" in _global_rule(".button:disabled")


def test_the_masks_use_the_house_button_and_keep_no_copy():
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
    # Each of them shows a main button except the job-start form, whose
    # own two are the quiet ways to what is missing.
    for name in HOUSE_BUTTON_FILES:
        markup = (TEILE / name).read_text(encoding="utf-8").split("<style>", 1)[0]
        assert ('class="button primary"' in markup) == (name != "AuftragStarten.svelte"), name


def test_the_foot_of_the_text_pages_is_two_signs():
    """On the desktop the foot's Cancel and Save are a cross and a disk with
    their word as tooltip and label; no word button is left there. (The phone
    keeps its own word buttons.)"""
    source = (TEILE / "SystemPrompt.svelte").read_text(encoding="utf-8")
    markup, css = source.split("<style>", 1)
    foot = markup.split('<div class="rechts">', 1)[1].split("</div>", 1)[0]
    assert "{#if bearbeitet}" in foot
    for word, sign in (("abbrechen", "kreuz"), ("sichern", "save")):
        assert f"aria-label={{t('app.{word}')}} title={{t('app.{word}')}}" in foot
        assert f'<Hauszeichen zeichen="{sign}"' in foot
    assert not re.search(r'class="button(?: primary)?"', markup)
    assert not _rules(css, r"\.button(?![-\w])")


def test_senden_bleibt_gefuellt():
    """Silence probe: the one filled button of the house keeps its ground."""
    css = (TEILE / "Eingabeleiste.svelte").read_text(encoding="utf-8").split("<style>", 1)[1]
    # The send button is the `.aktion` rule of the bar.
    assert re.search(r"\n  \.aktion[^{]*\{[^}]*background: var\(--text\)", css)


WINDOWS_WITH_FOOT = ["Arbeitsordner.svelte", "Layoutmodus.svelte"]


def test_the_foot_of_the_two_windows_is_the_house_button_in_both_forms():
    """Cancel is the quiet house button, the main button the primary one; no
    copy of either is left in the file."""
    for name in WINDOWS_WITH_FOOT:
        markup, css = (TEILE / name).read_text(encoding="utf-8").split("<style>", 1)
        assert re.search(r"""<button class="button"[^\n]*>\s*\{t\('app\.abbrechen'\)\}""", markup), name
        assert 'class="button primary"' in markup, name
        assert not re.search(r'class="knopf (?:stark|voll)"', markup), name
        # The only rule on the house button that a window keeps is the quiet
        # word's, which takes the ground away.
        selectors = {m.group(1).strip() for m in re.finditer(r"\n  ([^{\n]+)\{", css) if ".button" in m.group(1)}
        assert selectors <= {".button.leise"}, (name, selectors)
        assert not _rules(css, r"\.knopf\.(?:stark|voll)"), name


def test_the_quiet_words_beside_them_are_as_they_were():
    """Silence: "Default" stays without ground and edge, and the buttons in
    the rows of the folder window keep their own outlined face."""
    quiet = _rules(_style("Layoutmodus.svelte"), r"^\.button\.leise$")
    assert quiet and "background: none" in quiet[0] and "box-shadow: none" in quiet[0]
    rows = _rules(_style("Arbeitsordner.svelte"), r"^\.knopf$")
    assert rows and "background: none" in rows[0] and "var(--linie-stark)" in rows[0]


def test_the_switch_is_a_grey_track_when_off_and_the_ink_when_on():
    """White and grey in every look: off, the ink at a sixth of its strength;
    on, the ink itself — no blue, no red, no edge."""
    css = _style("Schalter.svelte")
    off = _rules(css, r"^\.schalter$")
    assert off and "background: color-mix(in srgb, var(--text) 16%, transparent)" in off[0]
    on = _rules(css, r"^\.schalter\[aria-checked='true'\]$")
    assert on and "background: var(--text)" in on[0]
    for forbidden in ("var(--blau)", "var(--rot)", "var(--glass-button", "eingriff"):
        assert forbidden not in css, forbidden
    # The knob: the quiet ink on the grey track, the ground of the look on the
    # ink. It travels.
    knob_off = _rules(css, r"^\.schalter i$")
    assert knob_off and "background: var(--text-leise)" in knob_off[0]
    knob_on = _rules(css, r"^\.schalter\[aria-checked='true'\] i$")
    assert knob_on and "background: var(--bg)" in knob_on[0]
    assert "translateX(14px)" in knob_on[0]
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

