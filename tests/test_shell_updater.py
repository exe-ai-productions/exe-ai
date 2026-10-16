"""The shell finds its own newer version, fetches it on request and installs
it — and shows nothing of that itself.

`fenster-electron/updater.js` keeps one state and tells the page every change
of it; `preload.js` carries the four calls and the listener across; `main.js`
takes one quiet look after the service's start. The package description names
where the releases live and makes sure a build on the machine never uploads.

The modules require electron and cannot run outside a packaged window, so
they are loaded for real in node with thin stand-ins for `electron` and
`electron-updater` put in front of `require`.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
SHELL = ROOT / "fenster-electron"
MAIN = SHELL / "main.js"
UPDATER = SHELL / "updater.js"
PRELOAD = SHELL / "preload.js"

AVAILABLE = (
    "{ version: '0.6.10', releaseNotes: '<p>Fixes</p>', "
    "releaseDate: '2026-01-02T03:04:05.000Z' }"
)


def _run(script: str, env: dict[str, str] | None = None) -> Any:
    if not shutil.which("node"):
        pytest.skip("node is missing")
    surroundings = {k: v for k, v in os.environ.items() if k != "EXE_AI_UPDATE_CONFIG"}
    run = subprocess.run(
        ["node", "-e", script], capture_output=True, text=True, timeout=30,
        env={**surroundings, **(env or {})},
    )
    assert run.returncode == 0, (run.stdout + run.stderr)[-3000:]
    return json.loads(run.stdout.strip().splitlines()[-1])


def _updater(
    body: str,
    *,
    packaged: bool = True,
    store: bool = False,
    service: bool = False,
    env: dict[str, str] | None = None,
) -> Any:
    """Loads updater.js with stand-ins and runs `body` (async) against it.
    The stand-in for the library behaves like the library where it matters:
    a failure is the 'error' event first and the rejected promise second.

    With `service` the shell hands in what an installation asks of the
    service, as main.js does: two stand-ins that note their call among the
    library's. `ending.fails` makes the end fail with that reason;
    `ending.held` keeps it on its way for as long as the scenario wants."""
    script = f"""
