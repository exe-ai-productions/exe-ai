"""The switch is white and grey in every look.

Switched on, the track is the ink of the look and the knob its ground; off,
the track is the ink at a sixth of its strength and the knob the quiet ink.
No blue and no red. The contrast of the knob against its track is calculated
from `global.css` itself: each look is its base block plus the blocks that
name it, read in the order the file has them.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CSS = (ROOT / "frontend/src/stil/global.css").read_text(encoding="utf-8")
SWITCH = (ROOT / "frontend/src/teile/Schalter.svelte").read_text(encoding="utf-8")


def _declarations(block_selector: str, source: str = CSS) -> dict[str, str]:
    """The custom properties the rule opening with this selector sets."""
    start = source.index(block_selector + " {") + len(block_selector) + 2
    depth, end = 1, start
    while depth:
        depth += {"{": 1, "}": -1}.get(source[end], 0)
        end += 1
    body = re.sub(r"/\*.*?\*/", "", source[start : end - 1], flags=re.S)
    return {m.group(1): m.group(2).strip() for m in re.finditer(r"(--[\w-]+)\s*:\s*([^;]+);", body)}


def _look(*blocks: str) -> dict[str, str]:
    tokens: dict[str, str] = {}
    for block in blocks:
        tokens.update(_declarations(block))
    return tokens


def _luminance(colour: str) -> float:
    channels = [int(colour[i : i + 2], 16) / 255 for i in (1, 3, 5)]
    linear = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def _contrast(first: str, second: str) -> float:
    high, low = sorted((_luminance(first), _luminance(second)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def _looks() -> dict[str, dict[str, str]]:
    base = _declarations(":root")
    return {
        "pearl": base,
        "heaven": {**base, **_declarations(":root[data-modus='heaven']")},
        "moune": {**base, **_declarations(":root[data-modus='moune']")},
        "exe": {**base, **_declarations(":root[data-eigen='dunkel'],\n:root[data-modus='dunkel']")},
        "dark matter": {**base, **_declarations(":root[data-modus='darkmatter']")},
    }


def test_a_switched_on_knob_stands_out_of_its_track_in_every_look():
    # On: the track is the ink, the knob the ground.
    for name, look in _looks().items():
        assert _contrast(look["--bg"], look["--text"]) >= 4.5, name


def test_a_switched_off_knob_stands_out_of_the_ground_in_every_look():
    # Off: the track is a sixth of the ink on the ground, the knob the quiet ink.
    for name, look in _looks().items():
        assert _contrast(look["--text-leise"], look["--bg"]) >= 3, name


def test_the_switch_is_drawn_in_the_ink_of_the_look_and_never_in_blue_or_red():
    assert "background: color-mix(in srgb, var(--text) 16%, transparent);" in SWITCH
    assert "background: var(--text-leise);" in SWITCH
    # On: the ink as the track, the ground as the knob.
    assert ".schalter[aria-checked='true'] {\n    background: var(--text);" in SWITCH
    assert "background: var(--bg);" in SWITCH
    for forbidden in ("var(--blau)", "var(--rot)", "knauf-an"):
        assert forbidden not in SWITCH, forbidden


def test_no_look_carries_the_old_knob_token_any_more():
    assert "--knauf-an" not in CSS
