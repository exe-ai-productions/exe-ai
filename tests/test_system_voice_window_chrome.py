"""The voice field lists the voices of the system, and the fields that act on a
voice model stand locked while one of them is chosen — measured in a real browser.

`Sprachserver.svelte` is built as shipped and drawn in headless Chrome with the
service's answers replaced, the way the block of the voice sample is measured
(tests/test_speech_server_sample_chrome.py, whose page, build and reading of the
result are used here). The report names the voice a machine starts with
(Anna) and two voices of the system; nothing is stored.

Shown: the voice field lists "-", the voice model and the voices of the system
with their language; with nothing stored the voice of the system stands in it;
while a voice of the system is chosen the sample (choice and four buttons), the
language, the five values (field and slider) and the layers and threads of the
voice stand locked and stay visible; choosing a voice model unlocks them again
and stores the choice; an emptied value is "Auto" and is stored as the word; a
value stored as the word is shown empty with its slider at the value the program
takes for itself.

Skipped where there is no Chrome or no node, like the other browser tests.
"""

from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
from uuid import uuid4

import pytest

from app import appfenster, prozessstopp
from tests import test_speech_server_sample_chrome as base

FRONTEND = base.FRONTEND

pytestmark = base.pytestmark


def _stub() -> str:
    stub = base.API_STUB
    for old, new in (
        ("vorlesen: true, keep_model_in_memory: true, conversation_pause_seconds: 3, stimme: '', stimmprobe: '',",
         "vorlesen: true, keep_model_in_memory: true, conversation_pause_seconds: 3, stimme: 'Anna', stimmprobe: '',"),
        ("stimmschichten: 99, stimmfaeden: 0, gespraechsanweisung: 'z', automatik: false, microphone_key: 'Meta+Alt',\n}",
         "stimmschichten: 99, stimmfaeden: 0, gespraechsanweisung: 'z', automatik: false, microphone_key: 'Meta+Alt',\n"
         "  stimmauto: { stimmtemperatur: 0.8, stimmtop_k: 40, stimmtop_p: 0.95, stimmmin_p: 0.05, stimmstrafe: 1.05 },\n}"),
        ("  stimmproben: [...stub.samples], stimmproben_dauer: copy(stub.lengths),\n})",
         "  stimmproben: [...stub.samples], stimmproben_dauer: copy(stub.lengths),\n"
         "  system_voices: [{ name: 'Anna', language: 'de_DE' }, { name: 'Albert', language: 'en_US' }],\n})"),
        ("  settings: { diktat: {} },", "  settings: { diktat: { stimmtop_k: 'auto' } },"),
    ):
        assert old in stub, old[:60]
        stub = stub.replace(old, new, 1)
    return stub


CASES = r"""
const report = {}
const wait = (ms) => new Promise((done) => setTimeout(done, ms))
const stub = window.__stub
const text = (node) => node.textContent.replace(/\s+/g, ' ').trim()
const open = (id) => document.getElementById(id)
const options = () => Array.from(document.querySelectorAll('[role=listbox] [role=option]')).map((o) => text(o))
async function choose(id, label) {
  open(id).click()
  await wait(250)
  const option = Array.from(document.querySelectorAll('[role=listbox] [role=option]')).find((o) => text(o).split(' · ')[0].replace(/^V /, '') === label)
  if (!option) throw new Error('no option ' + label + ' in ' + JSON.stringify(options()))
  option.click()
  await wait(700)
}
const params = () => Array.from(document.querySelectorAll('.parameterblock .regel'))
const locks = () => ({
  sample: open('sp-stimmprobe').disabled,
  buttons: ['sp-probe-aufnehmen', 'sp-probe-abspielen', 'sp-probe-stoppen', 'sp-probe-loeschen'].map((id) => open(id).disabled),
  language: open('sp-stimmsprache').disabled,
  values: params().map((r) => ({ field: r.querySelector('input:not([type=range])').disabled, slider: r.querySelector('input[type=range]').disabled })),
  layersField: document.querySelector('label[for=sps-schichten]').closest('.regel').querySelector('input:not([type=range])').disabled,
  threadsField: document.querySelector('label[for=sps-faeden]').closest('.regel').querySelector('input:not([type=range])').disabled,
  voice: open('sp-stimmemodell').disabled,
})

scene.show = 'sprach'
for (let k = 0; k < 100 && !(open('sp-stimmemodell') && document.querySelector('.probename')); k += 1) await wait(50)
await wait(500)
// The five values stand open.
document.querySelector('.klappzeile').click()
await wait(300)

// 1. Nothing stored for the voice: the voice of the system the machine starts with.
report.start = { voice: text(open('sp-stimmemodell')), locks: locks() }
open('sp-stimmemodell').click()
await wait(250)
report.list = options()
document.body.click()
await wait(250)

// 2. The value stored as the word: an empty field, and the slider rests at what the program takes.
const topK = params()[1]
report.auto = {
  label: text(topK.querySelector('label')),
  field: topK.querySelector('input:not([type=range])').value,
  word: topK.querySelector('.nullwort') ? text(topK.querySelector('.nullwort')) : null,
  slider: topK.querySelector('input[type=range]').value,
}

// 3. A voice model unlocks everything and the choice is stored.
await choose('sp-stimmemodell', 'voice.gguf')
report.model = { voice: text(open('sp-stimmemodell')), locks: locks(), patches: stub.calls.filter((c) => c.name === 'patch').map((c) => c.values) }

// 4. A voice of the system locks it again.
await choose('sp-stimmemodell', 'Albert')
report.albert = { voice: text(open('sp-stimmemodell')), locks: locks(), stored: stub.settings.diktat.stimme }

// 5. The dash is a choice too, and unlocks.
await choose('sp-stimmemodell', '-')
report.dash = { voice: text(open('sp-stimmemodell')), locks: locks(), stored: stub.settings.diktat.stimme }

// 6. An emptied value is "Auto": stored as the word, shown empty.
const temperature = params()[0].querySelector('input:not([type=range])')
temperature.focus()
temperature.value = ''
temperature.dispatchEvent(new Event('input', { bubbles: true }))
temperature.dispatchEvent(new Event('change', { bubbles: true }))
temperature.blur()
await wait(1200)
report.emptied = {
  stored: stub.settings.diktat.stimmtemperatur,
  shown: params()[0].querySelector('input:not([type=range])').value,
  slider: params()[0].querySelector('input[type=range]').value,
}

document.getElementById('ergebnis').textContent = JSON.stringify(report)
"""


