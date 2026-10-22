"""Blue shows a state, nothing else.

A link, the tick beside the chosen model, the chosen row of a phone sheet,
the dot of a chip that holds a value, the "GGUF" tag, an agent's name in a
report head, the bar in the context card and the focus ring of a control used
to be blue although nothing runs there. They wear the colour of the text now;
blue stays where something is on, running or loading (and at the bolt of a fast
model).

The rules are read from the sources of the components: a rule that names one
of these selectors may not carry ``--blau`` or ``--blau-text`` any more.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

FRONTEND = Path(__file__).resolve().parent.parent / "frontend" / "src"

_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)
_RULE = re.compile(r"([^{}]+)\{([^{}]*)\}")
_BLUE = re.compile(r"--blau(?:-text)?\b")

# (file, selector) — the places that are no state.
NO_STATE = [
    ("teile/Nachricht.svelte", ".antwort :global(a)"),
    ("teile/Nachricht.svelte", ".eigenlink"),
    ("teile/ModulVorschau.svelte", ".dokument :global(a)"),
    ("teile/Modellwahl.svelte", ".check"),
    ("phone/studio/Sheets.svelte", ".choice.chosen"),
    ("phone/parts/Pick.svelte", ".choice.chosen"),
    ("phone/studio/Compose.svelte", ".dot"),
    ("teile/ImageServerFiles.svelte", ".chip.gguf"),
    ("teile/Bildschau.svelte", ".agent"),
    ("teile/ContextRing.svelte", ".bar i"),
    ("stil/global.css", ":focus-visible"),
]

# The places that show a state and keep their blue.
STATE = [
    ("teile/Modellwahl.svelte", ".lamp.speed.on"),
    ("teile/Leuchtpunkt.svelte", ".scheibe[data-farbe='blau']"),
]


def _bodies(file: str, selector: str) -> list[str]:
    source = _COMMENT.sub("", (FRONTEND / file).read_text(encoding="utf-8"))
    found = []
    for head, body in _RULE.findall(source):
        if selector in [part.strip() for part in head.split(",")]:
            found.append(body)
    return found


@pytest.mark.parametrize(("file", "selector"), NO_STATE)
def test_a_place_without_a_state_does_not_wear_blue(file: str, selector: str):
    bodies = _bodies(file, selector)
    assert bodies, f"{selector} not found in {file}"
    for body in bodies:
        assert not _BLUE.search(body), f"{selector} in {file} still wears blue: {body.strip()}"


@pytest.mark.parametrize(("file", "selector"), NO_STATE)
def test_a_place_without_a_state_wears_the_text_colour(file: str, selector: str):
    assert any("var(--text)" in body for body in _bodies(file, selector))


@pytest.mark.parametrize(("file", "selector"), STATE)
def test_silence_a_place_with_a_state_keeps_its_blue(file: str, selector: str):
    bodies = _bodies(file, selector)
    assert bodies, f"{selector} not found in {file}"
    assert any(_BLUE.search(body) for body in bodies)


def test_the_selector_scan_sees_a_blue_rule():
    """The scan itself is tested: a rule with blue in it is found as blue."""
    source = ".x :global(a) { color: var(--blau); }"
    heads = _RULE.findall(source)
    assert heads and _BLUE.search(heads[0][1])


def test_silence_a_control_with_a_focus_ring_of_its_own_keeps_it():
    """Only the general ring changed colour: a component's own ring stays."""
    bodies = _bodies("teile/ContextRing.svelte", ".ring:focus-visible")
    assert bodies and all("var(--linie-stark)" in body for body in bodies)
