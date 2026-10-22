"""The house signs for playing and stopping a recording.

Both come from the house catalogue unchanged: a triangle and a rounded square
on the 24 grid, drawn with a stroke of 2.2. They are new to `Hauszeichen`, and
the signs that stood there before do not change.
"""

from __future__ import annotations

import re
from pathlib import Path

SOURCE = (Path(__file__).resolve().parent.parent / "frontend/src/teile/Hauszeichen.svelte").read_text(encoding="utf-8")


def _branch(name: str) -> str:
    start = SOURCE.index(f"{{:else if zeichen === '{name}'}}")
    return SOURCE[start:SOURCE.index("{:else", start + 10)]


def test_play_is_the_triangle_of_the_catalogue():
    assert '<path d="M8.5 6 L18.5 12 L8.5 18 Z" stroke-width="2.2" />' in _branch("play")


def test_stop_is_the_rounded_square_of_the_catalogue():
    assert '<rect x="6.5" y="6.5" width="11" height="11" rx="2" stroke-width="2.2" />' in _branch("stop")


def test_both_are_named_in_the_list_of_signs_at_the_head_of_the_file():
    head = SOURCE[: SOURCE.index("</script>")]
    assert re.search(r"\bplay\b.*\bstop\b", head)


def test_silence_the_bin_and_the_microphone_stay_as_they_were():
    assert '<path d="M3 6h18" />' in _branch("trash")
    assert "microphone" in SOURCE and "{:else if zeichen === 'microphone'}" in SOURCE
