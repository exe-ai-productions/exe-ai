"""Loading is not empty: the document folder and the catalogue wait for their
answer before they say anything.

The document folder said "No files yet." from the moment it opened until its
list came (four seconds on a slow machine), and the catalogue offered
"Download" on a model that lay in the folder until the folder was read — and
for good once that read failed. Now the wall says "Loading …" until the answer
for the open chat and the choices is in, and a card says "download" or
"downloaded" only for a kind whose files were read in full. A read that fails
leaves what was there and says why once.

The real windows, built as they ship, in a real Chrome; every answer of the
service is stood in by the page and comes after three seconds where the test
wants it late. Skipped where there is no Chrome or no node.
"""

from __future__ import annotations

import pytest

from tests.loading_harness import run_page
from tests.test_speech_server_projector_memory import browser

SHELL = "<p></p>"

ENTRY_JS = """import { mount, unmount } from 'svelte'
import DocFolder from '../src/teile/DocFolder.svelte'
import Katalog from '../src/teile/Katalog.svelte'
import { texte } from '../src/lib/texte.svelte.js'
import { zustand } from '../src/lib/zustand.svelte.js'
import { meldungen } from '../src/lib/meldewesen.svelte.js'
import { neuigkeit } from '../src/lib/ereignisstrom.svelte.js'
import { ApiFehler } from '../src/lib/api.js'
import { katalogFuer, passendeFassung } from '../src/lib/modellempfehlungen.js'
import katalog from '../../app/locales/de.json'
import '../src/stil/global.css'

texte.katalog = katalog
window.zustand = zustand
window.meldungen = meldungen
window.neuigkeit = neuigkeit
window.german = katalog
window.ApiFehler = ApiFehler
let current = null
window.showPage = (name) => {
  if (current) unmount(current)
  const root = document.getElementById('root')
  root.innerHTML = ''
  root.style.cssText = 'height: 1000px; display: flex; flex-direction: column;'
  current = mount(name === 'doc' ? DocFolder : Katalog, {
    target: root, props: name === 'doc' ? {} : { offen: true },
  })
}
window.firstCardFile = (art) => {
  const fassung = passendeFassung(katalogFuer(art)[0], 32)
  return fassung.ziel ?? fassung.datei
}
"""

CASES = r"""
const LOADING = window.german.bilder.laedt
const EMPTY = window.german.docfolder.empty
const DOWNLOAD = window.german.katalog.herunterladen
const wallText = () => document.querySelector('.rollen')?.textContent.replace(/\s+/g, ' ').trim() ?? ''
// What the wall says now: whether it is loading, whether it is empty, how many tiles stand.
const wall = () => ({ loading: wallText().includes(LOADING), empty: wallText().includes(EMPTY), text: wallText() })
const tiles = () => document.querySelectorAll('.rollen .kachel').length
const file = (n) => ({ source: 'chat', id: String(n), name: n + '.png', path: 'x/' + n + '.png', origin: '' })

window.answers = {
  speicherorteLesen: [],
  runnerAuskunft: { speicher_gb: 32, modelle: [], mmproj: [], mtp: [] },
  modellHolenStand: null,
}

// --- The document folder ---------------------------------------------------
window.zustand.aktiverChat = 'c1'
window.answers.docFolder = later(3000, [])
window.showPage('doc')
await wait(900)
report.docWaiting = { ...wall(), tiles: tiles() }
await until(() => wall().empty, 'the empty answer')
report.docEmpty = wall()

window.answers.docFolder = later(1500, [file(1), file(2)])
window.zustand.aktiverChat = 'c2'
await wait(600)
report.docSwitched = { ...wall(), tiles: tiles() }
await until(() => tiles() === 2, 'two tiles')

// The other chat: loading again, and none of the first one's tiles stay.
window.answers.docFolder = later(2500, [])
window.zustand.aktiverChat = 'c3'
await wait(600)
report.docOtherChat = { ...wall(), tiles: tiles() }
await until(() => wall().empty, 'the empty answer of the third chat')

// A quiet question (the live line says the jobs changed) leaves the wall standing.
window.answers.docFolder = later(1500, [file(1), file(2)])
window.zustand.aktiverChat = 'c2'
await until(() => tiles() === 2, 'two tiles again')
window.answers.docFolder = later(2000, [file(1), file(2), file(3)])
window.neuigkeit.auftraege += 1
await wait(800)
report.docQuiet = { ...wall(), tiles: tiles() }
await until(() => tiles() === 3, 'three tiles')

// A refused question: the red notice, and no sentence on the wall.
window.answers.docFolder = refused(300, 'Folder refused')
window.zustand.aktiverChat = 'c4'
await wait(1500)
report.docRefused = { ...wall(), tiles: tiles(), notices: noticesOf('Folder refused') }

// --- The catalogue ---------------------------------------------------------
const FILE = window.firstCardFile('sprache')
const catalogue = () => ({
  buttons: document.querySelectorAll('.karte .slot .sign-button[aria-label="' + DOWNLOAD + '"]').length,
  ticks: document.querySelectorAll('.karte .slot .done').length,
  cards: document.querySelectorAll('.karte').length,
  height: Math.round(document.querySelector('.karte')?.getBoundingClientRect().height ?? 0),
})
window.answers.spracheAuskunft = later(3000, { modelle: [{ name: FILE }], mmproj: [] })
window.showPage('katalog')
window.zustand.katalogArtWunsch = 'sprache'
await wait(1200)
report.catWaiting = catalogue()
await until(() => catalogue().ticks === 1, 'the tick of the model that lies there', 15000)
report.catAnswered = catalogue()

// To another kind and back: the read of the speech folder is asked again,
// and until it is in, neither a button nor a tick stands.
window.zustand.katalogArtWunsch = 'chat'
await wait(600)
window.zustand.katalogArtWunsch = 'sprache'
await wait(900)
report.catBack = catalogue()
await until(() => catalogue().ticks === 1, 'the tick again', 15000)

// A read that fails after a good one: the tick stays, the notice comes once.
window.answers.spracheAuskunft = refused(200, 'Speech read failed')
await wait(7500)
report.catFailedLater = { ...catalogue(), notices: noticesOf('Speech read failed') }

// The first read fails: nothing was ever read, so no button invites a download.
window.answers.spracheAuskunft = refused(200, 'First read failed')
window.showPage('katalog')
window.zustand.katalogArtWunsch = 'sprache'
await wait(4500)
report.catFirstFailed = { ...catalogue(), notices: noticesOf('First read failed') }

document.getElementById('ergebnis').textContent = JSON.stringify(report)
"""