const Module = require('module')
const {{ EventEmitter }} = require('events')
const lines = []
console.log = (...parts) => lines.push(parts.join(' '))
const calls = []
const autoUpdater = new EventEmitter()
const fail = (error) => {{ autoUpdater.emit('error', error); return Promise.reject(error) }}
autoUpdater.checkForUpdates = () => {{ calls.push('check'); return Promise.resolve(null) }}
autoUpdater.downloadUpdate = () => {{ calls.push('download'); return Promise.resolve([]) }}
autoUpdater.quitAndInstall = () => {{ calls.push('install') }}
const handlers = {{}}
const sent = []
let window = {{
  isDestroyed: () => false,
  webContents: {{ send: (channel, state) => sent.push([channel, state]) }},
}}
const electron = {{
  app: {{ isPackaged: {str(packaged).lower()}, getVersion: () => '0.6.9' }},
  ipcMain: {{ handle: (name, answer) => {{ handlers[name] = answer }} }},
}}
const load = Module._load
Module._load = function (request, ...rest) {{
  if (request === 'electron') return electron
  if (request === 'electron-updater') return {{ autoUpdater }}
  return load.call(this, request, ...rest)
}}
if ({str(store).lower()}) process.windowsStore = true
const updater = require({json.dumps(str(UPDATER))})
const ending = {{ fails: '', held: null }}
const installation = {{
  endService: async () => {{
    calls.push('end')
    if (ending.held) await ending.held
    if (ending.fails) throw new Error(ending.fails)
  }},
  restartService: () => {{ calls.push('restart') }},
}}
updater.start(() => window, {'installation' if service else 'undefined'})
const status = () => handlers['updates-status']()
;(async () => {{
  const result = await (async () => {{
{body}
  }})()
  process.stdout.write(JSON.stringify(result) + "\\n")
}})()
"""
    return _run(script, env)


# --- nothing by itself -------------------------------------------------------


def test_nothing_downloads_or_installs_by_itself_and_never_an_older_version():
    switches = _updater("""
    return {
      autoDownload: autoUpdater.autoDownload,
      autoInstallOnAppQuit: autoUpdater.autoInstallOnAppQuit,
      allowDowngrade: autoUpdater.allowDowngrade,
      logger: autoUpdater.logger,
    }
    """)
    assert switches == {
        "autoDownload": False, "autoInstallOnAppQuit": False, "allowDowngrade": False,
        "logger": None,
    }


def test_the_shell_looks_once_after_the_service_has_started():
    """Read off the source: the one look stands in the start, behind the wait
    for the service — and nowhere else in the shell."""
    source = MAIN.read_text(encoding="utf-8")
    match = re.search(r"\n  app\.whenReady\(\)\.then\(async \(\) => \{\n.*?\n  \}\)\n", source, re.S)
    assert match, "the start not found"
    start = match.group(0)
    assert start.index("await dienstStarten()") < start.index("updater.check()")
    assert source.count("updater.check()") == 1
    assert "updater.start(() => fenster, {" in source


def test_before_any_look_the_state_is_none_with_the_running_version():
    state = _updater("return { state: await status(), calls, lines, sent }")
    assert state["state"] == {
        "version": "0.6.9", "found": "", "notes": "", "date": "",
        "state": "none", "progress": None, "reason": "", "step": "",
    }
    assert state["calls"] == [] and state["lines"] == [] and state["sent"] == []


# --- every change of state reaches the page and the log ---------------------


def test_a_newer_version_is_found_with_its_notes_and_its_date():
    result = _updater(f"""
    autoUpdater.checkForUpdates = () => {{
      calls.push('check')
      autoUpdater.emit('checking-for-update')
      autoUpdater.emit('update-available', {AVAILABLE})
      return Promise.resolve(null)
    }}
    const answer = await handlers['updates-check']()
    return {{ answer, calls, lines, sent }}
    """)
    found = {
        "version": "0.6.9", "found": "0.6.10", "notes": "<p>Fixes</p>",
        "date": "2026-01-02T03:04:05.000Z", "state": "available",
        "progress": None, "reason": "", "step": "",
    }
    assert result["answer"] == found
    assert result["calls"] == ["check"]
    assert result["lines"] == ["Update: checking", "Update: available 0.6.10"]
    assert [channel for channel, _ in result["sent"]] == ["updates-state", "updates-state"]
    assert [state["state"] for _, state in result["sent"]] == ["checking", "available"]
    assert result["sent"][-1][1] == found


def test_the_download_reports_its_progress_and_ends_as_downloaded():
    result = _updater(f"""
    autoUpdater.emit('update-available', {AVAILABLE})
    autoUpdater.downloadUpdate = () => {{
      calls.push('download')
      autoUpdater.emit('download-progress', {{
        percent: 49.6, transferred: 496, total: 1000, bytesPerSecond: 248, delta: 1,
      }})
      autoUpdater.emit('update-downloaded', {{ version: '0.6.10' }})
      return Promise.resolve(['update.zip'])
    }}
    const answer = await handlers['updates-download']()
    return {{ answer, calls, lines: lines.slice(1), states: sent.slice(1).map(([, state]) => state) }}
    """)
    assert result["calls"] == ["download"]
    assert result["lines"] == [
        "Update: downloading 0.6.10", "Update: downloading 50 %", "Update: downloaded 0.6.10",
    ]
    assert [state["state"] for state in result["states"]] == ["downloading", "downloading", "downloaded"]
    assert result["states"][0]["progress"] is None
    assert result["states"][1]["progress"] == {
        "percent": 49.6, "transferred": 496, "total": 1000, "bytesPerSecond": 248,
    }
    assert result["answer"]["state"] == "downloaded" and result["answer"]["progress"] is None
    assert result["answer"]["found"] == "0.6.10"


def test_install_ends_the_program_once_and_only_with_a_download():
    result = _updater(f"""
    await handlers['updates-install']()
    const before = calls.slice()
    autoUpdater.emit('update-available', {AVAILABLE})
    await handlers['updates-install']()
    const available = calls.slice()
    autoUpdater.emit('update-downloaded', {{ version: '0.6.10' }})
    await handlers['updates-install']()
    await handlers['updates-install']()
    return {{ before, available, calls, last: lines[lines.length - 1] }}
    """)
    assert result["before"] == [] and result["available"] == []
    assert result["calls"] == ["install"]
    assert result["last"] == "Update: installing 0.6.10"


def test_a_failed_installation_can_be_tried_again():
    result = _updater(f"""
    for (let round = 0; round < 2; round += 1) {{
      autoUpdater.emit('update-available', {AVAILABLE})
      autoUpdater.emit('update-downloaded', {{ version: '0.6.10' }})
      await handlers['updates-install']()
      autoUpdater.emit('error', new Error('the package could not be taken over'))
    }}
    return {{ calls, state: await status() }}
    """)
    assert result["calls"] == ["install", "install"]
    assert result["state"]["state"] == "error"
    assert result["state"]["reason"] == "the package could not be taken over"


# --- an installation ends the service first ------------------------------------

DOWNLOADED = f"""
    autoUpdater.emit('update-available', {AVAILABLE})
    autoUpdater.emit('update-downloaded', {{ version: '0.6.10' }})
