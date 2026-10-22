"""The head of "Maße & Lauf" stays one line and the last seed is a button beside
the dice, measured in a real browser.

``StudioBasics.svelte`` is built as shipped on the page of
``tests/test_studio_generate_stays_chrome.py`` at the left column's smallest and
at a wider width, in German and in English, first before a picture was drawn
and then with a last seed. The head is one line high and its title one text
line; only "Standard" stands in it, whole and inside the card; the button for
the last seed stands beside the dice at their size, is blocked until there is a
seed, and then puts it into the field and holds it; the row of the seed keeps
its height when the seed arrives. Skipped where there is no Chrome or no node.
"""

from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
from pathlib import Path
from uuid import uuid4

import pytest

from app import appfenster, prozessstopp
from tests import test_studio_generate_stays_chrome as base

pytestmark = base.pytestmark

ROOT = Path(__file__).resolve().parent.parent
FRONTEND = base.FRONTEND
GERMAN = json.loads((ROOT / "app" / "locales" / "de.json").read_text(encoding="utf-8"))
ENGLISH = json.loads((ROOT / "app" / "locales" / "en.json").read_text(encoding="utf-8"))
LAST = 646427435

SHELL = """<script>
  import StudioBasics from '../../src/teile/StudioBasics.svelte'
  const width = Number(new URLSearchParams(location.search).get('width') || 285)
</script>

<div id="frame" style="width: {width}px; position: relative;"><StudioBasics /></div>
"""

CASES = r"""
const params = new URLSearchParams(location.search)
const wait = (ms) => new Promise((r) => setTimeout(r, ms))
const { werte, seedlage } = window.__studio
const TITLE = window.__title
const section = () => [...document.querySelectorAll('section.studioabschnitt')]
  .find((s) => s.querySelector('.kopf > span')?.textContent.trim() === TITLE)
for (let k = 0; k < 100 && !section(); k += 1) await wait(100)
await wait(800)
const box = (node) => {
  const r = node.getBoundingClientRect()
  return { left: r.left, right: r.right, top: r.top, width: r.width, height: r.height }
}
const measure = () => {
  const s = section()
  const head = s.querySelector('.kopf')
  const title = s.querySelector('.kopf > span')
  const card = s.querySelector('.karte')
  const row = [...document.querySelectorAll('.zeile')].find((z) => z.querySelector('.seedplatz'))
  const dice = row.querySelector('.wuerfel')
  const reuse = row.querySelector('.seed-reuse')
  return {
    head: box(head),
    title: { ...box(title), clipped: title.scrollWidth > title.clientWidth },
    card: box(card),
    buttons: [...head.querySelectorAll('button')].map((b) => ({ text: b.textContent.trim(), ...box(b) })),
    row: box(row),
    dice: box(dice),
    reuse: reuse ? { ...box(reuse), disabled: reuse.disabled, hint: reuse.title } : null,
  }
}
const report = { width: Number(params.get('width') || 285), lang: params.get('lang') }
report.before = measure()
seedlage.letzter = %(last)s
await wait(500)
report.after = measure()
document.querySelector('.seed-reuse')?.click()
await wait(300)
report.taken = { seed: werte.seed, mode: werte.seed_modus }
document.title = 'open'
document.getElementById('ergebnis').textContent = JSON.stringify(report)
"""


def _entry() -> str:
    entry = base.ENTRY_JS % {
        "global": "../../src/stil/global.css", "studio": "../../src/lib/studio.svelte.js",
    }
    entry = entry.replace(
        "import { werte, auswahl } from",
        "import { texte } from '../../src/lib/texte.svelte.js'\n"
        "import { seedlage } from '../../src/lib/bildseed.svelte.js'\n"
        "import german from '../../../app/locales/de.json'\n"
        "import english from '../../../app/locales/en.json'\n"
        "import { werte, auswahl } from",
        1,
    )
    entry = entry.replace(
        "const scenario = new URLSearchParams(location.search).get('scenario')\n",
        "const scenario = new URLSearchParams(location.search).get('scenario')\n"
        "const lang = new URLSearchParams(location.search).get('lang') || 'de'\n"
        "texte.katalog = lang === 'de' ? german : english\ntexte.sprache = lang\n",
        1,
    )
    entry = entry.replace(
        "window.__studio = { werte, auswahl, names }",
        "window.__studio = { werte, auswahl, names, seedlage }\n"
        "window.__title = (lang === 'de' ? german : english).bild.gruppe_masse",
    )
    assert "seedlage }" in entry and "window.__title" in entry
    return entry


