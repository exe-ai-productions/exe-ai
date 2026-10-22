"""The update card at the start and the version row of the settings
(`frontend/src/teile/Updatekarte.svelte`, `Updatezeile.svelte`), the state
behind them (`frontend/src/lib/updates.svelte.js`) and the notes of a release
made safe to set (`frontend/src/lib/releaseNotes.js`).

The two modules are run in node, against a stand-in for the shell's bridge:
what is asserted is what the real code answers. The parts are read as source.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

WURZEL = Path(__file__).resolve().parent.parent
LIB = WURZEL / "frontend" / "src" / "lib"
PARTS = WURZEL / "frontend" / "src" / "teile"
CARD = PARTS / "Updatekarte.svelte"
ROW = PARTS / "Updatezeile.svelte"

needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="no node on this machine")


def _run(source: str, script: str):
    # One time zone for every machine: a release's day is read in it.
    run = subprocess.run(
        ["node", "-e", f"{source}\n{script}"], capture_output=True, text=True, env={**os.environ, "TZ": "UTC"}
    )
    assert run.returncode == 0, run.stderr
    return json.loads(run.stdout)


def _notes(html: str) -> str:
    source = re.sub(r"^export ", "", (LIB / "releaseNotes.js").read_text(encoding="utf-8"), flags=re.M)
    return _run(source, f"console.log(JSON.stringify(releaseNotesHtml({json.dumps(html)})))")


# A stand-in for the shell: it counts every request, answers each with the
# state it holds, and `tell` is the shell telling a change of its own.
_SHELL = """
const calls = { status: 0, check: 0, download: 0, install: 0 }
let held = { version: '0.6.9', found: '', notes: '', date: '', state: 'none', progress: null, reason: '' }
let listener = null
const tell = (next) => { held = { ...held, ...next }; listener?.(held) }
const shell = {
  status: async () => { calls.status += 1; return held },
  check: async () => { calls.check += 1; return held },
  download: async () => { calls.download += 1; return held },
  install: async () => { calls.install += 1; return held },
  on: (callback) => { listener = callback },
}
"""


def _state(script: str, *, shell: bool = True):
    """Runs the state module with or without a shell behind the page; the
    rune that makes the state live in the page is a plain object here."""
    source = (LIB / "updates.svelte.js").read_text(encoding="utf-8")
    source = re.sub(r"^export ", "", source, flags=re.M).replace("$state(", "(")
    page = "globalThis.window = { exeHuelle: { updates: shell } }" if shell else "globalThis.window = {}"
    return _run(f"{_SHELL}\n{page}\n{source}", f"(async () => {{ {script} }})()")


@needs_node
def test_the_card_stands_only_while_a_newer_version_is_offered():
    shown = _state(
        """
        updatesStart(); await null; await null
        const out = {}
        for (const state of ['none', 'checking', 'available', 'downloading', 'downloaded', 'error']) {
          tell({ state, found: '0.7.0' })
          out[state] = cardShown()
        }
        console.log(JSON.stringify(out))
        """
    )
    assert shown == {
        "none": False, "checking": False, "available": True,
        "downloading": True, "downloaded": True, "error": False,
    }


@needs_node
def test_without_the_shell_there_is_no_card_and_no_row():
    answer = _state(
        """
        updatesStart(); await null
        updates.state = 'available'
        await checkForUpdates(); await downloadUpdate()
        console.log(JSON.stringify({ present: updates.present, card: cardShown(), calls }))
        """,
        shell=False,
    )
    assert answer == {"present": False, "card": False, "calls": {"status": 0, "check": 0, "download": 0, "install": 0}}
    # The row of the settings is drawn only where the shell is.
    row = ROW.read_text(encoding="utf-8")
    assert row.count("{#if updates.present && updates.version}") == 1
    assert row.index("{#if updates.present && updates.version}") < row.index('<div class="updates"')


@needs_node
def test_fetching_asks_the_shell_and_installing_only_once_the_version_lies_ready():
    steps = _state(
        """
        updatesStart(); await null; await null
        tell({ state: 'available', found: '0.7.0' })
        await installUpdate()
        const early = { ...calls }
        await downloadUpdate()
        tell({ state: 'downloading', progress: { percent: 40.4 } })
        await installUpdate()
        const fetching = { ...calls, percent: updates.percent }
        tell({ state: 'downloaded', progress: null })
        await installUpdate()
        console.log(JSON.stringify({ early, fetching, ready: calls }))
        """
    )
    assert steps["early"] == {"status": 1, "check": 0, "download": 0, "install": 0}
    assert steps["fetching"] == {"status": 1, "check": 0, "download": 1, "install": 0, "percent": 40}
    assert steps["ready"] == {"status": 1, "check": 0, "download": 1, "install": 1}


@needs_node
def test_later_closes_the_card_without_a_word_to_the_shell():
    answer = _state(
        """
        updatesStart(); await null; await null
        tell({ state: 'available', found: '0.7.0' })
        const before = cardShown()
        chooseLater()
        tell({ state: 'available', found: '0.7.0' })
        console.log(JSON.stringify({ before, after: cardShown(), calls }))
        """
    )
    assert answer == {
        "before": True, "after": False,
        "calls": {"status": 1, "check": 0, "download": 0, "install": 0},
    }


@needs_node
def test_up_to_date_is_said_only_after_a_look_and_a_lost_request_is_a_failure():
    answer = _state(
        """
        updatesStart(); await null; await null
        const unknown = updates.looked
        tell({ state: 'checking' }); tell({ state: 'none' })
        const looked = updates.looked
        shell.check = async () => { throw new Error('no answer') }
        await checkForUpdates()
        console.log(JSON.stringify({ unknown, looked, state: updates.state, reason: updates.reason }))
        """
    )
    assert answer == {"unknown": False, "looked": True, "state": "error", "reason": "no answer"}
    row = ROW.read_text(encoding="utf-8")
    assert "{:else if updates.state === 'none' && updates.looked}" in row


@needs_node
def test_the_release_s_date_is_written_in_the_language_asked_for():
    dates = _state(
        """
        updatesStart(); await null; await null
        tell({ state: 'available', date: '2026-10-09T10:00:00.000Z' })
        const read = [releaseDate('de-DE'), releaseDate('en-GB')]
        tell({ date: 'no date' }); read.push(releaseDate('de-DE'))
        tell({ date: '' }); read.push(releaseDate('de-DE'))
        console.log(JSON.stringify(read))
        """
    )
    assert dates == ["9. Oktober 2026", "9 October 2026", "", ""]
    # Without a date the card names the version alone.
    card = CARD.read_text(encoding="utf-8")
    assert "? t('updates.version_line', { version: updates.found, date })" in card
    assert ": t('updates.version', { version: updates.found })}" in card


@needs_node
def test_the_notes_keep_their_formatting_and_lose_scripts_pictures_and_addresses():
    notes = _notes(
        '<h2 class="x" onclick="alert(1)">What\'s new</h2><!-- hidden -->\n'
        '<ul><li>Faster <strong>start</strong> by <a href="https://example.org/u">someone</a></li>'
        '<li><img src="x" onerror="alert(2)">A picture went</li></ul>'
        "<script>alert(3)</script><style>p{color:red}</style>"
        '<p>1 < 2 &amp; <em>done</em><br/></p><iframe src="//example.org"></iframe>'
        "<scr<script>ipt>alert(4)</script>"
    )
    assert notes == (
        "<h2>What's new</h2>\n"
        "<ul><li>Faster <strong>start</strong> by someone</li>"
        "<li>A picture went</li></ul>"
        "<p>1 &lt; 2 &amp; <em>done</em><br></p>"
        "ipt&gt;alert(4)"
    )
    for trace in ("<script", "<img", "<a", "<iframe", "<style", "href", "onerror", "onclick", "class=", "alert(3)"):
        assert trace not in notes, trace
    # A tag that never closes takes the rest with it rather than letting it through.
    assert _notes("<p>kept</p><script>alert(5)") == "<p>kept</p>"
    # A ">" inside a quoted value does not end its tag; a quote that never
    # closes leaves no tag at all, only text.
    assert _notes('<p title="a>b" data-x=\'c>d\'>Text</p>') == "<p>Text</p>"
    assert _notes('<img alt="a>b" onerror="alert(6)">gone') == "gone"
    assert _notes('<p title="open>Text</p>') == '&lt;p title="open&gt;Text</p>'


@needs_node
def test_silence_probe_plain_notes_and_no_notes_pass_as_they_are():
    assert _notes("Bug fixes &amp; small things.") == "Bug fixes &amp; small things."
    assert _notes("") == ""
    assert _notes("<p>One</p>\n<ol><li>Two</li></ol>") == "<p>One</p>\n<ol><li>Two</li></ol>"


def test_the_card_sets_the_notes_only_through_the_one_door_and_its_buttons_only_ask():
    card = CARD.read_text(encoding="utf-8")
    assert "const notes = $derived(releaseNotesHtml(updates.notes))" in card
    assert card.count("{@html") == 1 and "{@html notes}" in card
    # It waits for the first-start window — and for the answer whether one is due.
    assert "const wanted = $derived(cardShown() && begruessung.geladen && !erststartNoetig())" in card
    # A download that fails says so, in the words of the settings row.
    # A step that fails says so, in the words of the settings row; "Later" says nothing.
    assert "if (stood && !stands && updates.state === 'error') {" in card
    assert "meldeText(failedKey(), { reason: updates.reason }, 'fehler')" in card
    assert "const stands = cardShown()" in card and "stood = stands" in card
    assert "onclick={chooseLater}>{t('updates.later')}" in card
    assert "onclick={downloadUpdate}>{t('updates.download')}" in card
    assert "onclick={installUpdate}>{t('updates.install')}" in card
    # The install button stands only once the version lies ready.
    assert card.index("{#if updates.state === 'downloaded'}") < card.index("onclick={installUpdate}")
    assert card.index("onclick={installUpdate}") < card.index("{:else if updates.state === 'downloading'}")
    assert "t('updates.downloading', { percent: updates.percent })" in card
    page = (WURZEL / "frontend" / "src" / "App.svelte").read_text(encoding="utf-8")
    assert "<Updatekarte />" in page and "  updatesStart()\n" in page
    # The silence probe: the first-start window is its own part, as before.
    first = (PARTS / "Erststart.svelte").read_text(encoding="utf-8")
    assert "updates" not in first and "<Erststart bind:modus />" in page


def test_the_row_of_the_settings_asks_by_hand_and_says_what_came_of_it():
    row = ROW.read_text(encoding="utf-8")
    assert "t('updates.version', { version: updates.version })" in row
    assert "onclick={look} disabled={updates.state === 'checking'}" in row
    assert "onclick={downloadUpdate}>{t('updates.download')}" in row
    assert "onclick={installUpdate}>{t('updates.install')}" in row
    # What a look brings is rolled into sight at the foot of the list.
    assert "await checkForUpdates()\n    await tick()\n    part?.scrollIntoView({ block: 'end' })" in row
    assert "t('updates.found', { version: updates.found })" in row
    assert "t(failedKey(), { reason: updates.reason })" in row
    assert "t('updates.current')" in row
    # The settings list has no block of its own under it any more: the row
    # "Updates" shows the answer at its right end (the phone keeps this part).
    nav = (PARTS / "SettingsNav.svelte").read_text(encoding="utf-8")
    assert "Updatezeile" not in nav
    assert "<Updatezeile" not in (PARTS / "SystemPrompt.svelte").read_text(encoding="utf-8")
    assert "<Updatezeile />" in (WURZEL / "frontend" / "src" / "phone" / "pages" / "Settings.svelte").read_text(encoding="utf-8")
    # The look belongs to the button of the row alone; nothing reaches it from outside any more.
    assert "  async function look()" in row and "export async function look()" not in row


ROW_OF_LIST = '''
const texts = {
  'updates.store': 'STORE', 'updates.found': 'FOUND {version}', 'updates.download': 'DOWNLOAD',
  'updates.install': 'INSTALL', 'updates.downloading': 'FETCHING {percent}', 'updates.current': 'CURRENT',
  'updates.failed': 'FAILED {reason}',
}
const t = (key, p = {}) => (texts[key] ?? key).replace(/\\{(\\w+)\\}/g, (_, k) => p[k])
'''


def _row_of_the_list(script: str):
    """``updatesRowShow`` run against the real state module and a stand-in for
    the texts (each key says itself)."""
    state = re.sub(r"^export ", "", (LIB / "updates.svelte.js").read_text(encoding="utf-8"), flags=re.M).replace("$state(", "(")
    row = re.sub(r"^import .*$", "", (LIB / "updatesRow.js").read_text(encoding="utf-8"), flags=re.M)
    row = re.sub(r"^export ", "", row, flags=re.M)
    return _run(f"{_SHELL}\n{ROW_OF_LIST}\nglobalThis.window = {{ exeHuelle: {{ updates: shell }} }}\n{state}\n{row}", f"(async () => {{ {script} }})()")


@needs_node
def test_the_row_of_the_list_shows_the_version_at_rest_and_the_answer_after_a_look():
    shown = _row_of_the_list(
        """
        updatesStart(); await null; await null
        const out = { rest: updatesRowShow() }
        tell({ state: 'checking' }); out.checking = updatesRowShow()
        tell({ state: 'none' }); out.current = updatesRowShow()
        tell({ state: 'available', found: '0.7.0' }); out.available = updatesRowShow()
        tell({ state: 'downloading', progress: { percent: 40 } }); out.downloading = updatesRowShow()
        tell({ state: 'downloaded', progress: null }); out.downloaded = updatesRowShow()
        tell({ state: 'error', step: 'download', reason: 'offline' }); out.failed = updatesRowShow()
        tell({ state: 'store' }); out.store = updatesRowShow()
        console.log(JSON.stringify(out))
        """
    )
    assert shown["rest"] == {"text": "0.6.9", "art": "", "tat": ""}
    assert shown["checking"] == {"text": "0.6.9", "art": "", "tat": ""}
    assert shown["current"] == {"text": "CURRENT", "art": "done", "tat": ""}
    assert shown["available"] == {"text": "FOUND 0.7.0", "art": "", "tat": "DOWNLOAD"}
    assert shown["downloading"] == {"text": "FETCHING 40", "art": "running", "tat": ""}
    assert shown["downloaded"] == {"text": "FOUND 0.7.0", "art": "", "tat": "INSTALL"}
    assert shown["failed"] == {"text": "updates.failed_download", "art": "failed", "tat": ""}
    assert shown["store"] == {"text": "STORE", "art": "done", "tat": ""}


@needs_node
def test_a_click_on_the_row_takes_the_next_step_and_never_two_at_once():
    source = (LIB / "settingsrow.js").read_text(encoding="utf-8")
    body = source.split("export function chooseRow", 1)[1]
    script = """
