"""The hourglass of a queued message stands in its full state colour.

A queued bubble is dimmed to say "typed, not yet said". An opacity on the
whole bubble used to take the hourglass down with it (0.6, and 0.8 on the
hourglass itself): on a light ground the yellow of "waiting" and the red of
"held" were hard to tell apart and under 3:1. The dimming now sits on the
parts — the ground by its alpha channel, the word and the text by their own
opacity — and the hourglass carries `--gelb` or `--rot` as they are.
"""

from __future__ import annotations

import re
from pathlib import Path

QUELLE = (
    Path(__file__).resolve().parent.parent
    / "frontend" / "src" / "teile" / "Warteblasen.svelte"
)


def _regeln() -> dict[str, str]:
    """Selector → declarations of the component's own style block, with
    comments removed. A rule with a selector list counts for each of them."""
    text = QUELLE.read_text(encoding="utf-8")
    stil = text.split("<style>", 1)[1].split("</style>", 1)[0]
    stil = re.sub(r"/\*.*?\*/", "", stil, flags=re.DOTALL)
    regeln: dict[str, str] = {}
    for auswahl, inhalt in re.findall(r"([^{}]+)\{([^{}]*)\}", stil):
        for einzeln in auswahl.split(","):
            schluessel = " ".join(einzeln.split())
            regeln[schluessel] = regeln.get(schluessel, "") + inhalt
    return regeln


def _opacity(inhalt: str) -> float | None:
    treffer = re.search(r"(?<![-\w])opacity\s*:\s*([0-9.]+)", inhalt)
    return float(treffer.group(1)) if treffer else None


def test_neither_the_hourglass_nor_the_bubble_carries_an_opacity():
    regeln = _regeln()
    assert _opacity(regeln[".sanduhr"]) is None
    assert _opacity(regeln[".wartet"]) is None
    assert _opacity(regeln[".wartet.haelt .sanduhr"]) is None


def test_the_hourglass_carries_the_state_colour_as_it_is():
    regeln = _regeln()
    assert "color: var(--gelb)" in regeln[".sanduhr"]
    assert "color: var(--rot)" in regeln[".wartet.haelt .sanduhr"]


def test_the_ground_is_dimmed_by_its_alpha_channel():
    boden = _regeln()[".wartet"]
    assert re.search(r"background:\s*color-mix\(\s*in srgb,[^;]*60%,\s*transparent\s*\)", boden)


def test_the_word_the_text_and_the_buttons_stay_dimmed_as_before():
    """Silence probe: what was dimmed to 0.6 (and 0.75 of that for the
    explanation and the attachment) is dimmed by the same amount."""
    regeln = _regeln()
    for auswahl in (".marke", ".text", ".weiter", ".weg"):
        assert _opacity(regeln[auswahl]) == 0.6, auswahl
    for auswahl in (".erklaerung", ".anhang"):
        assert _opacity(regeln[auswahl]) == round(0.6 * 0.75, 2), auswahl
