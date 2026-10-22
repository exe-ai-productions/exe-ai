"""A read that fails leaves the page of a server standing and says why.

The cleanup, speech, embedding and picture server pages read their server
now and then. When a read failed they threw their last answer away: a server
that ran showed as stopped, with an empty model choice and a locked button,
and not a word said why. The page now keeps its last answer — head with stop
or start, dot and port, the chosen model — and the reason stands once as a
red notice for as long as the same failure lasts, like on the pages of the
model and the agent server. A read that gets through clears it, so the next
failure is news again.

The real pages, built as they ship, in a real Chrome; the answers of the
service are stood in by the page (what is faked: every answer of every call).
Skipped where there is no Chrome or no node.
"""

from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
from uuid import uuid4

import pytest

from app import appfenster, prozessstopp
from tests.test_speech_server_projector_memory import (
    FRONTEND,
    PAGE,
    SHELL,
    VITE_CONFIG,
    _free_port,
    _read_result,
    browser,
)

ENTRY_JS = """import { mount } from 'svelte'
import Shell from './Shell.svelte'
import { texte } from '../src/lib/texte.svelte.js'
import { zustand } from '../src/lib/zustand.svelte.js'
import { meldungen } from '../src/lib/meldewesen.svelte.js'
import { neuigkeit } from '../src/lib/ereignisstrom.svelte.js'
import { ApiFehler } from '../src/lib/api.js'
import katalog from '../../app/locales/de.json'
import '../src/stil/global.css'

texte.katalog = katalog
window.zustand = zustand
window.meldungen = meldungen
window.neuigkeit = neuigkeit
window.ApiFehler = ApiFehler
mount(Shell, { target: document.getElementById('root') })
"""

# Every call answers with what `window.answers` holds under its name: a
# function is called (and may throw), anything else is handed back as it is.
API_STUB = """export const setSessionKey = () => {}
export const sitzungNeuLaden = () => {}
export const spracheMerken = () => {}
export const rememberStatusText = () => {}
export const bootMessage = (failure) => String(failure)
export const allPages = async () => []
export async function* antwortStrom() {}
export async function* zusehenStrom() {}
export class ApiFehler extends Error {}
export const api = new Proxy({}, {
  get: (_, name) => async (...args) => {
    ;(window.calls ||= []).push(name)
    const answer = (window.answers || {})[name]
    if (typeof answer === 'function') return answer(...args)
    return JSON.parse(JSON.stringify(answer === undefined ? {} : answer))
  },
})
"""