"""


def test_installing_ends_the_service_before_the_program_is_handed_over():
    """Falls over without the fix: the program was handed over with the
    service still running, and the release replaced its files under it."""
    result = _updater(DOWNLOADED + """
    const answer = await handlers['updates-install']()
    return { calls, state: answer.state }
    """, service=True)
    assert result == {"calls": ["end", "install"], "state": "downloaded"}


def test_nothing_is_handed_over_while_the_service_is_still_ending():
    """The end of the service takes its time. Until it is over the program
    is not handed over, and a second click does not end or install twice."""
    result = _updater(DOWNLOADED + """
    let release
    ending.held = new Promise((resolve) => { release = resolve })
    const first = handlers['updates-install']()
    await new Promise((resolve) => setImmediate(resolve))
    const second = await handlers['updates-install']()
    const meanwhile = calls.slice()
    release()
    await first
    return { meanwhile, second: second.state, calls }
    """, service=True)
    assert result["meanwhile"] == ["end"]
    assert result["second"] == "downloaded"
    assert result["calls"] == ["end", "install"]


def test_a_service_that_does_not_end_keeps_the_release_from_being_installed():
    """Nothing is installed over a running service: the state is the error
    with the reason the end gave, the service is not started again — it
    never went — and the next try asks it to end anew."""
    result = _updater(DOWNLOADED + """
    ending.fails = 'The service on port 8090 is still running.'
    const refused = await handlers['updates-install']()
    const after = calls.slice()
    ending.fails = ''
    autoUpdater.emit('update-downloaded', { version: '0.6.10' })
    await handlers['updates-install']()
    return { refused: [refused.state, refused.reason], after, calls }
    """, service=True)
    assert result["refused"] == ["error", "The service on port 8090 is still running."]
    assert result["after"] == ["end"]
    assert result["calls"] == ["end", "end", "install"]


def test_an_installation_that_fails_after_the_service_ended_brings_the_service_back():
    """The program runs on then, and so must its service — whether the
    library throws at once or announces the failure a moment later. Once
    per failed installation."""
    result = _updater(DOWNLOADED + """
    autoUpdater.quitAndInstall = () => { calls.push('install'); throw new Error('no hand-over') }
    const thrown = await handlers['updates-install']()
    const first = calls.splice(0)
    autoUpdater.quitAndInstall = () => { calls.push('install') }
    autoUpdater.emit('update-downloaded', { version: '0.6.10' })
    await handlers['updates-install']()
    autoUpdater.emit('error', new Error('the package could not be taken over'))
    autoUpdater.emit('error', new Error('said twice'))
    return { thrown: [thrown.state, thrown.reason], first, second: calls }
    """, service=True)
    assert result["thrown"] == ["error", "no hand-over"]
    assert result["first"] == ["end", "install", "restart"]
    assert result["second"] == ["end", "install", "restart"]


def test_silence_probe_without_a_fetched_release_the_service_is_left_alone():
    """Install without a download does nothing, as before — and neither a
    failed look nor a failed download starts a service that never ended."""
    result = _updater(f"""
    await handlers['updates-install']()
    autoUpdater.emit('update-available', {AVAILABLE})
    await handlers['updates-install']()
    autoUpdater.emit('download-progress', {{ percent: 40, transferred: 4, total: 10, bytesPerSecond: 1 }})
    await handlers['updates-install']()
    autoUpdater.emit('error', new Error('the download broke off'))
    autoUpdater.checkForUpdates = () => {{ calls.push('check'); return fail(new Error('no network')) }}
    await handlers['updates-check']()
    return {{ calls, state: (await status()).state }}
    """, service=True)
    assert result == {"calls": ["check"], "state": "error"}


def test_the_shell_hands_the_updater_the_end_of_the_service_and_its_way_back():
    """Read off the source: the two things an installation asks of the
    service are the shell's own, and the end of the service is called from
    nowhere but the installation — closing the window still leaves it."""
    source = MAIN.read_text(encoding="utf-8")
    wiring = re.search(r"\nupdater\.start\(\(\) => fenster, \{\n(.*?)\n\}\)\n", source, re.S)
    assert wiring, "the wiring not found"
    assert wiring.group(1).split() == [
        "endService:", "endServiceForUpdate,", "restartService:", "restartServiceAfterUpdate,",
    ]
    quit_ = re.search(r"\napp\.on\('before-quit', \(\) => \{\n.*?\n\}\)\n", source, re.S)
    assert quit_, "before-quit not found"
    assert "endServiceForUpdate" not in quit_.group(0)
    assert "updater" not in quit_.group(0)
    # Named where it is defined and where it is handed in; the third is the
    # sentence of the file's head that points at it.
    assert len(re.findall(r"\bendServiceForUpdate\b", source)) == 3


# --- the silence probes ------------------------------------------------------


def test_the_newest_version_is_no_finding_and_nothing_is_fetched():
    result = _updater("""
    autoUpdater.checkForUpdates = () => {
      calls.push('check')
      autoUpdater.emit('checking-for-update')
      autoUpdater.emit('update-not-available', { version: '0.6.9' })
      return Promise.resolve(null)
    }
    const answer = await handlers['updates-check']()
    await handlers['updates-download']()
    await handlers['updates-install']()
    return { answer, calls, lines }
    """)
    assert result["answer"]["state"] == "none" and result["answer"]["found"] == ""
    assert result["calls"] == ["check"]
    assert result["lines"] == [
        "Update: checking", "Update: not available (running 0.6.9, published 0.6.9)",
    ]


def test_a_finding_that_is_gone_takes_its_notes_with_it():
    state = _updater(f"""
    autoUpdater.emit('update-available', {AVAILABLE})
    autoUpdater.emit('update-not-available', {{ version: '0.6.9' }})
    return status()
    """)
    assert (state["found"], state["notes"], state["date"], state["state"]) == ("", "", "", "none")


def test_no_look_runs_under_a_download_or_over_a_finished_one():
    result = _updater(f"""
    autoUpdater.emit('update-available', {AVAILABLE})
    let finish
    autoUpdater.downloadUpdate = () => new Promise((done) => {{ finish = done }})
    const running = handlers['updates-download']()
    const during = await handlers['updates-check']()
    await handlers['updates-download']()
    autoUpdater.emit('update-downloaded', {{ version: '0.6.10' }})
    finish([])
    await running
    const after = await handlers['updates-check']()
    return {{ calls, during: during.state, after: after.state }}
    """)
    assert result == {"calls": [], "during": "downloading", "after": "downloaded"}


def test_the_shell_shows_nothing_of_an_update_itself():
    """No dialog, no window, no notification and no menu entry: the updater
    module reaches for the app and the bridge only, and the menu has no entry
    for it."""
    updater = UPDATER.read_text(encoding="utf-8")
    assert "const { app, ipcMain } = require('electron')" in updater
    assert updater.count("require('electron')") == 1
    main = MAIN.read_text(encoding="utf-8")
    preload = PRELOAD.read_text(encoding="utf-8")
    for source in (updater, main, preload):
        assert "showMessageBox" not in source and "new Notification" not in source
    taken = re.search(r"\nconst \{\n(.*?)\n\} = require\('electron'\)\n", main, re.S)
    assert taken, "what the shell takes from electron not found"
    names = {name.strip() for name in taken.group(1).split(",") if name.strip()}
    assert "app" in names and not names & {"dialog", "Notification"}
    menu = re.search(r"\nfunction menueSetzen\(\) \{\n.*?\n\}\n", main, re.S)
    assert menu, "the menu not found"
    assert "pdate" not in menu.group(0)


# --- a failure is a state, and nothing else ---------------------------------


def test_a_failed_look_is_the_state_error_with_its_reason_in_one_line():
    result = _updater("""
    autoUpdater.checkForUpdates = () => {
      autoUpdater.emit('checking-for-update')
      return fail(new Error('net::ERR_CONNECTION_REFUSED\\n    at somewhere (file.js:1:2)'))
    }
    const answer = await handlers['updates-check']()
    return { answer, lines, sent: sent.map(([, state]) => state.state) }
    """)
    assert result["answer"]["state"] == "error"
    assert result["answer"]["reason"] == "net::ERR_CONNECTION_REFUSED"
    assert result["lines"] == ["Update: checking", "Update: error: net::ERR_CONNECTION_REFUSED"]
    assert result["sent"] == ["checking", "error"]


def test_the_reason_leads_with_the_code_the_library_gives_a_failure():
    state = _updater("""
    const error = new Error('App version is not a valid semver version: "abc"')
    error.code = 'ERR_UPDATER_INVALID_VERSION'
    autoUpdater.checkForUpdates = () => fail(error)
    return handlers['updates-check']()
    """)
    assert state["reason"] == (
        'ERR_UPDATER_INVALID_VERSION: App version is not a valid semver version: "abc"'
    )


def test_a_failed_download_is_the_state_error_and_the_next_look_clears_it():
    result = _updater(f"""
    autoUpdater.emit('update-available', {AVAILABLE})
    autoUpdater.downloadUpdate = () => fail(new Error('sha512 checksum mismatch'))
    const failed = await handlers['updates-download']()
    autoUpdater.emit('checking-for-update')
    return {{ failed, cleared: await status() }}
    """)
    assert result["failed"]["state"] == "error"
    assert result["failed"]["reason"] == "sha512 checksum mismatch"
    assert result["failed"]["progress"] is None
    assert result["cleared"]["state"] == "checking" and result["cleared"]["reason"] == ""


def test_a_reason_that_begins_with_its_code_does_not_say_it_twice():
    state = _updater("""
    const error = new Error('ENOENT: no such file or directory, open app-update.yml')
    error.code = 'ENOENT'
    autoUpdater.checkForUpdates = () => fail(error)
    return handlers['updates-check']()
    """)
    assert state["reason"] == "ENOENT: no such file or directory, open app-update.yml"


def test_a_failure_the_library_does_not_announce_still_ends_as_error():
    """A rejection without the 'error' event, or a call that throws at once,
    must not leave the state at checking or downloading for good — and the
    page's call is answered, not rejected."""
    result = _updater(f"""
    autoUpdater.checkForUpdates = () => {{
      autoUpdater.emit('checking-for-update')
      return Promise.reject(new Error('quiet rejection'))
    }}
    const look = await handlers['updates-check']()
    autoUpdater.emit('update-available', {AVAILABLE})
    autoUpdater.downloadUpdate = () => {{ throw new Error('thrown at once') }}
    const fetched = await handlers['updates-download']()
    autoUpdater.emit('update-available', {AVAILABLE})
    autoUpdater.emit('update-downloaded', {{ version: '0.6.10' }})
    autoUpdater.quitAndInstall = () => {{ calls.push('install'); throw new Error('no hand-over') }}
    const first = await handlers['updates-install']()
    autoUpdater.emit('update-downloaded', {{ version: '0.6.10' }})
    await handlers['updates-install']()
    return {{
      look: [look.state, look.reason], fetched: [fetched.state, fetched.reason],
      first: [first.state, first.reason], calls,
      errors: lines.filter((line) => line.startsWith('Update: error')).length,
    }}
    """)
    assert result == {
        "look": ["error", "quiet rejection"],
        "fetched": ["error", "thrown at once"],
        "first": ["error", "no hand-over"],
        # The second installation is tried — and fails the same way.
        "calls": ["install", "install"],
        "errors": 4,
    }


