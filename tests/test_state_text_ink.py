"""A state said in words stands in the text form of its colour.

The four state colours exist twice (`global.css`): the form for shapes — dots,
ticks, rings, a wash behind text — and the darker, in the dark looks lighter,
form for type (`--gruen-text`, `--gelb-text`, `--blau-text`, `--rot-text`).
Red type in the shape form reads pink on the dark ground and the green and the
yellow stay under 4.5:1 on the light ones. So every state word and every
sentence of a failure wears the text form, while the signs, dots, ticks and
washes next to them keep the colour of the shape.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "frontend" / "src"
TEILE = SRC / "teile"
STIL = SRC / "stil" / "global.css"


def _rules(path: Path) -> list[tuple[str, str]]:
    """The (selector, body) of every rule in the style block of a component,
    one pair per selector of a list."""
    source = path.read_text(encoding="utf-8")
    style = source.split("<style>", 1)[1] if "<style>" in source else source
    style = re.sub(r"/\*.*?\*/", "", style, flags=re.S)
    pairs: list[tuple[str, str]] = []
    for head, body in re.findall(r"([^{}]+)\{([^{}]*)\}", style):
        for selector in head.split(","):
            pairs.append((re.sub(r"\s+", " ", selector).strip(), body))
    return pairs


def _declared(path: Path, selector: str, prop: str = "color") -> str:
    bodies = [body for found, body in _rules(path) if found == selector]
    assert bodies, f"{path.name} has no rule for {selector!r}"
    values = [
        match.group(1).strip()
        for body in bodies
        for match in [re.search(rf"(?:^|[;\s]){prop}\s*:\s*([^;]+)", body)]
        if match
    ]
    assert values, f"{path.name}: {selector!r} sets no {prop}"
    return values[-1]


# (file, selector) of every word or sentence that says a state, with the form
# of the colour it must wear.
WORDS = [
    (TEILE / "ServerOverview.svelte", ".state.active", "gruen-text"),
    (TEILE / "ServerOverview.svelte", ".state.failed", "rot-text"),
    (TEILE / "ServerOverview.svelte", ".state.rot", "rot-text"),
    (TEILE / "ServerOverview.svelte", ".state.gruen", "gruen-text"),
    (TEILE / "MCPMaske.svelte", ".copyrow button[data-copied='true']", "gruen-text"),
    (TEILE / "MCPMaske.svelte", ".fehlertext", "rot-text"),
    (TEILE / "MCPMaske.svelte", ".wz[data-stand='an'] .stand", "gruen-text"),
    (TEILE / "MCPMaske.svelte", ".wz[data-stand='fragt'] .stand", "gelb-text"),
    (TEILE / "MCPMaske.svelte", ".stand-zeile .wort", "gruen-text"),
    (TEILE / "SystemPrompt.svelte", ".key-state.set", "gruen-text"),
    (TEILE / "SystemPrompt.svelte", ".key-state.missing", "rot-text"),
    (SRC / "phone" / "settings" / "TextFile.svelte", ".key-state.set", "gruen-text"),
    (SRC / "phone" / "settings" / "TextFile.svelte", ".key-state.missing", "rot-text"),
    (TEILE / "Shortcuts.svelte", ".belegt", "rot-text"),
    (TEILE / "Updatezeile.svelte", ".result.running", "blau-text"),
    (TEILE / "Updatezeile.svelte", ".result.failed", "rot-text"),
    (TEILE / "Updatezeile.svelte", ".result.done", "gruen-text"),
    (TEILE / "Anmeldung.svelte", ".error", "rot-text"),
    (TEILE / "Erststart.svelte", ".sprachfehler", "rot-text"),
    (TEILE / "Startfehler.svelte", ".start-error", "rot-text"),
    (TEILE / "StudioSection.svelte", ".karte :global(.hinweis.vorsicht)", "gelb-text"),
    (SRC / "App.svelte", ".bildlauf-teilweise", "rot-text"),
    (TEILE / "Serverabschnitt.svelte", ".karte > :global(.zeile.kurz.fehlt)", "rot-text"),
    (TEILE / "ModulTerminal.svelte", ".wz-ergebnis :global(.diff-entfernt)", "rot-text"),
    (TEILE / "ModulTerminal.svelte", ".wz-ergebnis :global(.diff-hinzu)", "gruen-text"),
    (TEILE / "ModulTerminal.svelte", ".werkzeugblock.misslungen .name", "rot-text"),
    (TEILE / "ModulTerminal.svelte", ".werkzeugblock.misslungen .ausgang", "rot-text"),
    (TEILE / "ModulTerminal.svelte", ".exit-code", "rot-text"),
    (TEILE / "UpToDateMark.svelte", ".uptodate", "gruen-text"),
    (TEILE / "Bildserver.svelte", ":global(.karte) .zeile .v_fehler", "rot-text"),
    (TEILE / "Modellserver.svelte", ".start-error", "rot-text"),
    (TEILE / "Modellserver.svelte", ".pille.gruen", "gruen-text"),
    (TEILE / "BuildRows.svelte", ".da", "gruen-text"),
]

# The shapes next to the words: signs, dots, ticks, hover marks. They stay in
# the colour of the shape.
SHAPES = [
    (TEILE / "DownloadRow.svelte", ".tick", "gruen"),
    (TEILE / "BuildRows.svelte", ".haken", "gruen"),
    (TEILE / "QuestionBox.svelte", ".reason svg", "gelb"),
    (TEILE / "Meldungen.svelte", ".erfolg .zeichen", "gruen"),
    (TEILE / "Meldungen.svelte", ".warnung .zeichen", "gelb"),
    (TEILE / "Meldungen.svelte", ".fehler .zeichen", "rot"),
    (TEILE / "DocFolder.svelte", ".weg:hover", "rot"),
    (TEILE / "ModulAgenten.svelte", ".bweg:hover", "rot"),
    (TEILE / "Nachricht.svelte", ".zeichen.gruen", "gruen"),
    (TEILE / "Nachricht.svelte", ".zeichen.rot", "rot"),
    (TEILE / "ToolSigns.svelte", ".zeichen[data-zustand='gruen']", "gruen"),
    (TEILE / "ToolSigns.svelte", ".zeichen[data-zustand='blau']", "blau"),
    (TEILE / "ToolSigns.svelte", ".zeichen[data-zustand='gelb']", "gelb"),
    (TEILE / "ToolSigns.svelte", ".zeichen[data-zustand='rot']", "rot"),
    (TEILE / "Warteblasen.svelte", ".sanduhr", "gelb"),
    # The tick and the cross of a key row stand inside the word that names it.
    (TEILE / "SystemPrompt.svelte", ".key-state.set .key-sign", "gruen"),
    (TEILE / "SystemPrompt.svelte", ".key-state.missing .key-sign", "rot"),
    (SRC / "phone" / "settings" / "TextFile.svelte", ".key-state.set .key-sign", "gruen"),
    (SRC / "phone" / "settings" / "TextFile.svelte", ".key-state.missing .key-sign", "rot"),
]


@pytest.mark.parametrize(("path", "selector", "form"), WORDS, ids=lambda v: v if isinstance(v, str) else getattr(v, "name", None))
def test_a_state_word_wears_the_text_form_of_its_colour(path, selector, form):
    assert _declared(path, selector) == f"var(--{form})"


@pytest.mark.parametrize(("path", "selector", "form"), SHAPES, ids=lambda v: v if isinstance(v, str) else getattr(v, "name", None))
def test_silence_a_shape_next_to_a_word_keeps_the_colour_of_the_shape(path, selector, form):
    assert _declared(path, selector) == f"var(--{form})"


def test_silence_the_washes_and_dots_behind_the_words_keep_the_colour_of_the_shape():
    # The wash behind a failed line, behind a removed and an added line, and
    # the lamp of a running tool: all of them stay.
    assert "color-mix(in srgb, var(--rot) 12%, var(--bg))" in _declared(
        TEILE / "Erststart.svelte", ".sprachfehler", "background")
    terminal = TEILE / "ModulTerminal.svelte"
    assert "var(--rot) 12%" in _declared(terminal, ".wz-ergebnis :global(.diff-entfernt)", "background")
    assert "var(--gruen) 12%" in _declared(terminal, ".wz-ergebnis :global(.diff-hinzu)", "background")
    assert _declared(TEILE / "MCPMaske.svelte", ".stand-zeile .lampe", "background") == "var(--gruen)"
    # The rim of the green pill of the first steps stays in the colour of the shape.
    rim = _declared(TEILE / "Modellserver.svelte", ".pille.gruen", "border-color")
    assert "var(--gruen)" in rim and "-text" not in rim, rim


def test_only_the_colour_of_these_words_changed_not_their_weight_or_size():
    # A word does not become bolder or larger by getting its text form.
    assert _declared(TEILE / "ServerOverview.svelte", ".state", "font-weight") == "500"
    assert _declared(TEILE / "Shortcuts.svelte", ".belegt", "font-size") == "12.5px"
    assert _declared(TEILE / "Anmeldung.svelte", ".error", "font-size") == "12.5px"
    assert _declared(TEILE / "ModulTerminal.svelte", ".exit-code", "font-size") == "10.5px"
    assert _declared(TEILE / "UpToDateMark.svelte", ".uptodate", "font-size") == "12px"


def test_the_text_forms_exist_in_the_stylesheet_of_every_look():
    sheet = STIL.read_text(encoding="utf-8")
    for token in ("--gruen-text", "--gelb-text", "--blau-text", "--rot-text"):
        assert f"{token}:" in sheet, token
    # The dark looks lift them: the set exists more than once.
    assert sheet.count("--rot-text:") >= 3
