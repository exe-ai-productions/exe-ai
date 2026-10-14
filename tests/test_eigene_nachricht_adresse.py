"""An address in the own message is a link; the rest stays text.

The real detection (`adressTeile` in `lib/markdown.js`) is run in node, the
way `tests/test_markdown_bilder.py` runs the renderer. The bubble itself is a
component whose logic lives in its instance script, so its three places are
read as source text.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from tests.test_hintergrundmeldung import _modul, _node

ROOT = Path(__file__).resolve().parent.parent
BUBBLE = (ROOT / "frontend/src/teile/Nachricht.svelte").read_text(encoding="utf-8")

needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="no node on this machine")

STAND_IN = """
const hervorheben = (code) => String(code);
const t = () => 'Copy';
const dateiart = () => null;
const dateiname = (sprache, nummer) => sprache + '-' + nummer;
"""


def _pieces(text: str) -> list[dict]:
    script = f"{_modul(STAND_IN)}\nconsole.log(JSON.stringify(adressTeile({json.dumps(text)})))"
    return json.loads(_node(script))


@needs_node
def test_an_address_in_the_middle_of_a_sentence_is_a_link():
    assert _pieces("schau https://www.youtube.com an") == [
        {"text": "schau "},
        {"text": "https://www.youtube.com", "href": "https://www.youtube.com"},
        {"text": " an"},
    ]


@needs_node
@pytest.mark.parametrize(
    ("text", "address"),
    [
        ("siehe https://example.com/a.", "https://example.com/a"),
        ("erst https://example.com/a, dann", "https://example.com/a"),
        ("(siehe https://example.com/a)", "https://example.com/a"),
        ("ist das https://example.com/a?", "https://example.com/a"),
        ("http://example.com/x_(film) ok", "http://example.com/x_(film)"),
        ("HTTPS://EXAMPLE.COM/A weiter", "HTTPS://EXAMPLE.COM/A"),
        ("https://example.com/a?b=1&c=2#top fertig", "https://example.com/a?b=1&c=2#top"),
    ],
)
def test_a_sentence_mark_behind_the_address_is_not_part_of_it(text, address):
    links = [piece for piece in _pieces(text) if "href" in piece]
    assert [piece["href"] for piece in links] == [address]
    # Put together, the pieces are the message — mark and all.
    assert "".join(piece["text"] for piece in _pieces(text)) == text


@needs_node
def test_two_addresses_are_two_links_with_their_words_between():
    pieces = _pieces("a https://one.example und https://two.example.")
    assert [p.get("href") for p in pieces] == [None, "https://one.example", None, "https://two.example", None]
    assert pieces[-1] == {"text": "."}


@needs_node
@pytest.mark.parametrize(
    "text",
    [
        "ein Satz ohne Adresse",
        "**fett** und `code` und _kursiv_",
        "<b>x</b> <script>alert(1)</script>",
        "www.youtube.com ohne Schema",
        "mailto:a@b.de und ftp://example.com und javascript:alert(1)",
        "nur das Schema https:// und sonst nichts",
        "zwei\nZeilen mit  doppeltem Leerraum\n\nund Leerzeile",
        "",
    ],
)
def test_silence_everything_but_an_address_stays_text_character_for_character(text):
    pieces = _pieces(text)
    assert not any("href" in piece for piece in pieces)
    assert "".join(piece["text"] for piece in pieces) == text
    assert len(pieces) == (1 if text else 0)


@needs_node
def test_an_address_between_markup_does_not_take_the_markup_with_it():
    pieces = _pieces('<a href="https://example.com/x">hier</a>')
    links = [piece["href"] for piece in pieces if "href" in piece]
    assert links == ["https://example.com/x"]
    assert "".join(piece["text"] for piece in pieces) == '<a href="https://example.com/x">hier</a>'


def test_the_bubble_draws_the_pieces_in_all_three_places():
    """With an attachment, behind the skill pill, and plain; nothing of the
    own text goes through the markdown renderer or `@html`."""
    assert "adressTeile" in BUBBLE.split("</script>", 1)[0]
    snippet = BUBBLE.split("{#snippet eigenerText(inhalt)}", 1)[1].split("{/snippet}", 1)[0]
    assert "{#each adressTeile(inhalt) as teil}" in snippet
    assert 'target="_blank" rel="noopener noreferrer"' in snippet and "href={teil.href}" in snippet
    assert "@html" not in snippet
    assert '<div class="bildtext">{@render eigenerText(nachricht.content)}</div>' in BUBBLE
    assert "{@render eigenerText(ohneSkill)}" in BUBBLE
    assert "{:else}{@render eigenerText(nachricht.content)}{/if}" in BUBBLE
    assert "{ohneSkill}" not in BUBBLE.replace("eigenerText(ohneSkill)", "")


def test_the_own_link_has_the_colour_of_a_link_in_an_answer():
    assert ".eigenlink { color: var(--blau); text-underline-offset: 3px; }" in BUBBLE
    assert ".antwort :global(a) { color: var(--blau); text-underline-offset: 3px; }" in BUBBLE
