"""The click catcher, run for real.

A foreign link in a program window must open the browser only when a person
clicked it. The catcher (fenster-electron/linkclicks.js) is a preload, so it
needs a window and electron's renderer side; node runs it here with a stand-in
for `electron` and for the window, the same detour tests/test_adressregel.py
takes for the rule itself.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

WURZEL = Path(__file__).resolve().parents[1]
MODUL = WURZEL / "fenster-electron" / "linkclicks.js"

SKRIPT = """
const Module = require('module')
const sent = []
const fakeElectron = { ipcRenderer: { send: (...a) => sent.push(a) } }
const load = Module._load
Module._load = function (request, ...rest) {
  return request === 'electron' ? fakeElectron : load.call(this, request, ...rest)
}
const catcher = require(%(modul)s)

// A link element and a click on it, as far as the catcher reads them.
const link = (href, attrs = {}) => ({
  tagName: 'A', href, hasAttribute: (n) => n === 'href' || n in attrs,
})
const click = (path, { isTrusted = true, defaultPrevented = false, button = 0 } = {}) => {
  const event = {
    isTrusted, defaultPrevented, button, prevented: false,
    composedPath: () => path,
    preventDefault() { this.prevented = true },
  }
  return event
}
const here = new URL('http://127.0.0.1:8090/app/')
const run = (event, where = here) => {
  sent.length = 0
  const taken = catcher.handleClick(event, fakeElectron.ipcRenderer, where)
  return { taken, prevented: event.prevented, sent: sent.map((a) => a.slice()) }
}

const result = {
  channel: catcher.CHANNEL,
  foreign: run(click([{ tagName: 'SPAN' }, link('https://exe-hq.net/hilfe?x=1')])),
  foreign_http: run(click([link('http://exe-hq.net/')])),
  scripted: run(click([link('https://exe-hq.net/')], { isTrusted: false })),
  handled: run(click([link('https://exe-hq.net/')], { defaultPrevented: true })),
  middle: run(click([link('https://exe-hq.net/')], { button: 1 })),
  middle_scripted: run(click([link('https://exe-hq.net/')], { button: 1, isTrusted: false })),
  secondary: run(click([link('https://exe-hq.net/')], { button: 2 })),
  own: run(click([link('http://127.0.0.1:8090/hilfe/')])),
  own_localhost: run(click([link('http://localhost:8090/hilfe/')])),
  other_port: run(click([link('http://127.0.0.1:8091/app/')])),
  javascript: run(click([link('javascript:alert(1)')])),
  file: run(click([link('file:///etc/passwd')])),
  download: run(click([link('https://exe-hq.net/x.zip', { download: true })])),
  no_link: run(click([{ tagName: 'DIV' }, { tagName: 'BODY' }])),
  garbage: run(click([link('http://')])),
  from_splash: run(click([link('https://exe-hq.net/')]), new URL('file:///x/anzeige/index.html')),
}

// install(): the listener is on the window and takes a click once.
const listeners = []
const win = { location: here, addEventListener: (t, f) => listeners.push([t, f]) }
catcher.install(win, fakeElectron.ipcRenderer)
sent.length = 0
const e = click([link('https://exe-hq.net/')])
listeners.forEach(([t, f]) => t === 'click' && f(e))
result.install = { types: listeners.map(([t]) => t), sent: sent.map((a) => a.slice()), prevented: e.prevented }

console.log(JSON.stringify(result))
"""


@pytest.fixture(scope="module")
def antwort():
    if not shutil.which("node"):
        pytest.skip("node is missing")
    ausdruck = SKRIPT % {"modul": json.dumps(str(MODUL))}
    lauf = subprocess.run(
        ["node", "-e", ausdruck], capture_output=True, text=True, timeout=60
    )
    assert lauf.returncode == 0, (lauf.stdout + lauf.stderr)[-2000:]
    return json.loads(lauf.stdout)


def _genommen(adresse):
    return {"taken": True, "prevented": True, "sent": [["open-link", adresse]]}


NICHTS = {"taken": False, "prevented": False, "sent": []}


def test_a_real_click_on_a_foreign_link_is_stopped_and_asked_for_once(antwort):
    assert antwort["channel"] == "open-link"
    assert antwort["foreign"] == _genommen("https://exe-hq.net/hilfe?x=1")
    assert antwort["foreign_http"] == _genommen("http://exe-hq.net/")
    # A person's middle click is told here once: the shell no longer opens
    # it through the window-open handler outside the main window.
    assert antwort["middle"] == _genommen("https://exe-hq.net/")
    # The window is the splash's file page: still a person's click.
    assert antwort["from_splash"] == _genommen("https://exe-hq.net/")


def test_what_is_not_a_persons_click_on_a_foreign_link_asks_for_nothing(antwort):
    """A script's click (not trusted), a click the page handled itself, a
    script's middle click, the secondary button, a link of our own in either
    spelling, a link that is a download and a click on nothing."""
    for name in (
        "scripted", "handled", "middle_scripted", "secondary", "own", "own_localhost",
        "download", "no_link",
    ):
        assert antwort[name] == NICHTS, name


def test_other_schemes_are_left_to_the_navigation_rule(antwort):
    """The catcher never asks for a `javascript:` or `file:` address and never
    stops its click: the navigation rule stops what must not load. Another
    port on loopback is not our page and goes out like any foreign one."""
    for name in ("javascript", "file", "garbage"):
        assert antwort[name] == NICHTS, name
    assert antwort["other_port"] == _genommen("http://127.0.0.1:8091/app/")


def test_the_catcher_listens_on_the_window_and_takes_a_click_once(antwort):
    assert antwort["install"] == {
        "types": ["click", "auxclick"],
        "sent": [["open-link", "https://exe-hq.net/"]],
        "prevented": True,
    }


def test_the_catcher_names_the_same_own_hosts_as_the_address_rule():
    """The catcher is a sandboxed preload and cannot read adressregel.js, so
    it carries its own copy of the two loopback names. This holds the two
    lists together."""
    import re

    regel = (WURZEL / "fenster-electron" / "adressregel.js").read_text(encoding="utf-8")
    fenger = MODUL.read_text(encoding="utf-8")
    eigene = re.search(r"EIGENE_WIRTE = new Set\(\[(.*?)\]\)", regel, re.S)
    lokal = re.search(r"LOOPBACK = new Set\(\[(.*?)\]\)", fenger, re.S)
    assert eigene and lokal
    assert eigene.group(1).strip() == lokal.group(1).strip()