const calls = []
const updates = { state: 'none' }
const downloadUpdate = () => calls.push('download')
const installUpdate = () => calls.push('install')
const zustand = {}, seiteZeigen = () => {}, handbuchOeffnen = () => {}, openSettingsPage = () => {}
function chooseRow""" + body + """
const row = { ziel: { update: true } }
const out = {}
for (const state of ['none', 'error', 'available', 'downloaded', 'downloading', 'checking', 'store']) {
  updates.state = state
  calls.length = 0
  chooseRow(row, { look: () => calls.push('look') })
  out[state] = [...calls]
}
console.log(JSON.stringify(out))
"""
    run = subprocess.run(["node", "-e", script], capture_output=True, text=True)
    assert run.returncode == 0, run.stderr
    assert json.loads(run.stdout) == {
        "none": ["look"], "error": ["look"], "available": ["download"], "downloaded": ["install"],
        "downloading": [], "checking": [], "store": [],
    }


def test_every_text_stands_word_for_word_in_both_languages():
    texts = {
        language: json.loads((WURZEL / "app" / "locales" / f"{language}.json").read_text(encoding="utf-8"))["updates"]
        for language in ("de", "en")
    }
    assert texts["de"] == {
        "title": "Neue Version verfügbar",
        "version_line": "Version {version}, veröffentlicht am {date}",
        "download": "Download",
        "downloading": "Download … {percent} %",
        "install": "Installieren",
        "later": "Später",
        "version": "Version {version}",
        "check": "Nach Updates suchen",
        "current": "Die App ist aktuell.",
        "found": "Neue Version {version} verfügbar.",
        "failed": "Prüfen nicht möglich: {reason}",
        "failed_download": "Download nicht möglich: {reason}",
        "failed_install": "Installieren nicht möglich: {reason}",
        "store": "Updates kommen aus dem Microsoft Store.",
    }
    assert texts["en"] == {
        "title": "New version available",
        "version_line": "Version {version}, released {date}",
        "download": "Download",
        "downloading": "Downloading … {percent} %",
        "install": "Install",
        "later": "Later",
        "version": "Version {version}",
        "check": "Check for updates",
        "current": "The app is up to date.",
        "found": "New version {version} available.",
        "failed": "Could not check: {reason}",
        "failed_download": "Could not download: {reason}",
        "failed_install": "Could not install: {reason}",
        "store": "Updates come from the Microsoft Store.",
    }


def test_each_step_that_fails_has_its_own_sentence_and_a_look_keeps_the_old_one():
    """The shell names the step that failed; the page picks the sentence by
    it, in the row and in the card's notice alike. A failure that names no
    step is a look, as before."""
    source = (LIB / "updates.svelte.js").read_text(encoding="utf-8")
    assert "const STEPS = ['check', 'download', 'install']" in source
    assert "updates.step = STEPS.includes(status.step) ? status.step : 'check'" in source
    key = re.search(r"export function failedKey\(\) \{\n(.*?)\n\}", source, re.S)
    assert key, "failedKey not found"
    body = key.group(1)
    assert "updates.step === 'download'" in body and "'updates.failed_download'" in body
    assert "updates.step === 'install'" in body and "'updates.failed_install'" in body
    assert body.rstrip().endswith("return 'updates.failed'")
    # A request that does not come back at all is told with the step it was.
    assert "updates.step = STEPS.includes(name) ? name : 'check'" in source


@needs_node
def test_the_page_picks_the_sentence_by_the_step_the_shell_names():
    """A failed look keeps its sentence, a failed download and a failed
    installation take their own; a failure that names no step, or one the
    page does not know, is a look. A request that does not come back at all
    is told with the step of the request."""
    answer = _state(
        """
        updatesStart(); await null; await null
        const out = {}
        for (const step of ['check', 'download', 'install', undefined, 'unpack']) {
          tell({ state: 'error', reason: 'x', step })
          out[String(step)] = failedKey()
        }
        shell.download = async () => { throw new Error('gone') }
        tell({ state: 'available', found: '0.7.0', step: 'check' })
        await downloadUpdate()
        out.rejected = [updates.state, failedKey(), updates.reason]
        console.log(JSON.stringify(out))
        """
    )
    assert answer == {
        "check": "updates.failed",
        "download": "updates.failed_download",
        "install": "updates.failed_install",
        "undefined": "updates.failed",
        "unpack": "updates.failed",
        "rejected": ["error", "updates.failed_download", "gone"],
    }