@pytest.fixture(scope="module")
def report() -> dict:
    program = appfenster._programm() or pytest.skip("no Chrome on this machine")
    folder = FRONTEND / "node_modules" / f".harness-system-voice-{uuid4().hex}"
    folder.mkdir(parents=True)
    try:
        (folder / "Shell.svelte").write_text(
            base.SHELL % {"sprach": "../../src/teile/Sprachserver.svelte"}, encoding="utf-8"
        )
        (folder / "scene.svelte.js").write_text(base.SCENE_JS, encoding="utf-8")
        (folder / "api_stub.js").write_text(_stub(), encoding="utf-8")
        (folder / "entry.js").write_text(
            base.ENTRY_JS % {"global": "../../src/stil/global.css"}, encoding="utf-8"
        )
        (folder / "vite.config.js").write_text(base.VITE_CONFIG, encoding="utf-8")
        build = subprocess.run(
            [shutil.which("vite", path=str(FRONTEND / "node_modules" / ".bin")), "build", "--config", "vite.config.js"],
            cwd=folder, capture_output=True, text=True, timeout=300,
        )
        assert build.returncode == 0, (build.stdout + build.stderr)[-2500:]
        page = folder / "measure.html"
        page.write_text(base.PAGE % {"cases": CASES}, encoding="utf-8")
        port = base._free_port()
        browser = subprocess.Popen(
            [
                program, "--headless=new", "--disable-gpu", "--no-first-run",
                "--disable-background-networking", "--allow-file-access-from-files",
                "--window-size=1100,1500", f"--remote-debugging-port={port}",
                f"--user-data-dir={folder / 'profile'}", page.as_uri(),
            ],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True,
        )
        try:
            raw = asyncio.run(base._read_result(port))
        finally:
            prozessstopp.beenden(browser, frist=5)
        assert raw, "the page reported nothing"
        result = json.loads(raw)
        assert "failure" not in result, result["failure"]
        return result
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def _all(locks: dict, value: bool) -> bool:
    # Unlocked, only the button to record stands free of any other reason:
    # play, stop and the bin wait for a sample to be chosen.
    buttons = locks["buttons"] if value else locks["buttons"][:1]
    return (
        locks["sample"] is value
        and all(flag is value for flag in buttons)
        and locks["language"] is value
        and all(row["field"] is value and row["slider"] is value for row in locks["values"])
        and locks["layersField"] is value
        and locks["threadsField"] is value
    )


def test_with_nothing_stored_the_voice_the_machine_starts_with_stands_in_the_field_and_locks_the_rest(report):
    assert report["start"]["voice"].startswith("Anna"), report["start"]
    assert _all(report["start"]["locks"], True), report["start"]["locks"]
    # The voice field itself is never locked.
    assert report["start"]["locks"]["voice"] is False


def test_the_list_holds_the_dash_the_voice_model_and_the_voices_of_the_system_with_their_language(report):
    items = report["list"]
    assert items[0] == "-"
    assert "voice.gguf" in items[1]
    assert items[2:] == ["Anna · de_DE", "Albert · en_US"]


def test_a_value_stored_as_the_word_is_an_empty_field_and_its_slider_rests_at_the_value_of_the_program(report):
    auto = report["auto"]
    assert auto["field"] == "" and auto["word"] == "Auto", auto
    assert float(auto["slider"]) == 40.0, auto


def test_a_voice_model_unlocks_the_fields_and_the_choice_is_stored(report):
    assert "voice.gguf" in report["model"]["voice"]
    assert _all(report["model"]["locks"], False), report["model"]["locks"]
    assert {"stimme": "voice.gguf"} in report["model"]["patches"]


def test_a_voice_of_the_system_locks_them_again_and_the_fields_stay_visible(report):
    assert report["albert"]["voice"].startswith("Albert")
    assert _all(report["albert"]["locks"], True), report["albert"]["locks"]
    assert report["albert"]["stored"] == "Albert"


def test_the_dash_is_a_stored_choice_and_unlocks(report):
    assert report["dash"]["voice"] == "-"
    assert report["dash"]["stored"] == ""
    assert _all(report["dash"]["locks"], False), report["dash"]["locks"]


def test_an_emptied_value_is_auto_stored_as_the_word_and_shown_empty(report):
    emptied = report["emptied"]
    assert emptied["stored"] == "auto", emptied
    assert emptied["shown"] == "", emptied
    # The slider of the temperature counts steps of 0.05: 0.8 is the sixteenth.
    assert float(emptied["slider"]) == 16, emptied
