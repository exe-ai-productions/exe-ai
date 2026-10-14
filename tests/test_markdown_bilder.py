"""Markdown images in the answer: the program draws what the page may load
anyway, turns every other address into a link, and leaves the rest as text.

The real renderer (`lib/markdown.js`) is run in node, the way
``tests/test_dokumentkarte.py`` runs it.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from tests.test_hintergrundmeldung import _modul, _node

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "frontend/src"

needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="no node on this machine")

STAND_IN = """
globalThis.location = { origin: 'http://127.0.0.1:8273' };
const hervorheben = (code) => String(code);
const t = () => 'Copy';
const dateiart = () => null;
const dateiname = (sprache, nummer) => sprache + '-' + nummer;
"""


def _drawn(text: str) -> str:
    return _node(f"{_modul(STAND_IN)}\nconsole.log(rendern({json.dumps(text)}))")


@needs_node
def test_an_image_on_a_path_of_the_service_is_drawn_with_its_alt_text():
    html = _drawn("![A cat](/api/v1/files/cat.png)")
    assert '<img class="md-bild" src="/api/v1/files/cat.png" alt="A cat" loading="lazy">' in html


@needs_node
def test_an_inline_data_image_is_drawn():
    html = _drawn("![Dot](data:image/png;base64,iVBORw0KGgo=)")
    assert '<img class="md-bild" src="data:image/png;base64,iVBORw0KGgo=" alt="Dot"' in html


@needs_node
def test_a_full_address_of_the_own_origin_is_drawn():
    html = _drawn("![Own](http://127.0.0.1:8273/api/v1/x.png)")
    assert '<img class="md-bild" src="http://127.0.0.1:8273/api/v1/x.png"' in html


@needs_node
def test_a_foreign_address_becomes_a_link_without_the_exclamation_mark():
    html = _drawn("![A cat](https://example.com/a.png)")
    assert "<img" not in html
    assert (
        '<a href="https://example.com/a.png" target="_blank" rel="noopener noreferrer">A cat</a>'
        in html
    )
    assert "!<a" not in html


@needs_node
def test_a_foreign_image_without_alt_text_is_a_link_with_its_address():
    html = _drawn("![](https://example.com/a.png)")
    assert "<img" not in html
    assert ">https://example.com/a.png</a>" in html


@needs_node
@pytest.mark.parametrize(
    "text",
    [
        "![x](//example.com/a.png)",
        "![x](javascript:alert(1))",
        "![x](ftp://example.com/a.png)",
        "![x](relative/a.png)",
    ],
)
def test_every_other_form_stays_text(text):
    html = _drawn(text)
    assert "<img" not in html and "<a " not in html
    assert "![x]" in html


@needs_node
def test_an_image_in_backticks_stays_text():
    html = _drawn("write `![Bild](/api/v1/x.png)` for an image")
    assert "<img" not in html
    assert "<code>![Bild](/api/v1/x.png)</code>" in html


@needs_node
def test_the_alt_text_cannot_write_markup_into_the_image():
    """Emphasis and link rules read the finished text; the image is set aside
    first, so nothing written in the alt text reaches its attributes."""
    html = _drawn('![*a* **b** `c` ~~d~~ "q"](/api/v1/x.png)')
    assert html.count("<img") == 1
    tag = html[html.index("<img"): html.index(">", html.index("<img")) + 1]
    assert "<em>" not in tag and "<strong>" not in tag and "<del>" not in tag
    assert "<code>" not in tag
    assert 'alt="*a* **b** `c` ~~d~~ &quot;q&quot;"' in tag


@needs_node
def test_ordinary_links_and_emphasis_read_as_before():
    html = _drawn("A [link](https://example.com), **bold** and *italic*.")
    assert '<a href="https://example.com"' in html
    assert "<strong>bold</strong>" in html and "<em>italic</em>" in html
    assert "<img" not in html


def test_an_image_is_at_most_as_wide_as_its_text():
    message = (SOURCE / "teile/Nachricht.svelte").read_text(encoding="utf-8")
    report = (SOURCE / "stil/berichttext.css").read_text(encoding="utf-8")
    assert ".antwort :global(img.md-bild) { max-width: 100%; height: auto; }" in message
    assert ".berichttext img.md-bild { max-width: 100%; height: auto; }" in report