@pytest.fixture(scope="module")
def measure():
    program = appfenster._programm() or pytest.skip("no Chrome on this machine")
    folder = FRONTEND / "node_modules" / f".harness-studio-measures-head-{uuid4().hex}"
    folder.mkdir(parents=True)
    try:
        (folder / "Shell.svelte").write_text(SHELL, encoding="utf-8")
        (folder / "entry.js").write_text(_entry(), encoding="utf-8")
        (folder / "vite.config.js").write_text(base.VITE_CONFIG, encoding="utf-8")
        build = subprocess.run(
            [shutil.which("vite", path=str(FRONTEND / "node_modules" / ".bin")), "build", "--config", "vite.config.js"],
            cwd=folder, capture_output=True, text=True, timeout=240,
        )
        assert build.returncode == 0, (build.stdout + build.stderr)[-2000:]
        cases = CASES % {"last": LAST}
        (folder / "measure.html").write_text(base.PAGE % {"cases": cases}, encoding="utf-8")

        def run(width: int, lang: str) -> dict:
            port = base._free_port()
            browser = subprocess.Popen(
                [
                    program, "--headless=new", "--no-first-run", "--disable-background-networking",
                    "--mute-audio", "--allow-file-access-from-files", "--window-size=1440,900",
                    f"--remote-debugging-port={port}",
                    f"--user-data-dir={folder / f'profile-{lang}-{width}'}",
                    (folder / "measure.html").as_uri() + f"?width={width}&lang={lang}",
                ],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True,
            )
            try:
                return asyncio.run(base._drive(port))
            finally:
                prozessstopp.beenden(browser, frist=5)

        yield run
    finally:
        shutil.rmtree(folder, ignore_errors=True)


@pytest.fixture(scope="module", params=[(285, "de"), (285, "en"), (400, "de"), (400, "en")],
                ids=lambda p: f"{p[1]}-{p[0]}")
def report(request, measure) -> dict:
    return measure(*request.param)


def test_the_head_is_one_line_before_and_after_the_first_picture(report):
    for state in ("before", "after"):
        head = report[state]["head"]
        assert head["height"] == 26, (state, report)
        assert report[state]["title"]["height"] <= 22, (state, report)


def test_only_standard_stands_in_the_head_whole_and_inside_the_card(report):
    for state in ("before", "after"):
        buttons = report[state]["buttons"]
        assert [b["text"] for b in buttons] == [
            (GERMAN if report["lang"] == "de" else ENGLISH)["bild"]["standard"],
        ], (state, report)
        assert max(b["right"] for b in buttons) <= report[state]["card"]["right"] + 0.5, (state, report)
        assert not report[state]["title"]["clipped"], (state, report)


def test_the_button_for_the_last_seed_stands_beside_the_dice_at_their_size(report):
    for state in ("before", "after"):
        reuse, dice = report[state]["reuse"], report[state]["dice"]
        assert (reuse["width"], reuse["height"]) == (dice["width"], dice["height"]), (state, report)
        assert abs(reuse["top"] - dice["top"]) < 2 and reuse["right"] <= dice["left"], (state, report)


def test_the_button_is_blocked_until_a_seed_exists_and_its_hint_names_it_then(report):
    assert report["before"]["reuse"]["disabled"] is True, report
    assert str(LAST) not in report["before"]["reuse"]["hint"], report
    assert report["after"]["reuse"]["disabled"] is False, report
    assert str(LAST) in report["after"]["reuse"]["hint"], report


def test_a_press_puts_the_seed_into_the_field_and_holds_it(report):
    assert report["taken"] == {"seed": str(LAST), "mode": "fest"}, report


def test_silence_the_row_of_the_seed_keeps_its_height_when_the_seed_arrives(report):
    assert report["before"]["row"]["height"] == report["after"]["row"]["height"], report
