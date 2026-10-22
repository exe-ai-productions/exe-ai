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
from pathlib import Path

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
const knopf = {{ classList: {{ add() {{}}, remove() {{}} }}, closest: () => ({{ querySelector: () => code }}) }};
let kopiert = null;
Object.defineProperty(globalThis, 'navigator', {{ configurable: true, value: {{ clipboard: {{ writeText: (x) => {{ kopiert = x; return Promise.resolve(); }} }} }} }});
codeKopierKlick({{ target: {{ closest: () => knopf }} }}, () => console.log(JSON.stringify(kopiert)));
"""
    assert json.loads(_node(skript)) == "first\n\nthird"


# --- the button wears a tick for a second after a copy -----------------------

CSS = Path(__file__).resolve().parent.parent / "frontend/src/stil/codeblock.css"

# A stand-in page: buttons with a class list, a clock that only moves when told,
# and a clipboard that answers as each script decides.
STAND_IN = """
const makeButton = (name) => {
  const classes = new Set();
  const code = { querySelectorAll: () => [], textContent: name };
  return { name, tickTimer: undefined, classList: { add: (name) => classes.add(name), remove: (name) => classes.delete(name), contains: (name) => classes.has(name) },
    closest: () => ({ querySelector: () => code }) };
};
const click = (target, done) => codeKopierKlick({ target: { closest: () => target } }, done);
const clock = [];
globalThis.setTimeout = (f, ms) => { clock.push({ f, ms, live: true }); return clock.length - 1; };
globalThis.clearTimeout = (id) => { if (clock[id]) clock[id].live = false; };
const runOut = () => clock.filter((entry) => entry.live).forEach((entry) => { entry.live = false; entry.f(); });
const clipboard = (answer) => Object.defineProperty(globalThis, 'navigator', { configurable: true, value: { clipboard: { writeText: () => answer } } });
const settle = () => new Promise((r) => setImmediate(r));
"""


def _stand_in(script: str):
    return json.loads(_node(f"{_modul()}\n{STAND_IN}\n(async () => {{ {script} }})()"))


def test_the_button_shows_the_tick_only_after_the_copy_and_then_for_a_second():
    out = _stand_in("""
    const b = makeButton('a');
    clipboard(Promise.resolve());
    let reported = 0;
    click(b, () => { reported += 1; });
    const at_once = b.classList.contains('copied');
    await settle();
    const after = b.classList.contains('copied');
    const deadlines = clock.map((entry) => entry.ms);
    runOut();
    console.log(JSON.stringify({ at_once, after, deadlines, reported, back: !b.classList.contains('copied') }));
    """)
    assert out == {"at_once": False, "after": True, "deadlines": [1000], "reported": 1, "back": True}


def test_a_refused_write_keeps_the_copy_mark_and_reports_nothing():
    out = _stand_in("""
    const b = makeButton('a');
    clipboard(Promise.reject(new Error('denied')));
    let reported = 0;
    click(b, () => { reported += 1; });
    await settle();
    console.log(JSON.stringify({ tick: b.classList.contains('copied'), reported, deadlines: clock.length }));
    """)
    assert out == {"tick": False, "reported": 0, "deadlines": 0}


def test_a_second_click_within_the_second_copies_again_and_restarts_it():
    out = _stand_in("""
    const b = makeButton('a');
    clipboard(Promise.resolve());
    let reported = 0;
    click(b, () => { reported += 1; });
    await settle();
    click(b, () => { reported += 1; });
    await settle();
    const alive = clock.filter((entry) => entry.live).length;
    console.log(JSON.stringify({ reported, alive, set_up: clock.length, tick: b.classList.contains('copied') }));
    """)
    # Two copies, two timers set, only the newest alive; the tick still stands.
    assert out == {"reported": 2, "alive": 1, "set_up": 2, "tick": True}


def test_with_two_blocks_only_the_pressed_one_changes():
    out = _stand_in("""
    const a = makeButton('a');
    const b = makeButton('b');
    clipboard(Promise.resolve());
    click(a, () => {});
    await settle();
    console.log(JSON.stringify({ a: a.classList.contains('copied'), b: b.classList.contains('copied') }));
    """)
    assert out == {"a": True, "b": False}


def test_the_button_carries_both_signs_and_keeps_its_name():
    html = _gezeichnet("```\nnpm install\n```")
    button = html[html.index('<button class="code-kopieren"') : html.index("</button>")]
    assert button.count("<svg") == 2 and 'class="code-tick"' in button, button
    assert 'M4 12.5 L9.5 18 L20 6.5' in button  # the house's tick drawing
    assert 'title="' in button and 'aria-label="' in button and "copied" not in button
    assert "code-kopieren" not in _gezeichnet("```bash\nnpm ins")


def test_the_signs_cross_fade_with_the_block_duration():
    css = CSS.read_text(encoding="utf-8")
    assert ".code-kopieren > svg { grid-area: 1 / 1; transition: opacity 0.18s; }" in css
    assert ".code-kopieren.copied > .code-tick { opacity: 1; }" in css
    assert ".code-kopieren.copied > svg:first-child { opacity: 0; }" in css
