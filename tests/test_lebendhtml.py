"""Drawing streamed HTML in place (`frontend/src/lib/lebendhtml.js`).

The claim is about the DOM, so it is checked against a real one: the
library is loaded into a headless Chrome page together with the cases
below, and the page reports back through `--dump-dom`. Skipped where no
Chrome is installed, exactly like the node-bound tests skip without node.
"""

from __future__ import annotations

import html
import json
import re
import subprocess
import time
from pathlib import Path

import pytest

from app import appfenster, prozessstopp

WURZEL = Path(__file__).resolve().parent.parent
QUELLE = WURZEL / "frontend/src/lib/lebendhtml.js"

FAELLE = """
const meldung = {}
const kasten = document.getElementById('kasten')
const mark = (n) => { n._marke = true; return n }
const markiert = (n) => n?._marke === true

// First draw: a plain fill.
htmlAngleichen(kasten, '<p>Hallo</p>')
meldung.erstes = kasten.innerHTML

// Growing text keeps the paragraph AND its text node.
mark(kasten.firstChild); mark(kasten.firstChild.firstChild)
htmlAngleichen(kasten, '<p>Hallo Welt</p>')
meldung.text = {
  html: kasten.innerHTML,
  absatzBleibt: markiert(kasten.firstChild),
  textknotenBleibt: markiert(kasten.firstChild.firstChild),
}

// A growing list keeps its finished items and appends the new one.
htmlAngleichen(kasten, '<ul><li>a</li><li>b</li></ul>')
mark(kasten.firstChild); mark(kasten.firstChild.children[0])
htmlAngleichen(kasten, '<ul><li>a</li><li>b</li><li>c</li></ul>')
meldung.liste = {
  html: kasten.innerHTML,
  listeBleibt: markiert(kasten.firstChild),
  erstesBleibt: markiert(kasten.firstChild.children[0]),
}

// The parser changing its mind (a paragraph turns out to be a list)
// replaces the element.
htmlAngleichen(kasten, '<p>- a</p>')
mark(kasten.firstChild)
htmlAngleichen(kasten, '<ul><li>a</li></ul>')
meldung.umbau = { html: kasten.innerHTML, absatzWeg: !markiert(kasten.firstChild) }

// Shrinking drops the tail.
htmlAngleichen(kasten, '<p>a</p><p>b</p><p>c</p>')
htmlAngleichen(kasten, '<p>a</p>')
meldung.kuerzer = kasten.innerHTML

// A changed attribute is a different element; its parent is kept.
htmlAngleichen(kasten, '<pre><code class="x">a</code></pre>')
mark(kasten.firstChild); mark(kasten.firstChild.firstChild)
htmlAngleichen(kasten, '<pre><code class="y">a</code></pre>')
meldung.attribut = {
  html: kasten.innerHTML,
  preBleibt: markiert(kasten.firstChild),
  codeNeu: !markiert(kasten.firstChild.firstChild),
}

// A tick on a live button: the class the page set is no difference, so the
// button stays the same node with its class and its timer while the text
// after the block grows. Any other difference still replaces it.
const frame = (attributes, tail) => `<div class="codeblock"><button class="code-kopieren"${attributes}>x</button></div><p>${tail}</p>`
htmlAngleichen(kasten, frame('', 'one'))
const tickButton = mark(kasten.querySelector('button'))
tickButton.classList.add('copied')
tickButton.tickTimer = 7
htmlAngleichen(kasten, frame('', 'one two'))
meldung.liveTick = {
  same: markiert(kasten.querySelector('button')),
  copied: kasten.querySelector('button').classList.contains('copied'),
  timer: kasten.querySelector('button').tickTimer,
  text: kasten.querySelector('p').textContent,
}
htmlAngleichen(kasten, frame(' title="t"', 'one two'))
meldung.liveTickOtherAttribute = {
  replaced: !markiert(kasten.querySelector('button')),
  copied: kasten.querySelector('button').classList.contains('copied'),
}
htmlAngleichen(kasten, frame('', 'one two'))
const otherButton = mark(kasten.querySelector('button'))
otherButton.classList.add('copied', 'other')
htmlAngleichen(kasten, frame('', 'one two three'))
meldung.liveTickOtherClass = { replaced: !markiert(kasten.querySelector('button')) }

// Empty and missing input clear the box.
htmlAngleichen(kasten, '')
meldung.leer = kasten.innerHTML
htmlAngleichen(kasten, undefined)
meldung.fehlt = kasten.innerHTML

// The point of it all: a scroller standing at its floor is not moved
// while the answer inside grows. The rebuild that this replaces is
// measured beside it — with a layout forced between tearing out and
// putting back, the way a transition or an observer forces one — so the
// throw-back this guards against is on record, not assumed.
const rolle = document.getElementById('rolle')
const zeilen = (n) => Array.from({ length: n }, (_, i) => `<p>Zeile ${i}</p>`).join('')
htmlAngleichen(kasten, zeilen(40))
rolle.scrollTop = rolle.scrollHeight
const oben = rolle.scrollTop
htmlAngleichen(kasten, zeilen(41))
meldung.rollt = { vorher: oben, nachher: rolle.scrollTop, gewachsen: rolle.scrollHeight > oben + rolle.clientHeight }

rolle.scrollTop = rolle.scrollHeight
const obenAlt = rolle.scrollTop
kasten.replaceChildren()
void rolle.offsetHeight
kasten.innerHTML = zeilen(42)
meldung.neuaufbau = { vorher: obenAlt, nachher: rolle.scrollTop }

// Fading in: the characters that came up within the last 280 ms wear a span
// with a negative delay of their age; what is older is plain again. The clock
// is the page's own `performance.now`, set by hand so no timer is needed.
let clock = 1000
performance.now = () => clock
const flowing = document.getElementById('flowing')
const spans = () => Array.from(flowing.querySelectorAll('.flow-char')).map(
  (s) => ({ text: s.textContent, delay: s.style.animationDelay }))
const action = lebendHtml(flowing, { html: '<p>Hello</p>', fadeIn: false })
meldung.flowFirst = { spans: spans(), text: flowing.textContent }
clock = 1100
action.update({ html: '<p>Hello world</p>', fadeIn: true })
meldung.flowNew = { spans: spans(), text: flowing.textContent }
clock = 1200
action.update({ html: '<p>Hello world, how</p>', fadeIn: true })
meldung.flowMore = { spans: spans(), text: flowing.textContent }
clock = 1500
action.update({ html: '<p>Hello world, how</p>', fadeIn: true })
meldung.flowLater = { spans: spans(), text: flowing.textContent, html: flowing.innerHTML }
clock = 1600
action.update({ html: '<p>Hello world, how are</p>', fadeIn: false })
meldung.flowWhole = { spans: spans(), text: flowing.textContent }
// A text that is handed in as a plain string never fades.
const plain = document.getElementById('plain')
lebendHtml(plain, '<p>All here</p>')
meldung.plain = { spans: Array.from(plain.querySelectorAll('.flow-char')).length, text: plain.textContent }

document.getElementById('ergebnis').textContent = JSON.stringify(meldung)
"""