def test_an_announced_failure_is_told_once():
    lines = _updater("""
    autoUpdater.checkForUpdates = () => fail(new Error('told by the event'))
    await handlers['updates-check']()
    return lines
    """)
    assert lines == ["Update: error: told by the event"]


def test_a_change_without_a_window_is_only_a_line():
    result = _updater("""
    window = null
    autoUpdater.emit('checking-for-update')
    window = { isDestroyed: () => true, webContents: { send: () => { throw new Error('gone') } } }
    autoUpdater.emit('update-not-available', { version: '0.6.9' })
    return { lines: lines.length, sent }
    """)
    assert result == {"lines": 2, "sent": []}


# --- the trial run from the source folder ------------------------------------


def _trial(*, packaged: bool, config: str | None) -> dict:
    return _updater(
        """
    return {
      forced: autoUpdater.forceDevUpdateConfig === true,
      path: autoUpdater.updateConfigPath ?? null,
    }
    """,
        packaged=packaged,
        env={"EXE_AI_UPDATE_CONFIG": config} if config else None,
    )


def test_a_trial_run_can_name_its_own_feed_description():
    assert _trial(packaged=False, config="/somewhere/trial.yml") == {
        "forced": True, "path": "/somewhere/trial.yml",
    }


def test_a_packaged_shell_does_not_read_the_trial_variable():
    assert _trial(packaged=True, config="/somewhere/trial.yml") == {"forced": False, "path": None}