CASES = r"""
const report = { errors: [] }
window.addEventListener('error', (event) => report.errors.push(String(event.message)))
window.addEventListener('unhandledrejection', (event) => report.errors.push(String(event.reason && event.reason.message || event.reason)))
const wait = (ms) => new Promise((done) => setTimeout(done, ms))
const until = async (test, what, limit = 20000) => {
  const end = Date.now() + limit
  while (Date.now() < end) {
    try { if (test()) return true } catch (_) {}
    await wait(150)
  }
  throw new Error('timed out waiting for ' + what)
}

// Every notice that ever stood, by its number: a notice outlives the failure
// that made it, and the list holds three at most, so it is read all the time.
const seen = new Map()
setInterval(() => { for (const notice of window.meldungen.liste) seen.set(notice.id, notice.text) }, 40)
const noticesOf = (sentence) => [...seen.values()].filter((text) => text === sentence).length

const file = (name) => ({ name, groesse_gb: 1.2 })
const machine = { speicher_gb: 32, kerne: 8, vorgaben: { kontext: 4096, schichten: null, port: 8080, vorladen: false }, zuordnung: {}, mtp: [], modelle: [file('chat.gguf')], projector_size_gb: {} }
const running = (name, port) => ({ ...machine, laeuft: true, port, modell: name, modelle: [file(name)], programm: true, mmproj: [], projektoren: {} })
const fail = (sentence) => async () => { throw new window.ApiFehler(sentence) }
window.answers = {
  runnerAuskunft: { ...machine, laeuft: false, port: null, programm: true },
  einbettungAuskunft: { ...machine, laeuft: false, port: null, modelle: [], programm: true },
  agentenmodellAuskunft: { ...machine, laeuft: false, port: null, programm: true },
  spracheAuskunft: running('ear.gguf', 8084),
  bereinigungAuskunft: running('tidy.gguf', 8085),
  turboStand: { zustand: 'bereit', port: 8097, programm_da: true, picture_running: true },
  speicherBlick: { wired_gb: 10, wired_limit_gb: 20, gesamt_gb: 32 },
  einstellungAufgeloest: { wert: null },
  modelle: [], modelleAlle: [], serverUebersicht: [], oauthStatus: [],
  bildmodelle: { modelle: [], families: {}, programm_da: true, standardmodell: '' },
  bildProgrammStand: {},
  bildProgrammVarianten: { varianten: [] },
  bildFamilien: [],
  bildAufbereitung: { verbesserer: 'agent', anweisungen: { sdxl: '' } },
  imageDevices: [], imageModelFiles: [], imageFamilies: {},
  runnerProtokoll: [], einbettungProtokoll: [], spracheProtokoll: [], bereinigungProtokoll: [],
  agentenmodellProtokoll: [], bildProtokoll: [],
  speicherorteLesen: [],
}

const titles = { server: 'Modell-Server', sprache: 'Sprach-Server', bereinigung: 'Bereinigungs-Server', einbettung: 'Einbettungs-Server', bild: 'Bild-Server' }
const show = async (name) => {
  window.zustand.lokalWunsch = name
  await until(() => document.querySelector('header.kopf .titel')?.textContent.trim() === titles[name], name + ' page')
  await wait(700)
}
// What the head and the page say now: the button's word, and whether the model stands.
const look = (model) => ({
  stop: (document.querySelector('header.kopf')?.textContent ?? '').includes('Stopp'),
  model: document.body.textContent.includes(model),
})

// The cleanup and the speech server: a good answer, then a failing read for
// 7 s (two polls), a good one, a failing one again.
const polled = async (key, name, model, model_name) => {
  const sentence = 'Read failed on ' + key
  window.answers[name] = running(model, 8090)
  await show(key)
  const outcome = { before: look(model), noticesBefore: [...seen.values()] }
  window.answers[name] = fail(sentence)
  await wait(7000)
  outcome.during = { ...look(model), notices: noticesOf(sentence) }
  window.answers[name] = running(model, 8090)
  await wait(3500)
  window.answers[name] = fail(sentence)
  await wait(3500)
  outcome.again = noticesOf(sentence)
  window.answers[name] = running(model, 8090)
  return outcome
}
report.cleanup = await polled('bereinigung', 'bereinigungAuskunft', 'tidy.gguf')
report.speech = await polled('sprache', 'spracheAuskunft', 'ear.gguf')

// The first read fails: nothing to keep, the page stays without values and
// says why once.
{
  const sentence = 'First read failed'
  window.answers.spracheAuskunft = fail(sentence)
  await show('server')
  await show('sprache')
  await wait(3600)
  report.first = { stop: look('ear.gguf').stop, notices: noticesOf(sentence) }
  window.answers.spracheAuskunft = running('ear.gguf', 8084)
}

// The embedding server reads when its server announces itself: good at
// opening, then the announcement and a failing read, again with the same
// sentence, then a good read and a failing one.
{
  const sentence = 'Embedding read failed'
  window.answers.einbettungAuskunft = running('embed.gguf', 8081)
  await show('einbettung')
  const before = look('embed.gguf')
  const bump = async () => { window.neuigkeit.einbettung += 1; await wait(1200) }
  window.answers.einbettungAuskunft = fail(sentence)
  await bump()
  const during = { ...look('embed.gguf'), notices: noticesOf(sentence) }
  await bump()
  const same = noticesOf(sentence)
  window.answers.einbettungAuskunft = running('embed.gguf', 8081)
  await bump()
  window.answers.einbettungAuskunft = fail(sentence)
  await bump()
  report.embedding = { before, during, same, again: noticesOf(sentence) }
}

// The picture server: one of its reads fails and the head stays; then both
// reads fail with the same sentence and it is said once.
{
  const sentence = 'Picture server read failed'
  await show('bild')
  const before = look('')
  window.answers.turboStand = fail(sentence)
  await wait(7000)
  const during = { stop: look('').stop, notices: noticesOf(sentence) }
  window.answers.turboStand = { zustand: 'bereit', port: 8097, programm_da: true, picture_running: true }
  await wait(3500)
  const second = 'Both picture reads failed'
  window.answers.turboStand = fail(second)
  window.answers.bildmodelle = fail(second)
  await show('server')
  await show('bild')
  await wait(7000)
  report.picture = { before, during, both: noticesOf(second) }
}

// Silence: good answers bring no notice (the first ones above, before any failure).
report.strayBeforeFailures = report.cleanup.noticesBefore

document.getElementById('ergebnis').textContent = JSON.stringify(report)
"""


