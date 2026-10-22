"""Every surface on a menu page is glass.

The page itself is glass (Seitenrahmen.svelte), and what stands on it
carries the glass tokens of the look instead of the flat raised grounds:
`--glass-card` for a card, `--glass-button` for a button, a pill or a field
(a field with the house's field outline), `--glass-dropdown` for a layer
that floats. The selection field and the dropdown choice are glass by
default, with no switch left to turn it off. Read off the source.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

FRONTEND = Path(__file__).resolve().parent.parent / "frontend/src"
TEILE = FRONTEND / "teile"

# The files of the menu pages, their masks, fields and floating windows.
DATEIEN = [
    "Auswahlfeld.svelte", "Klappwahl.svelte", "SystemPrompt.svelte", "Modellkarte.svelte",
    "Modelldetail.svelte", "Modellserver.svelte", "Katalog.svelte", "Agentenmaske.svelte",
    "Anbietermaske.svelte", "MCPMaske.svelte", "Skillmaske.svelte", "Serverabschnitt.svelte",
    "Werkzeuge.svelte", "Verbindungen.svelte", "Shortcuts.svelte", "Meldewahl.svelte",
    "SettingsAgents.svelte", "Zahlenfeld.svelte", "Standpille.svelte", "Fenster.svelte",
    "Frage.svelte", "Protokollfenster.svelte", "Meldungen.svelte",
]
FLACH = ("var(--bg-erhoben)", "var(--bg-hoch)")


def _style(name: str) -> str:
    return (TEILE / name).read_text(encoding="utf-8").split("<style>", 1)[1]


def _rule(name: str, selector: str) -> str:
    """The declarations of every rule that opens with this selector, joined —
    a window may split its rule in two."""
    css = _style(name)
    opener = f"\n  {selector} {{"
    assert opener in css, (name, selector)
    return "\n".join(part.split("}", 1)[0] for part in css.split(opener)[1:])


@pytest.mark.parametrize("name", DATEIEN)
def test_no_flat_surface_is_left(name):
    css = _style(name)
    for token in FLACH:
        assert token not in css, (name, token)


def test_the_selection_field_and_the_dropdown_choice_are_glass_without_a_switch():
    for name in ("Auswahlfeld.svelte", "Klappwahl.svelte"):
        quelle = (TEILE / name).read_text(encoding="utf-8")
        script = quelle.split("</script>", 1)[0]
        assert not re.search(r"\bglass\s*=", script), name
        assert "class:glass" not in quelle, name
        css = quelle.split("<style>", 1)[1]
        assert ".glass" not in css, name
        assert "var(--glass-button)" in css, name
        assert "var(--glass-dropdown)" in css, name
    # The field carries the house's field outline, its list floats in dense glass.
    feld = _rule("Auswahlfeld.svelte", ".feld")
    assert "background: var(--glass-button)" in feld
    assert "border: 1px solid var(--feldstrich)" in feld
    klapp = _rule("Auswahlfeld.svelte", ".klapp")
    assert "var(--glass-dropdown)" in klapp
    assert "blur(16px)" in klapp
    liste = _rule("Klappwahl.svelte", ".liste")
    assert "var(--glass-dropdown)" in liste
    assert "blur(16px)" in liste


def test_no_caller_passes_the_switch():
    for pfad in FRONTEND.rglob("*.svelte"):
        quelle = pfad.read_text(encoding="utf-8")
        for tag in ("Auswahlfeld", "Klappwahl"):
            for treffer in re.finditer(rf"<{tag}\b[^>]*>", quelle, re.S):
                assert not re.search(r"\bglass\b", treffer.group(0)), (pfad.name, treffer.group(0)[:80])


def test_floating_layers_carry_dense_glass():
    for name, selector in (
        ("Fenster.svelte", ".popup"), ("Frage.svelte", ".popup"),
        ("Protokollfenster.svelte", ".popup"), ("Meldungen.svelte", ".meldung"),
    ):
        block = _rule(name, selector)
        assert "var(--glass-dropdown)" in block, name
        # The window keeps its blur on a layer of its own (`.popup::before`),
        # so a fixed-positioned list inside it keeps the viewport as its frame.
        assert "blur(16px)" in _style(name), name


def test_fixed_surfaces_stay():
    """Silence probe: the first-start window keeps its solid ground — a
    backdrop filter there broke its fixed list — and the input bar keeps
    the ground of its field."""
    fenster = _rule("Erststart.svelte", ".fenster")
    assert "var(--bg-erhoben)" in fenster
    assert "--kachel-eingabe" in _style("Eingabeleiste.svelte")


# The fields and quiet buttons on the light looks' near-white ground: they
# stand on `--bg-hoch` and wear the field outline as an inner ring, so the
# ring adds no height and the fill stays.
FIELDS_WITH_OUTLINE = [
    ("Ankreuzliste.svelte", ".suche"), ("BildGeraete.svelte", ".eingabe"),
    ("Bildmodellwerte.svelte", ".eingabe"),
    ("Parametertafel.svelte", ".zahl"), ("Modellwahl.svelte", ".search"),
    ("Startordnerpillen.svelte", ".pfadfeld"), ("Updatekarte.svelte", ".choice.quiet"),
    ("FolderChip.svelte", ".small"),
]


@pytest.mark.parametrize(("name", "selector"), FIELDS_WITH_OUTLINE)
def test_a_field_or_quiet_button_on_the_raised_ground_wears_the_field_outline(name, selector):
    rule = _rule(name, selector)
    assert "var(--bg-hoch)" in rule, (name, selector)
    assert "box-shadow: inset 0 0 0 1px var(--feldstrich)" in rule, (name, selector)


def test_the_outline_is_defined_by_every_look_and_the_icon_button_stays_without_it():
    """Silence: the value of the outline is the look's own (six definitions in
    the global stylesheet), and the icon button of the log head carries none."""
    css = (FRONTEND / "stil" / "global.css").read_text(encoding="utf-8")
    assert len(re.findall(r"^\s*--feldstrich:", css, re.M)) >= 6
    assert "--feldstrich" not in _rule("Serverlogkopf.svelte", ".aus")