def _seite() -> str:
    quelle = QUELLE.read_text(encoding="utf-8").replace("export function", "function")
    return (
        "<!doctype html><meta charset=utf-8><title>lebendhtml</title>"
        '<div id="rolle" style="height:120px;overflow:auto"><div id="kasten"></div></div>'
        '<div id="flowing"></div><div id="plain"></div>'
        '<pre id="ergebnis"></pre>'
        f"<script>{quelle}\n{FAELLE}</script>"
    )


@pytest.fixture(scope="module")
def meldung(tmp_path_factory) -> dict:
    programm = appfenster._programm() or pytest.skip("no Chrome on this machine")
    ordner = tmp_path_factory.mktemp("lebendhtml")
    seite = ordner / "pruefung.html"
    seite.write_text(_seite(), encoding="utf-8")
    # Chrome prints the page and then keeps standing: its updater child
    # holds the pipe open. Read until the document is complete, then end
    # the whole process group ourselves.
    lauf = subprocess.Popen(
        [
            programm,
            "--headless=new",
            "--disable-gpu",
            "--no-first-run",
            "--disable-background-networking",
            f"--user-data-dir={ordner / 'profil'}",
            "--dump-dom",
            seite.as_uri(),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        start_new_session=True,
    )
    zeilen: list[str] = []
    assert lauf.stdout is not None
    try:
        ende = time.monotonic() + 60
        while time.monotonic() < ende:
            zeile = lauf.stdout.readline()
            if not zeile:
                break
            zeilen.append(zeile)
            if "</html>" in zeile:
                break
    finally:
        # The whole tree, the way the program ends its own helpers: there
        # is no ``killpg`` on Windows (app/prozessstopp.py).
        prozessstopp.beenden(lauf, frist=5)
    ausgabe = "".join(zeilen)
    treffer = re.search(r'<pre id="ergebnis">(.*?)</pre>', ausgabe, re.S)
    assert treffer and treffer.group(1), f"the page reported nothing:\n{ausgabe[-800:]}"
    return json.loads(html.unescape(treffer.group(1)))


def test_der_erste_aufbau_fuellt_die_box(meldung):
    assert meldung["erstes"] == "<p>Hallo</p>"


def test_wachsender_text_behaelt_absatz_und_textknoten(meldung):
    assert meldung["text"] == {
        "html": "<p>Hallo Welt</p>",
        "absatzBleibt": True,
        "textknotenBleibt": True,
    }


def test_eine_wachsende_liste_behaelt_ihre_fertigen_eintraege(meldung):
    assert meldung["liste"] == {
        "html": "<ul><li>a</li><li>b</li><li>c</li></ul>",
        "listeBleibt": True,
        "erstesBleibt": True,
    }


def test_ein_anderer_baustein_wird_ersetzt(meldung):
    assert meldung["umbau"] == {"html": "<ul><li>a</li></ul>", "absatzWeg": True}


def test_kuerzerer_inhalt_verliert_seinen_schwanz(meldung):
    assert meldung["kuerzer"] == "<p>a</p>"


def test_ein_geaendertes_attribut_ersetzt_nur_dieses_element(meldung):
    assert meldung["attribut"] == {
        "html": '<pre><code class="y">a</code></pre>',
        "preBleibt": True,
        "codeNeu": True,
    }


def test_a_tick_on_a_live_button_survives_the_next_chunk(meldung):
    assert meldung["liveTick"] == {"same": True, "copied": True, "timer": 7, "text": "one two"}


def test_a_live_button_that_differs_in_another_attribute_or_class_is_replaced(meldung):
    assert meldung["liveTickOtherAttribute"] == {"replaced": True, "copied": False}
    assert meldung["liveTickOtherClass"] == {"replaced": True}


def test_leer_und_fehlend_raeumen_die_box(meldung):
    assert meldung["leer"] == ""
    assert meldung["fehlt"] == ""


def test_die_ansicht_bleibt_stehen_waehrend_die_antwort_waechst(meldung):
    rollt = meldung["rollt"]
    assert rollt["gewachsen"], "the measurement saw no growing scroll area"
    assert rollt["nachher"] == rollt["vorher"], "the aligner moved the view"


def test_der_alte_neuaufbau_wirft_die_ansicht_zurueck(meldung):
    """The control: the rebuild this library replaces does throw the
    reader back once a layout lands between tearing out and putting back.
    If this ever stops failing, the browser changed — the guard above
    still holds, but the reason recorded in lebendhtml.js no longer does."""
    neu = meldung["neuaufbau"]
    assert neu["nachher"] < neu["vorher"], neu


def test_new_characters_fade_in_and_older_ones_stand_plain_again(meldung):
    """The characters of a flowing text fade in for 280 ms: each piece that
    came up in that time wears a span whose negative delay is its age, so a
    span made afresh with the next frame goes on from where the last one
    was. Whatever is older is plain text again, and the text itself is the
    same in every step."""
    assert meldung["flowFirst"] == {"spans": [], "text": "Hello"}
    assert meldung["flowNew"] == {
        "spans": [{"text": " world", "delay": "0ms"}],
        "text": "Hello world",
    }
    assert meldung["flowMore"] == {
        "spans": [
            {"text": " world", "delay": "-100ms"},
            {"text": ", how", "delay": "0ms"},
        ],
        "text": "Hello world, how",
    }
    assert meldung["flowLater"]["spans"] == []
    assert meldung["flowLater"]["html"] == "<p>Hello world, how</p>"


def test_without_fade_in_the_text_stands_whole_and_without_wrappers(meldung):
    """The silence probe: an answer that is stored, and the text of a window
    that reduces motion, are drawn whole — no span, no delay."""
    assert meldung["flowWhole"] == {"spans": [], "text": "Hello world, how are"}
    assert meldung["plain"] == {"spans": 0, "text": "All here"}