def test_a_run_from_the_source_folder_without_it_looks_for_nothing():
    assert _trial(packaged=False, config=None) == {"forced": False, "path": None}


# --- the bridge ---------------------------------------------------------------


def _bridge(body: str) -> Any:
    script = f"""
const Module = require('module')
const exposed = {{}}
const invoked = []
const listening = []
const removed = []
const electron = {{
  contextBridge: {{ exposeInMainWorld: (name, api) => {{ exposed[name] = api }} }},
  ipcRenderer: {{
    invoke: (...args) => {{ invoked.push(args); return Promise.resolve('answer') }},
    on: (channel, listener) => listening.push([channel, listener]),
    removeListener: (channel, listener) => removed.push([channel, listener]),
    send: () => {{}},
  }},
}}
const load = Module._load
Module._load = function (request, ...rest) {{
  return request === 'electron' ? electron : load.call(this, request, ...rest)
}}
require({json.dumps(str(PRELOAD))})
const bridge = exposed.exeHuelle
;(async () => {{
  const result = await (async () => {{
{body}
  }})()
  process.stdout.write(JSON.stringify(result) + "\\n")
}})()
"""
    return _run(script)


def test_the_bridge_carries_the_four_calls_each_on_its_own_channel():
    result = _bridge("""
    const answers = [
      await bridge.updates.status(), await bridge.updates.check(),
      await bridge.updates.download(), await bridge.updates.install(),
    ]
    return { answers, invoked, names: Object.keys(bridge.updates).sort() }
    """)
    assert result["names"] == ["check", "download", "install", "on", "status"]
    assert result["invoked"] == [
        ["updates-status"], ["updates-check"], ["updates-download"], ["updates-install"],
    ]
    assert result["answers"] == ["answer"] * 4