@pytest.fixture(scope="module")
def report() -> dict:
    program = appfenster._programm() or pytest.skip("no Chrome on this machine")
    folder = FRONTEND / f".harness-readfailure-{uuid4().hex}"
    folder.mkdir(parents=True)
    try:
        (folder / "Shell.svelte").write_text(SHELL, encoding="utf-8")
        (folder / "api_stub.js").write_text(API_STUB, encoding="utf-8")
        (folder / "entry.js").write_text(ENTRY_JS, encoding="utf-8")
        (folder / "vite.config.js").write_text(VITE_CONFIG, encoding="utf-8")
        build = subprocess.run(
            [shutil.which("vite", path=str(FRONTEND / "node_modules" / ".bin")), "build", "--config", "vite.config.js"],
            cwd=folder, capture_output=True, text=True, timeout=300,
        )
        assert build.returncode == 0, (build.stdout + build.stderr)[-2500:]
        page = folder / "measure.html"
        page.write_text(PAGE % {"cases": CASES}, encoding="utf-8")
        port = _free_port()
        chrome = subprocess.Popen(
            [
                program, "--headless=new", "--disable-gpu", "--no-first-run",
                "--disable-background-networking", "--allow-file-access-from-files",
                "--window-size=1920,1080", f"--remote-debugging-port={port}",
                f"--user-data-dir={folder / 'profile'}", page.as_uri(),
            ],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True,
        )
        try:
            raw = asyncio.run(_read_result(port, limit=300.0))
        finally:
            prozessstopp.beenden(chrome, frist=5)
        assert raw, "the page reported nothing"
        result = json.loads(raw)
        assert "failure" not in result, result["failure"]
        return result
    finally:
        shutil.rmtree(folder, ignore_errors=True)


@browser
def test_the_page_ran_without_a_script_error(report):
    assert report["errors"] == []


@browser
@pytest.mark.parametrize("which", ["cleanup", "speech"])
def test_a_failed_read_leaves_the_head_and_the_model_and_says_it_once(report, which):
    outcome = report[which]
    assert outcome["before"] == {"stop": True, "model": True}
    # Two reads failed in those seconds: the head still offers to stop the
    # server, the model still stands, and the reason is on the screen once.
    assert outcome["during"] == {"stop": True, "model": True, "notices": 1}
    # A good read between, and the same failure again: news a second time.
    assert outcome["again"] == 2


@browser
def test_a_first_read_that_fails_says_why_once_and_shows_no_server(report):
    assert report["first"] == {"stop": False, "notices": 1}


@browser
def test_the_embedding_page_keeps_its_answer_when_the_announced_read_fails(report):
    outcome = report["embedding"]
    assert outcome["before"] == {"stop": True, "model": True}
    assert outcome["during"] == {"stop": True, "model": True, "notices": 1}
    assert outcome["same"] == 1
    assert outcome["again"] == 2


@browser
def test_the_picture_page_keeps_its_head_and_two_failing_reads_say_it_once(report):
    outcome = report["picture"]
    assert outcome["before"]["stop"] is True
    assert outcome["during"] == {"stop": True, "notices": 1}
    assert outcome["both"] == 1


@browser
def test_silence_good_answers_bring_no_notice(report):
    assert report["strayBeforeFailures"] == []
