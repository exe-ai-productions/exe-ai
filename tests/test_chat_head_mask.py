"""Text scrolled up behind the chat's name is not there at all.

The chat's head has no ground of its own: the history's mask melts the text
out over it. The mask used to turn opaque only at the head's lower edge, so
at the height of the name the text was still half there and ran through its
letters. Now the text is fully transparent over the name's height and melts
in only below it. The fade above the input field is not touched.

The rule lives in `frontend/src/App.svelte`; the test reads it as it stands.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "frontend" / "src" / "App.svelte"

# The 44 px head centres a 13 px name whose line is 16 px high there
# (measured in Chrome: the `.chatname` box runs from 14 to 30 px of the head).
HEAD_HEIGHT = 44
NAME_BOTTOM = 30


def _rule(selector: str) -> str:
    source = APP.read_text(encoding="utf-8")
    hit = re.search(r"\n  " + re.escape(selector) + r"\s*\{([^}]*)\}", source)
    assert hit, f"no rule for {selector}"
    return hit.group(1)


def _px(rule: str, name: str) -> float:
    hit = re.search(re.escape(name) + r":\s*([0-9.]+)px;", rule)
    assert hit, f"{name} is not set in {rule!r}"
    return float(hit.group(1))


def test_the_head_is_44_px_and_its_name_is_13_px():
    """The numbers the mask is cut to: if the head changes, this stops first."""
    head = _rule(".chatkopf")
    assert f"height: {HEAD_HEIGHT}px;" in head
    assert "font-size: 13px;" in _rule(".chatname")


def test_over_the_names_height_the_text_is_fully_transparent_and_melts_in_below():
    under = _rule(".verlauf.under-head")
    clear = _px(under, "--head-clear")
    fade = _px(under, "--head-fade")
    assert clear >= NAME_BOTTOM, "the text still shows through the name"
    assert clear < fade, "the text must melt in below the name, not jump in"
    assert fade <= 2 * HEAD_HEIGHT, "the melt-in must stay near the head"


def test_the_mask_runs_transparent_to_the_clear_edge_then_to_the_fade_edge():
    verlauf = _rule(".verlauf")
    for name in ("-webkit-mask-image", "mask-image"):
        hit = re.search(re.escape(name) + r":\s*linear-gradient\((.*?)\);", verlauf, re.S)
        assert hit, name
        stops = [stop.strip() for stop in re.split(r",\s*(?![^()]*\))", hit.group(1))]
        assert stops == [
            "to bottom",
            "transparent",
            "transparent var(--head-clear)",
            "#000 var(--head-fade)",
            "#000 calc(100% - var(--auslauf))",
            "transparent",
        ], stops


def test_without_a_head_nothing_is_cleared_and_the_fade_above_the_input_stays():
    """The silence check: a chat without the head layer (`under-head` not set)
    has both edges at 0, and the lower fade is the 64 px it always was."""
    verlauf = _rule(".verlauf")
    assert "--head-clear: 0px;" in verlauf
    assert "--head-fade: 0px;" in verlauf
    assert "--auslauf: 64px;" in verlauf