def test_the_bridge_hands_on_every_change_and_the_way_to_stop_listening():
    result = _bridge("""
    const heard = []
    const stop = bridge.updates.on((state) => heard.push(state))
    const [channel, listener] = listening[0]
    listener({ sender: 'the event stays behind' }, { state: 'available', found: '0.6.10' })
    stop()
    return {
      channel, heard, listeners: listening.length,
      removed: removed.length === 1 && removed[0][0] === 'updates-state' && removed[0][1] === listener,
    }
    """)
    assert result == {
        "channel": "updates-state",
        "heard": [{"state": "available", "found": "0.6.10"}],
        "listeners": 1,
        "removed": True,
    }


def test_the_bridge_listens_for_nothing_without_a_callback():
    result = _bridge("return { answer: bridge.updates.on('not a function') ?? null, listening }")
    assert result == {"answer": None, "listening": []}


def test_the_bridge_carries_these_calls_and_no_others():
    names = _bridge("return Object.keys(bridge).sort()")
    assert names == [
        "aufBetrachterEscape", "aufDiktat", "aufVorlesen", "frameColour", "frameScheme", "menuWords",
        "terminal", "thumbnail", "updates", "vorlesenBeschriftung",
    ]


# --- the package description -------------------------------------------------


def _package() -> dict:
    return json.loads((SHELL / "package.json").read_text(encoding="utf-8"))


def test_the_shell_ships_the_updater_and_its_own_module():
    package = _package()
    assert "electron-updater" in package["dependencies"]
    assert "electron-updater" not in package["devDependencies"]
    assert "updater.js" in package["build"]["files"]


def test_the_lock_file_is_in_step_with_the_package():
    """A clean install reads the lock file and refuses one that disagrees."""
    lock = json.loads((SHELL / "package-lock.json").read_text(encoding="utf-8"))
    wanted = _package()["dependencies"]["electron-updater"]
    assert lock["packages"][""]["dependencies"]["electron-updater"] == wanted
    assert "node_modules/electron-updater" in lock["packages"]
    assert lock["packages"]["node_modules/electron-updater"].get("dev") is not True


