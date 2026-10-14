"""The knob of a switched-on switch in the light looks.

On the blue track the knob wore the ground of the look; in Pearl and Moune
that ground is nearly as light as the track's blue is dark in the middle, and
the knob measured under 3 : 1 against it. The knob is white in Pearl, Moune
and Heaven; the dark looks keep the ground.

The contrast is calculated from `global.css` itself: each look is its base
block plus the blocks that name it, read in the order the file has them.
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


def _knob(look: dict[str, str]) -> str:
    """What `var(--knauf-an, var(--bg))` resolves to in this look."""
    value = look.get("--knauf-an", "initial")
    return look["--bg"] if value == "initial" else value


# The auto-dark block sits inside a media query; it is the dark look's base
# when the system is dark, and the later blocks name their own look over it.
AUTO_DARK = _declarations(":root:not([data-modus='hell'], [data-eigen='hell'])", CSS.split("@media (prefers-color-scheme: dark) {", 1)[1])


def test_the_knob_is_white_against_the_blue_track_in_pearl_moune_and_heaven():
    base = _declarations(":root")
    pearl = {**base}
    heaven = {**base, **_declarations(":root[data-modus='heaven']")}
    moune = {**base, **_declarations(":root[data-modus='moune']")}
    was = {"pearl": 2.99, "moune": 2.76, "heaven": 4.57}
    for name, look, wanted in (("pearl", pearl, 4.3), ("moune", moune, 3.5), ("heaven", heaven, 5.3)):
        assert _knob(look) == "#ffffff", name
        assert round(_contrast(_knob(look), look["--blau"]), 1) == wanted, name
        # What it was: the ground of the look, under 3 : 1 in two of them.
        assert round(_contrast(look["--bg"], look["--blau"]), 2) == was[name], name


def test_the_light_looks_keep_the_knob_white_where_the_system_is_dark():
    """The auto-dark block comes before Heaven and Moune; their own value has
    to stand against it, or the knob would fall back to the ground there."""
    base = {**_declarations(":root"), **AUTO_DARK}
    assert _knob(base) != "#ffffff"
    for modus in ("heaven", "moune"):
        look = {**base, **_declarations(f":root[data-modus='{modus}']")}
        assert _knob(look) == "#ffffff", modus


def test_silence_exe_and_dark_matter_keep_the_ground_as_the_knob():
    base = _declarations(":root")
    exe = {**base, **_declarations(":root[data-eigen='dunkel'],\n:root[data-modus='dunkel']")}
    dark_matter = {**base, **_declarations(":root[data-modus='darkmatter']")}
    for name, look in (("exe", exe), ("dark matter", dark_matter)):
        assert _knob(look) == look["--bg"], name
    assert round(_contrast(_knob(exe), exe["--blau"]), 2) == 5.56
    assert round(_contrast(_knob(dark_matter), dark_matter["--blau"]), 2) == 9.8


def test_the_switch_reads_the_token_with_the_ground_as_the_fallback():
    assert "background: var(--knauf-an, var(--bg));" in SWITCH
    # The track, the knob off and the red of taking away are as they were.
    assert "background: var(--blau);" in SWITCH and "background: var(--rot);" in SWITCH
    assert "background: var(--text-still);" in SWITCH
