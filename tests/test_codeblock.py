"""An answer's code block: every finished block can be copied, long lines
wrap, and a wrapped line keeps its one number.

It broke on a prompt a model wrote into a fence without a language. The copy
button sat in a header bar that only existed when a language was named, so
that block had none; and the line ran off into the right edge, cut off with
no visible way on.

Runs the real ``frontend/src/lib/markdown.js`` in node, like
``tests/test_hintergrundmeldung.py``, and asserts on the HTML it draws.
"""

from __future__ import annotations

import json
import shutil

import pytest

from tests.test_hintergrundmeldung import _gezeichnet, _modul, _node

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="no node on this machine")


def test_ein_block_ohne_sprache_hat_einen_kopierknopf():
    html = _gezeichnet("Prompt:\n\n```\nCloseup face portrait, soft light\n```")
    assert '<div class="codeblock umbricht">' in html, html
    assert 'class="code-kopieren"' in html, html
    assert "code-sprache" not in html


def test_ein_block_mit_sprache_nennt_sie_und_hat_einen_kopierknopf():
    html = _gezeichnet("```bash\nnpm install\n```")
    assert '<div class="codeblock umbricht mit-sprache">' in html, html
    assert '<span class="code-sprache">bash</span>' in html
    assert 'class="code-kopieren"' in html


def test_ein_block_im_entstehen_hat_keinen_kopierknopf():
    """Half-written code is not worth copying; the mark arrives with the
    closing fence."""
    html = _gezeichnet("```bash\nnpm ins")
    assert '<div class="codeblock offen umbricht mit-sprache">' in html, html
    assert "code-kopieren" not in html


def test_jede_zeile_ist_eine_reihe_und_die_ziffernbreite_steht_dabei():
    zeilen = [f"line {n}" for n in range(1, 11)]
    html = _gezeichnet("```\n" + "\n".join(zeilen) + "\n```")
    assert 'class="codeblock umbricht nummeriert"' in html, html
    assert '<code style="--ziffern:2">' in html, html
    assert html.count('class="code-zeile"') == 10
    # The number is drawn by CSS, never written into the code.
    assert "code-nummern" not in html


def test_ein_einzeiler_bekommt_keine_reihen():
    html = _gezeichnet("```\nnpm install\n```")
    assert "code-zeile" not in html
    assert "<code>npm install</code>" in html


def test_eine_farbspanne_ueber_den_zeilenumbruch_wird_je_reihe_geschlossen():
    """A multi-line string or comment is ONE highlighter span across the
    line break. Each row has to be well-formed on its own: closed at its
    end, reopened in the next."""
    ersatz = """
const hervorheben = () => '<span class="hljs-string">"a\\nb"</span> x';
const t = () => 'Copy';
const dateiart = () => null;
const dateiname = () => null;
"""
    zaun = json.dumps("```py\nsource of\ntwo lines\n```")
    html = _node(f"{_modul(ersatz)}\nconsole.log(rendern({zaun}))")
    assert (
        '<span class="code-zeile"><span><span class="hljs-string">"a</span></span></span>'
        '<span class="code-zeile"><span><span class="hljs-string">b"</span> x</span></span>'
    ) in html, html


def test_der_kopierknopf_kopiert_die_zeilen_ohne_nummern_mit_umbruechen():
    """The copy half, run against a stand-in for the page: the rows are
    joined with line breaks, and no number rides along."""
    zaun = json.dumps("```\nfirst\n\nthird\n```")
    skript = f"""{_modul()}
const html = rendern({zaun});
const reihen = [...html.matchAll(/<span class="code-zeile"><span>(.*?)<\\/span><\\/span>/g)].map((m) => m[1]);
const code = {{ querySelectorAll: () => reihen.map((r) => ({{ textContent: r }})), textContent: 'unused' }};
const knopf = {{ closest: () => ({{ querySelector: () => code }}) }};
let kopiert = null;
Object.defineProperty(globalThis, 'navigator', {{ configurable: true, value: {{ clipboard: {{ writeText: (x) => {{ kopiert = x; return Promise.resolve(); }} }} }} }});
codeKopierKlick({{ target: {{ closest: () => knopf }} }}, () => console.log(JSON.stringify(kopiert)));
"""
    assert json.loads(_node(skript)) == "first\n\nthird"