def test_the_releases_live_on_github_and_start_as_a_draft():
    assert _package()["build"]["publish"] == [{
        "provider": "github", "owner": "exe-ai-productions", "repo": "exe-ai",
        "releaseType": "draft",
    }]


def test_macos_builds_the_zip_the_updater_fetches_beside_the_dmg():
    build = _package()["build"]
    assert build["mac"]["target"] == ["dmg", "zip"]
    assert build["win"]["target"] == [{"target": "nsis", "arch": ["x64"]}]


def test_the_macos_packages_carry_no_space_in_their_name():
    """The feed names the zip by a name without spaces; a zip named after the
    product would lie on disk under another name than the one the feed asks
    for."""
    name = _package()["build"]["mac"]["artifactName"]
    assert name == "Exe-AI-${version}-${arch}.${ext}"
    assert " " not in name and "${productName}" not in name


def test_a_build_on_the_machine_never_uploads():
    scripts = _package()["scripts"]
    assert scripts["packen"] == "electron-builder --mac --publish never"
    assert scripts["pack:win"] == "electron-builder --win --publish never"
    for name, script in scripts.items():
        if "electron-builder" in script and "--dir" not in script:
            assert script.endswith("--publish never"), name


# --- a copy from the Microsoft Store ----------------------------------------


def test_a_copy_from_the_store_never_looks_and_says_so_from_the_start():
    """The Store keeps such a copy current: its state is `store` before any
    look, the look the shell takes after the start touches the library not
    at all, and the state stays."""
    result = _updater("""
    const before = status()
    const after = await handlers['updates-check']()
    return { before, after, calls }
    """, store=True)
    assert result["before"]["state"] == "store"
    assert result["after"]["state"] == "store"
    assert result["calls"] == []


def test_a_copy_that_is_not_from_the_store_keeps_its_own_look():
    """The silence check: without the Store's mark nothing changes."""
    result = _updater("""
    const before = status()
    await handlers['updates-check']()
    return { before, calls }
    """)
    assert result["before"]["state"] == "none"
    assert result["calls"] == ["check"]


def test_the_settings_row_of_a_store_copy_names_the_store_and_offers_no_look():
    row = (SHELL.parent / "frontend" / "src" / "teile" / "Updatezeile.svelte").read_text(encoding="utf-8")
    assert "{#if updates.state !== 'store'}" in row
    assert "{#if updates.state === 'store'}" in row
    assert "t('updates.store')" in row


# --- a failure names the step it belongs to ----------------------------------


def test_a_failed_look_names_the_step_check():
    state = _updater("""
    autoUpdater.checkForUpdates = () => fail(new Error('offline'))
    return handlers['updates-check']()
    """)
    assert (state["state"], state["step"], state["reason"]) == ("error", "check", "offline")


def test_a_failed_download_names_the_step_download_and_a_later_look_names_check():
    result = _updater(f"""
    autoUpdater.emit('update-available', {AVAILABLE})
    autoUpdater.downloadUpdate = () => fail(new Error('sha512 checksum mismatch'))
    const download = await handlers['updates-download']()
    autoUpdater.checkForUpdates = () => fail(new Error('offline'))
    const look = await handlers['updates-check']()
    return {{ download: [download.state, download.step, download.reason], look: [look.state, look.step] }}
    """)
    assert result["download"] == ["error", "download", "sha512 checksum mismatch"]
    assert result["look"] == ["error", "check"]


def test_a_failed_installation_names_the_step_install_with_the_reason_the_end_gave():
    result = _updater(f"""
    autoUpdater.emit('update-available', {AVAILABLE})
    autoUpdater.emit('update-downloaded', {{ version: '0.6.10' }})
    ending.fails = 'The service on port 8090 is still running.'
    const refused = await handlers['updates-install']()
    return {{ refused: [refused.state, refused.step, refused.reason], calls }}
    """, service=True)
    assert result["refused"] == ["error", "install", "The service on port 8090 is still running."]


def test_a_failure_of_the_library_during_the_installation_names_the_step_install():
    state = _updater(f"""
    autoUpdater.emit('update-available', {AVAILABLE})
    autoUpdater.emit('update-downloaded', {{ version: '0.6.10' }})
    autoUpdater.quitAndInstall = () => {{ throw new Error('the package could not be taken over') }}
    return handlers['updates-install']()
    """, service=True)
    assert (state["state"], state["step"]) == ("error", "install")