@pytest.fixture(scope="module")
def report() -> dict:
    return run_page(SHELL, ENTRY_JS, CASES)


@browser
def test_the_windows_ran_without_a_script_error(report):
    assert report["errors"] == []


@browser
def test_the_wall_says_loading_until_the_answer_is_in_and_empty_only_after(report):
    waiting, empty = report["docWaiting"], report["docEmpty"]
    assert waiting["loading"] and not waiting["empty"] and waiting["tiles"] == 0
    assert empty["empty"] and not empty["loading"]


@browser
def test_after_a_change_of_chat_the_tiles_of_the_one_before_do_not_stand(report):
    assert report["docSwitched"]["loading"] and report["docSwitched"]["tiles"] == 0
    assert report["docOtherChat"]["loading"] and report["docOtherChat"]["tiles"] == 0


@browser
def test_silence_a_quiet_question_leaves_the_wall_standing(report):
    assert report["docQuiet"]["tiles"] == 2 and not report["docQuiet"]["loading"]


@browser
def test_a_refused_question_gives_the_notice_and_no_sentence_on_the_wall(report):
    refused = report["docRefused"]
    assert refused["notices"] == 1 and refused["tiles"] == 0
    assert not refused["loading"] and not refused["empty"]


@browser
def test_a_card_offers_no_download_and_shows_no_tick_before_the_folder_is_read(report):
    waiting, answered = report["catWaiting"], report["catAnswered"]
    assert waiting["cards"] > 1 and waiting["buttons"] == 0 and waiting["ticks"] == 0
    # The card keeps its size, and afterwards the model that lies there shows its tick.
    assert waiting["height"] == answered["height"]
    assert answered["ticks"] == 1 and answered["buttons"] == answered["cards"] - 1


@browser
def test_after_a_change_of_kind_the_cards_wait_for_the_read_of_that_kind(report):
    back = report["catBack"]
    assert back["buttons"] == 0 and back["ticks"] == 0


@browser
def test_a_read_that_fails_later_keeps_the_tick_and_says_why_once(report):
    failed = report["catFailedLater"]
    assert failed["ticks"] == 1 and failed["notices"] == 1


@browser
def test_a_first_read_that_fails_shows_no_download_button(report):
    first = report["catFirstFailed"]
    assert first["buttons"] == 0 and first["ticks"] == 0 and first["notices"] == 1
