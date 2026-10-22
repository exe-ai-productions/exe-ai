"""The waiting bubble is the sent bubble, dimmed — and nothing else.

A queued message stands as the bubble it will become: it is the sent message's
own bubble, drawn from the same shape, so the width, place, padding, corners,
type and parts are the sent one's. The state stands under it, in the row where "Copy" stands once the
message is sent: the hourglass in its full state colour, the word, the ✕. The
sentence that says what the bubble is stands only as the hint of the word.
That makes the waiting bubble as high as the sent one, so nothing jumps when
the message goes; only the dimming fills in.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

FRONTEND = Path(__file__).resolve().parent.parent / "frontend"
SOURCE = FRONTEND / "src" / "teile" / "Warteblasen.svelte"
BUBBLE = FRONTEND / "src" / "teile" / "Nachricht.svelte"


def _rules(file: Path) -> dict[str, str]:
    """Selector → declarations of the component's own style block, with
    comments removed. A rule with a selector list counts for each of them."""
    text = file.read_text(encoding="utf-8")
    style = text.split("<style>", 1)[1].split("</style>", 1)[0]
    style = re.sub(r"/\*.*?\*/", "", style, flags=re.DOTALL)
    rules: dict[str, str] = {}
    for selector, content in re.findall(r"([^{}]+)\{([^{}]*)\}", style):
        for single in selector.split(","):
            key = " ".join(single.split())
            rules[key] = rules.get(key, "") + content
    return rules


def _declarations(content: str) -> dict[str, str]:
    return {
        name.strip(): " ".join(value.split())
        for name, value in re.findall(r"([\w-]+)\s*:\s*([^;]+);", content)
    }


def _opacity(content: str) -> float | None:
    found = re.search(r"(?<![-\w])opacity\s*:\s*([0-9.]+)", content)
    return float(found.group(1)) if found else None


def _markup(file: Path) -> str:
    return file.read_text(encoding="utf-8").split("</script>", 1)[1].split("<style>", 1)[0]


def test_neither_the_hourglass_nor_the_row_carries_an_opacity():
    """The dimming is on the bubble, as a whole, in the sent bubble's own file;
    the row under it is no part of the bubble and is not dimmed with it."""
    rules = _rules(SOURCE)
    assert _opacity(rules[".sanduhr"]) is None
    assert _opacity(rules[".zeile"]) is None


def test_the_hourglass_carries_the_state_colour_as_it_is():
    rules = _rules(SOURCE)
    assert "color: var(--gelb)" in rules[".sanduhr"]
    # the hold is gone, so the red hourglass and its rules are too
    assert not any("haelt" in selector for selector in rules)
    assert "--rot" not in SOURCE.read_text(encoding="utf-8")


def test_the_waiting_bubble_is_dimmed_as_a_whole_by_the_sent_bubbles_own_file():
    rules = _rules(BUBBLE)
    assert _opacity(rules[".von-mir.waiting"]) == 0.6


def test_the_waiting_bubble_is_the_sent_bubble_and_has_no_box_of_its_own():
    """The bubble is drawn by `Nachricht.svelte` from the shape the send gives
    the message, so its width, place, padding, corners, type and parts are the
    sent one's by construction; a rule of its own here would let the two drift
    and the text would jump when the message goes."""
    rules = _rules(SOURCE)
    for selector in (".wartet", ".text", ".anhang"):
        assert selector not in rules, selector
    markup = _markup(SOURCE)
    assert re.search(r"<Nachricht nachricht=\{asMessage\(eintrag\)\} waiting=\{true\} waitRow=\{row\} />", markup)
    source = SOURCE.read_text(encoding="utf-8")
    # the same fields the send fills (lib/chatlauf.svelte.js)
    for field in ("bild: pictures[0] ?? null", "anhaenge: pictures.length > 1 ? pictures : null",
                  "dokument: documents.length === 1 ? documents[0] : null",
                  "dokumente: documents.length > 1 ? documents : null"):
        assert field in source, field
    # the bubble of the sent message takes the row in its place
    assert "class:waiting" in BUBBLE.read_text(encoding="utf-8")
    assert "{@render waitRow()}" in BUBBLE.read_text(encoding="utf-8")


def test_only_the_state_stands_in_the_row_under_the_bubble():
    markup = _markup(SOURCE)
    row = re.search(r'\{#snippet row\(\)\}(.*?)\{/snippet\}', markup, re.S)
    assert row
    for part in ("sanduhr", "marke", "weg"):
        assert part in row.group(1), part
    # none of it is passed into the bubble: the bubble is `Nachricht`
    assert "sanduhr" not in markup.split("{/snippet}", 1)[1]


def test_the_sentence_stands_as_the_hint_of_the_word_and_opens_on_a_tap_where_there_is_no_pointer():
    markup = _markup(SOURCE)
    assert re.search(r'<button class="marke" title=\{t\(\'warteschlange\.erklaerung\'\)\}', markup)
    # the second place is the opened hint, the one a tap on the word shows
    assert markup.count("warteschlange.erklaerung") == 2
    assert re.search(r'\{#if hintOpen === eintrag\.id\}\s*<span class="hint" role="status">\{t\(\'warteschlange\.erklaerung\'\)\}</span>', markup)
    source = SOURCE.read_text(encoding="utf-8")
    # the screen is asked at the tap; a pointer that comes and goes is read as it is
    assert "if (!matchMedia('(hover: none)').matches) return" in source
    assert "<svelte:window onpointerdown={tapOutside} />" in source
    rules = _rules(SOURCE)
    assert ".erklaerung" not in rules
    # it stands over what follows and takes no room: the block keeps its height
    assert "position: absolute" in rules[".hint"]


def test_the_row_under_the_bubble_is_as_high_as_the_row_of_the_sent_bubble():
    """Where "Copy" stands: right-aligned, 6 px below the bubble, as high as
    its buttons (4 px padding around a 15 px sign)."""
    row = _declarations(_rules(SOURCE)[".zeile"])
    mine = _declarations(_rules(BUBBLE)[".fuss.meine"])
    assert row["align-self"] == mine["align-self"] == "flex-end"
    assert row["padding-top"] == mine["padding-top"] == "6px"
    assert row["gap"] == mine["gap"] == "6px"
    button = _declarations(_rules(BUBBLE)[".fuss .tat"])
    assert button["padding"] == "4px"
    assert row["min-height"] == "29px"  # 6 + 4 + 15 + 4


needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="no Node on this machine")


def test_a_waiting_bubble_and_a_sent_message_stand_in_one_block_each():
    """The history spaces its blocks (`.spur` has a gap of its own): the two
    rows of the waiting bubble must stand in one block, like the two rows of a
    sent message, or the gap would open between the bubble and its state."""
    markup = _markup(SOURCE)
    assert re.search(r"\{#each wartende as eintrag \(eintrag\.id\)\}.*<div>\s*<Nachricht ", markup, re.S)


def test_a_message_out_of_the_line_fills_in_from_the_strength_of_the_waiting_bubble_and_does_not_move():
    """The class on the wrapper of a message that came out of the line: its
    animation runs from the opacity the waiting bubble is drawn at to full
    (the same amount as the text's opacity), and with less motion there is
    none. The rise of an ordinary message is switched off for it."""
    css = (FRONTEND / "src" / "stil" / "global.css").read_text(encoding="utf-8")
    keyframes = re.search(r"@keyframes from-queue-fill \{(.*?)\n\}", css, re.S)
    assert keyframes
    assert _opacity(re.search(r"from \{([^}]*)\}", keyframes.group(1)).group(1)) == _opacity(_rules(BUBBLE)[".von-mir.waiting"]) == 0.6
    assert _opacity(re.search(r"to \{([^}]*)\}", keyframes.group(1)).group(1)) == 1.0
    assert re.search(r"\.from-queue \{\s*animation: from-queue-fill 240ms ease-out;", css)
    assert re.search(
        r"@media \(prefers-reduced-motion: reduce\) \{\s*\.from-queue \{ animation: none; \}", css
    )
    for file in ("App.svelte", "phone/ChatView.svelte"):
        text = (FRONTEND / "src" / file).read_text(encoding="utf-8")
        assert "class:from-queue={nachricht.fromQueue}" in text, file
        assert "in:fly={nachricht.fromQueue ? { y: 0, duration: 0 } :" in text, file
    lauf = (FRONTEND / "src" / "lib" / "chatlauf.svelte.js").read_text(encoding="utf-8")
    assert "fromQueue: Boolean(ausReihe)" in lauf
