"""The terminal in the window and the service the window finds already
running — the two shell modules behind them, run for real in node.

`fenster-electron/terminal.js` owns the pseudoterminal that runs the
terminal client inside the window; `fenster-electron/dienstsuche.js` finds a
service of ours that is already running on the shell's folder and port, so
the window uses it instead of starting a second one. Both are plain node;
node-pty, the one native piece, is replaced by a stand-in here, and the
service by a small HTTP server that answers the interface page.

The orchestration in `fenster-electron/main.js` (`dienstAnbinden`) is cut
from its source by name, the way tests/test_huelle_dienst_und_geheimnis.py
does it, and run with a stand-in for the lookup.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

WURZEL = Path(__file__).resolve().parents[1]
HUELLE = WURZEL / "fenster-electron"
TERMINAL = HUELLE / "terminal.js"
DIENSTSUCHE = HUELLE / "dienstsuche.js"
MAIN = HUELLE / "main.js"
PRELOAD = HUELLE / "preload.js"
PAKET = HUELLE / "package.json"


def _laufe(skript: str, *, timeout: int = 30) -> dict:
    if not shutil.which("node"):
        pytest.skip("node is missing")
    lauf = subprocess.run(
        ["node", "-e", skript], capture_output=True, text=True, encoding="utf-8", timeout=timeout
    )
    assert lauf.returncode == 0, (lauf.stdout + lauf.stderr)[-3000:]
    return json.loads(lauf.stdout.strip().splitlines()[-1])


def _slashes(wert):
    """The paths of a report with one separator: ``path.join`` of the host
    writes a backslash on Windows and a slash elsewhere, and what the
    tests state is the order of the parts."""
    if isinstance(wert, dict):
        return {schluessel: _slashes(inhalt) for schluessel, inhalt in wert.items()}
    if isinstance(wert, list):
        return [_slashes(inhalt) for inhalt in wert]
    return wert.replace("\\", "/") if isinstance(wert, str) else wert


def _stueck(quelle: str, muster: str, name: str) -> str:
    treffer = re.search(muster, quelle, re.S)
    assert treffer, f"{name} not found"
    return treffer.group(0).strip() + "\n"


# --- terminal.js: the program, its arguments, its environment ---------------


def test_from_source_the_client_is_the_environments_python_with_the_module():
    skript = f"""
const t = require({json.dumps(str(TERMINAL))})
console.log(JSON.stringify({{
  source: t.clientCommand({{ env: {{}}, packaged: false, repoRoot: '/repo', platform: 'darwin' }}),
  source_win: t.clientCommand({{ env: {{}}, packaged: false, repoRoot: 'C:\\\\repo', platform: 'win32' }}),
  own: t.clientCommand({{ env: {{ EXE_AI_CLI: '/elsewhere/exe' }}, packaged: true, resourcesPath: '/App/Resources' }}),
}}))
"""
    ergebnis = _slashes(_laufe(skript))
    assert ergebnis["source"]["file"] == "/repo/.venv/bin/python"
    assert ergebnis["source"]["args"] == ["-m", "cli"]
    assert ergebnis["source"]["cwd"] == "/repo"
    assert ergebnis["source_win"]["file"].endswith("python.exe")
    assert ergebnis["own"]["file"] == "/elsewhere/exe"


def _packaged_command(platform: str) -> str:
    """Where the packaged window looks for the command, counted from the
    resources folder, with the slash as the separator on every system — the
    test runs node on this machine, whichever system it names."""
    resources = "/App/Resources"
    skript = f"""
const t = require({json.dumps(str(TERMINAL))})
console.log(JSON.stringify(t.clientCommand({{
  env: {{}}, packaged: true, resourcesPath: {json.dumps(resources)}, platform: {json.dumps(platform)},
}})))
"""
    command = _laufe(skript)
    assert command["args"] == []
    file = command["file"].replace("\\", "/")
    assert file.startswith(resources + "/"), file
    return file[len(resources) + 1 :]


def test_packaged_the_client_is_the_command_the_package_carries():
    """Falls over with the former places: a program named exe directly in
    the resources folder, which no package ever put there."""
    assert _packaged_command("darwin") == "bin/exe"
    assert _packaged_command("win32") == "exe-ai-terminal/exe.exe"


def test_the_window_looks_for_the_command_where_the_package_puts_it():
    """The two places are not this module's to choose: the packer lays the
    command out, and the installer and the Store's alias name it. Each of
    those is read here, so that a place moved in one of them is a red test
    and not a window whose terminal starts nothing."""
    build = json.loads(PAKET.read_text(encoding="utf-8"))["build"]
    # macOS: the script the links on the path point at.
    (script,) = [entry for entry in build["mac"]["extraResources"] if entry["from"] == "../deploy/exe"]
    assert _packaged_command("darwin") == script["to"]
    # Windows: the console program beside the service, in the service's
    # folder, the way the packer copies it and the build description names it.
    (service,) = [entry for entry in build["extraResources"] if entry["from"] == "../dist/Exe AI"]
    folder, program = _packaged_command("win32").split("/")
    assert folder == service["to"]
    spec = (WURZEL / "deploy" / "exe-ai-terminal.spec").read_text(encoding="utf-8")
    assert program == "exe.exe" and re.search(r"""\bname\s*=\s*["']exe["']""", spec)
    place = f"resources\\{folder}\\{program}"
    installer = (HUELLE / "build" / "installer.nsh").read_text(encoding="utf-8")
    assert f'@"%~dp0..\\{place}" %*' in installer
    alias = (HUELLE / "build" / "appx-extensions.xml").read_text(encoding="utf-8")
    assert f'Executable="app\\{place}"' in alias


def test_the_client_gets_the_address_first_and_only_well_formed_wishes():
    skript = f"""
const t = require({json.dumps(str(TERMINAL))})
const clean = t.cleanRequest({{
  chat: 'd8b00b6266814323bfd9d90ff931dedf', look: 'heaven', lang: 'de', cols: 120, rows: 40,
}})
const dirty = t.cleanRequest({{
  chat: '../etc/passwd', look: '--record', lang: 'de; rm', cols: 'abc', rows: 0,
}})
console.log(JSON.stringify({{
  clean: t.clientArguments({{ address: 'http://127.0.0.1:8123', ...clean }}),
  dirty: t.clientArguments({{ address: 'http://127.0.0.1:8123', ...dirty }}),
  clean_size: [clean.cols, clean.rows],
  dirty_size: [dirty.cols, dirty.rows],
  nothing: t.clientArguments({{ address: 'http://127.0.0.1:8123', ...t.cleanRequest(null) }}),
}}))
"""
    ergebnis = _laufe(skript)
    assert ergebnis["clean"] == [
        "--url", "http://127.0.0.1:8123",
        "--chat", "d8b00b6266814323bfd9d90ff931dedf",
        "--theme", "heaven",
        "--lang", "de",
    ]
    assert ergebnis["dirty"] == ["--url", "http://127.0.0.1:8123"]
    assert ergebnis["clean_size"] == [120, 40]
    assert ergebnis["dirty_size"] == [80, 24]
    assert ergebnis["nothing"] == ["--url", "http://127.0.0.1:8123"]


def test_the_client_is_told_that_it_runs_in_the_window():
    skript = f"""
const t = require({json.dumps(str(TERMINAL))})
const env = t.clientEnvironment({{ PATH: '/usr/bin', HOME: '/home/someone' }})
console.log(JSON.stringify({{ env, mark: t.WINDOW_MARK }}))
"""
    ergebnis = _laufe(skript)
    assert ergebnis["mark"] == "EXE_AI_WINDOW_TERMINAL"
    assert ergebnis["env"]["EXE_AI_WINDOW_TERMINAL"] == "1"
    assert ergebnis["env"]["TERM"] == "xterm-256color"
    assert ergebnis["env"]["COLORTERM"] == "truecolor"
    assert ergebnis["env"]["PATH"] == "/usr/bin"


# --- terminal.js: the terminals, wired to a stand-in pty and ipc ------------

_STAND_INS = """
const t = require(%(modul)s)
const handlers = {}
const ipcMain = {
  handle: (name, fn) => { handlers[name] = fn },
  on: (name, fn) => { handlers[name] = fn },
}
const spawned = []
const pty = {
  spawn(file, args, options) {
    const term = {
      pid: 4242 + spawned.length, file, args, options, written: [], sizes: [], killed: false,
      onData(fn) { this.data = fn }, onExit(fn) { this.exit = fn },
      write(d) { this.written.push(d) }, resize(c, r) { this.sizes.push([c, r]) },
      kill() { this.killed = true },
    }
    spawned.push(term)
    return term
  },
}
const sent = []
let destroyed = false
const contents = {
  id: 7, isDestroyed: () => destroyed, send: (name, data) => sent.push([name, data]),
  once: () => {},
}
const logged = []
const terminals = t.createTerminals({
  ipcMain, pty, address: 'http://127.0.0.1:8123',
  command: { file: '/repo/.venv/bin/python', args: ['-m', 'cli'], cwd: '/repo' },
  log: (line) => logged.push(line),
  exists: () => true,
})
"""


def _stand_ins() -> str:
    return _STAND_INS % {"modul": json.dumps(str(TERMINAL))}


def test_a_start_spawns_the_client_against_the_shells_own_service_and_says_so():
    skript = f"""
{_stand_ins()}
Promise.resolve(handlers['terminal-start']({{ sender: contents }}, {{ cols: 100, rows: 30, look: 'exe', lang: 'en' }}))
  .then((answer) => {{
    const term = spawned[0]
    term.data('hello from exe')
    handlers['terminal-write']({{ sender: contents }}, '/help\\r')
    handlers['terminal-resize']({{ sender: contents }}, 90, 28)
    const running = terminals.running(7)
    term.exit({{ exitCode: 0 }})
    console.log(JSON.stringify({{
      answer, file: term.file, args: term.args, name: term.options.name,
      size: [term.options.cols, term.options.rows], cwd: term.options.cwd,
      mark: term.options.env.EXE_AI_WINDOW_TERMINAL, written: term.written, sizes: term.sizes,
      sent, running, runningAfterExit: terminals.running(7), logged,
    }}))
  }})
"""
    ergebnis = _laufe(skript)
    assert ergebnis["answer"] == {"pid": 4242}
    assert ergebnis["file"] == "/repo/.venv/bin/python"
    assert ergebnis["args"] == ["-m", "cli", "--url", "http://127.0.0.1:8123", "--theme", "exe", "--lang", "en"]
    assert ergebnis["name"] == "xterm-256color"
    assert ergebnis["size"] == [100, 30]
    assert ergebnis["cwd"] == "/repo"
    assert ergebnis["mark"] == "1"
    assert ergebnis["written"] == ["/help\r"]
    assert ergebnis["sizes"] == [[90, 28]]
    assert ergebnis["sent"] == [["terminal-data", "hello from exe"], ["terminal-exit", 0]]
    assert ergebnis["running"] is True
    assert ergebnis["runningAfterExit"] is False
    assert len(ergebnis["logged"]) == 1
    assert "started in the window against http://127.0.0.1:8123" in ergebnis["logged"][0]
    assert "pid 4242" in ergebnis["logged"][0]


def test_a_second_start_for_the_same_page_ends_the_first_client():
    """And the first client's late output and end never reach the page as
    the second one's: a replaced client is silent towards the page."""
    skript = f"""
{_stand_ins()}
const start = () => Promise.resolve(handlers['terminal-start']({{ sender: contents }}, {{}}))
start().then(() => start()).then((answer) => {{
  spawned[0].data('late output of the first')
  spawned[0].exit({{ exitCode: 1 }})
  console.log(JSON.stringify({{
    answer, firstKilled: spawned[0].killed, secondKilled: spawned[1].killed, count: spawned.length,
    sent, running: terminals.running(7),
  }}))
}})
"""
    ergebnis = _laufe(skript)
    assert ergebnis["answer"] == {"pid": 4243}
    assert ergebnis["firstKilled"] is True
    assert ergebnis["secondKilled"] is False
    assert ergebnis["count"] == 2
    assert ergebnis["sent"] == []
    assert ergebnis["running"] is True


def test_stop_all_ends_every_client_and_nothing_reaches_a_closed_page():
    skript = f"""
{_stand_ins()}
Promise.resolve(handlers['terminal-start']({{ sender: contents }}, {{}})).then(() => {{
  destroyed = true
  spawned[0].data('late')
  terminals.stopAll()
  handlers['terminal-write']({{ sender: contents }}, 'typed after the end')
  console.log(JSON.stringify({{
    killed: spawned[0].killed, sent, written: spawned[0].written, running: terminals.running(7),
  }}))
}})
"""
    ergebnis = _laufe(skript)
    assert ergebnis["killed"] is True
    assert ergebnis["sent"] == []
    assert ergebnis["written"] == []
    assert ergebnis["running"] is False


def test_without_node_pty_or_with_a_failing_spawn_the_page_hears_an_error():
    skript = f"""
const t = require({json.dumps(str(TERMINAL))})
const handlers = {{}}
const ipcMain = {{ handle: (n, f) => {{ handlers[n] = f }}, on: (n, f) => {{ handlers[n] = f }} }}
const contents = {{ id: 1, isDestroyed: () => false, send: () => {{}}, once: () => {{}} }}
const logged = []
const none = t.createTerminals({{ ipcMain, pty: null, address: 'http://127.0.0.1:8123', command: {{ file: '/x', args: [] }}, log: () => {{}} }})
const withoutPty = none.start(contents, {{}})
const failing = t.createTerminals({{
  ipcMain, pty: {{ spawn() {{ throw new Error('ENOENT: no such file') }} }}, address: 'http://127.0.0.1:8123',
  command: {{ file: '/missing/exe', args: [] }}, log: (line) => logged.push(line), exists: () => true,
}})
const broken = failing.start(contents, {{}})
console.log(JSON.stringify({{ withoutPty, broken, logged, running: failing.running(1) }}))
"""
    ergebnis = _laufe(skript)
    # The missing module is named with a reason the page can translate; a
    # failure the system names carries none.
    assert ergebnis["withoutPty"] == {"error": "node-pty is unavailable.", "reason": "no-pty"}
    assert "ENOENT" in ergebnis["broken"]["error"]
    assert "reason" not in ergebnis["broken"]
    assert ergebnis["running"] is False
    assert any("could not be started" in line for line in ergebnis["logged"])


def test_a_program_that_is_not_there_is_never_started_and_the_answer_names_the_file():
    """The child of a missing program ends at once, without node-pty
    throwing, and the page would only see that it ended. So the file is
    looked for first: nothing is spawned, the answer carries its own reason
    and the path, and the log names the path and no start."""
    skript = f"""
const t = require({json.dumps(str(TERMINAL))})
const handlers = {{}}
const ipcMain = {{ handle: (n, f) => {{ handlers[n] = f }}, on: (n, f) => {{ handlers[n] = f }} }}
const contents = {{ id: 1, isDestroyed: () => false, send: () => {{}}, once: () => {{}} }}
const logged = []
let spawns = 0
const pty = {{ spawn() {{ spawns += 1; return {{ pid: 9, onData() {{}}, onExit() {{}}, kill() {{}} }} }} }}
const make = (exists) => t.createTerminals({{
  ipcMain, pty, address: 'http://127.0.0.1:8123',
  command: {{ file: '/tmp/gone/exe', args: [] }}, log: (line) => logged.push(line), exists,
}})
const missing = make(() => false)
const answer = missing.start(contents, {{}})
const spawnedWithout = spawns
const present = make((file) => file === '/tmp/gone/exe')
const started = present.start(contents, {{}})
console.log(JSON.stringify({{ answer, spawnedWithout, started, spawnsAfter: spawns, logged, running: missing.running(1) }}))
"""
    ergebnis = _laufe(skript)
    assert ergebnis["answer"] == {
        "error": "/tmp/gone/exe was not found.",
        "reason": "no-file",
        "path": "/tmp/gone/exe",
    }
    assert ergebnis["spawnedWithout"] == 0
    # Silence probe: a program that is there starts as before.
    assert ergebnis["started"] == {"pid": 9}
    assert ergebnis["spawnsAfter"] == 1
    assert any("/tmp/gone/exe was not found" in line for line in ergebnis["logged"])
    assert ergebnis["logged"][0] == "Terminal: /tmp/gone/exe was not found, nothing was started"


def test_the_default_looks_for_the_file_on_the_disk():
    """Without a stand-in the check is the disk's: a file that is not there
    is refused, one that is there is started."""
    skript = f"""
const t = require({json.dumps(str(TERMINAL))})
const handlers = {{}}
const ipcMain = {{ handle: (n, f) => {{ handlers[n] = f }}, on: (n, f) => {{ handlers[n] = f }} }}
const contents = {{ id: 1, isDestroyed: () => false, send: () => {{}}, once: () => {{}} }}
let spawns = 0
const pty = {{ spawn() {{ spawns += 1; return {{ pid: 5, onData() {{}}, onExit() {{}}, kill() {{}} }} }} }}
const run = (file) => t.createTerminals({{
  ipcMain, pty, address: 'http://127.0.0.1:8123', command: {{ file, args: [] }}, log: () => {{}},
}}).start(contents, {{}})
console.log(JSON.stringify({{ gone: run('/definitely/not/here/exe'), there: run(process.execPath) }}))
"""
    ergebnis = _laufe(skript)
    assert ergebnis["gone"]["reason"] == "no-file"
    assert ergebnis["there"] == {"pid": 5}


def test_the_bridge_and_the_shell_speak_the_same_channel_names():
    """preload.js names the channels the page uses; terminal.js answers them.
    A name that only one side knows is a terminal that never starts."""
    preload = PRELOAD.read_text(encoding="utf-8")
    terminal = TERMINAL.read_text(encoding="utf-8")
    kanaele = {"terminal-start", "terminal-write", "terminal-resize", "terminal-stop", "terminal-data", "terminal-exit"}
    for name in kanaele:
        assert f"'{name}'" in preload, f"{name} missing in preload.js"
        assert f"'{name}'" in terminal, f"{name} missing in terminal.js"
    assert "terminal:" in preload


def test_the_package_carries_the_native_module_and_the_two_modules():
    package = json.loads(PAKET.read_text(encoding="utf-8"))
    assert package["dependencies"]["node-pty"] == "1.1.0"
    assert "@electron/rebuild" in package["devDependencies"]
    assert "node-pty" in package["scripts"]["postinstall"]
    assert "terminal.js" in package["build"]["files"]
    assert "dienstsuche.js" in package["build"]["files"]
    assert any("node-pty" in pattern for pattern in package["build"]["asarUnpack"])


# --- dienstsuche.js: the note and the page --------------------------------


def test_the_data_root_is_resolved_the_way_the_service_resolves_it():
    skript = f"""
const d = require({json.dumps(str(DIENSTSUCHE))})
console.log(JSON.stringify({{
  own: d.dataRoot({{ env: {{ EXE_AI_DATEN: '/own/folder ' }}, packaged: true, platform: 'darwin', home: '/Users/x' }}),
  source: d.dataRoot({{ env: {{}}, packaged: false, repoRoot: '/repo' }}),
  mac: d.dataRoot({{ env: {{}}, packaged: true, platform: 'darwin', home: '/Users/x' }}),
  win: d.dataRoot({{ env: {{}}, packaged: true, platform: 'win32', home: 'C:\\\\Users\\\\x' }}),
  linux: d.dataRoot({{ env: {{}}, packaged: true, platform: 'linux', home: '/home/x' }}),
  note: d.noteFile('/root', 8090),
}}))
"""
    ergebnis = _slashes(_laufe(skript))
    assert ergebnis["own"] == "/own/folder"
    assert ergebnis["source"] == "/repo"
    assert ergebnis["mac"] == "/Users/x/Library/Application Support/Exe AI Terminal"
    assert ergebnis["win"].endswith("Exe AI Terminal") and "Roaming" in ergebnis["win"]
    assert ergebnis["linux"] == "/home/x/.local/share/exe-ai-terminal"
    assert ergebnis["note"] == "/root/data/.dienst-8090.json"


_LOOKUP = """
const d = require(%(modul)s)
const fs = require('fs')
const http = require('http')
const path = require('path')
const root = %(root)s
fs.mkdirSync(path.join(root, 'data'), { recursive: true })
const server = http.createServer((request, answer) => {
  if (request.url === '/app/' && %(answers)s) { answer.writeHead(200, { 'content-type': 'text/html' }); answer.end('<html></html>') }
  else { answer.writeHead(404); answer.end() }
})
server.listen(0, '127.0.0.1', async () => {
  const port = server.address().port
  %(note)s
  const found = await d.runningService({ port, root })
  server.close()
  console.log(JSON.stringify({ found, port, pid: process.pid }))
})
"""


def _lookup(tmp_path: Path, *, note: str, answers: str = "true") -> dict:
    skript = _LOOKUP % {
        "modul": json.dumps(str(DIENSTSUCHE)),
        "root": json.dumps(str(tmp_path)),
        "note": note,
        "answers": answers,
    }
    return _laufe(skript)


def test_a_note_for_the_port_and_an_answering_page_name_the_running_service(tmp_path):
    ergebnis = _lookup(
        tmp_path,
        note="fs.writeFileSync(d.noteFile(root, port), JSON.stringify({ pid: process.pid, port }))",
    )
    assert ergebnis["found"] == {"pid": ergebnis["pid"], "port": ergebnis["port"]}


def test_without_a_note_nothing_is_found_even_where_the_page_answers(tmp_path):
    """The silence probe: an answering port without a note is not known to
    be ours, and the shell goes on the way it always did."""
    ergebnis = _lookup(tmp_path, note="")
    assert ergebnis["found"] is None


def test_a_note_whose_page_does_not_answer_names_nobody(tmp_path):
    ergebnis = _lookup(
        tmp_path,
        note="fs.writeFileSync(d.noteFile(root, port), JSON.stringify({ pid: process.pid, port }))",
        answers="false",
    )
    assert ergebnis["found"] is None


def test_a_note_for_another_port_or_half_a_note_names_nobody(tmp_path):
    other = _lookup(
        tmp_path,
        note="fs.writeFileSync(d.noteFile(root, port), JSON.stringify({ pid: process.pid, port: port + 1 }))",
    )
    assert other["found"] is None
    half = _lookup(tmp_path, note="fs.writeFileSync(d.noteFile(root, port), '{\"pid\": 31')")
    assert half["found"] is None


def test_a_note_whose_process_is_gone_names_nobody(tmp_path):
    """A crashed service leaves its note behind; whatever answers on the
    port now is not it."""
    skript = f"""
const d = require({json.dumps(str(DIENSTSUCHE))})
const fs = require('fs')
const path = require('path')
const root = {json.dumps(str(tmp_path))}
fs.mkdirSync(path.join(root, 'data'), {{ recursive: true }})
fs.writeFileSync(d.noteFile(root, 8123), JSON.stringify({{ pid: 31337, port: 8123 }}))
Promise.all([
  d.runningService({{ port: 8123, root, answers: async () => true, alive: () => false }}),
  d.runningService({{ port: 8123, root, answers: async () => true, alive: () => true }}),
]).then(([gone, there]) => console.log(JSON.stringify({{
  gone, there, self: d.processAlive(process.pid), nobody: d.processAlive(2147483646),
}})))
"""
    ergebnis = _laufe(skript)
    assert ergebnis["gone"] is None
    assert ergebnis["there"] == {"pid": 31337, "port": 8123}
    assert ergebnis["self"] is True
    assert ergebnis["nobody"] is False


def test_a_silent_port_is_a_silent_service():
    skript = f"""
const d = require({json.dumps(str(DIENSTSUCHE))})
const net = require('net')
const server = net.createServer(() => {{}})
server.listen(0, '127.0.0.1', async () => {{
  const taken = server.address().port
  server.close()
  const refused = await d.pageAnswers(taken, {{ timeout: 500 }})
  console.log(JSON.stringify({{ refused }}))
}})
"""
    ergebnis = _laufe(skript)
    assert ergebnis["refused"] is False


# --- main.js: the window uses the service it finds -------------------------


def _dienstAnbinden() -> str:
    quelle = MAIN.read_text(encoding="utf-8")
    return "\n".join([
        _stueck(quelle, r"\nlet dienstVorgefunden = null\n", "dienstVorgefunden"),
        _stueck(quelle, r"\nasync function dienstAnbinden\(\) \{\n.*?\n\}\n", "dienstAnbinden"),
    ])


def _anbinden_mit_dienst(*, stop: str = "ok") -> dict:
    """`dienstAnbinden` with a service of ours found on the port. `stop`: how
    the end of that service goes — `ok`, or `refused` (it cannot be ended and
    stays). The window never asks which version it is."""
    skript = f"""
const path = require('path')
const PORT = 8123
const app = {{ isPackaged: false, getVersion: () => '0.6.11' }}
const asked = []
const dienstsuche = {{
  dataRoot: () => '/root',
  runningService: async () => ({{ pid: 31337, port: 8123 }}),
}}
const logged = []
const errors = []
console.log = (line) => logged.push(line)
console.error = (line) => errors.push(line)
async function endFoundService(running) {{
  asked.push(['end', running.pid])
  if ({json.dumps(stop)} === 'refused') throw new Error('the system refused the signal')
  return 'stopped'
}}
{_dienstAnbinden()}
dienstAnbinden().then((attached) => {{
  process.stdout.write(JSON.stringify({{ attached, logged, errors, asked, dienstVorgefunden }}) + '\\n')
}})
"""
    return _laufe(skript)


def _anbinden(gefunden: str) -> dict:
    skript = f"""
const path = require('path')
const PORT = 8123
const app = {{ isPackaged: false, getVersion: () => '0.6.11' }}
const asked = []
const dienstsuche = {{
  dataRoot: (options) => {{ asked.push(['root', options.packaged]); return '/root' }},
  runningService: async (options) => {{ asked.push(['service', options.port, options.root]); return {gefunden} }},
}}
const logged = []
console.log = (line) => logged.push(line)
async function endFoundService(running) {{ asked.push(['end', running.pid]); return 'stopped' }}
{_dienstAnbinden()}
dienstAnbinden().then((attached) => {{
  process.stdout.write(JSON.stringify({{ attached, logged, asked, dienstVorgefunden }}) + '\\n')
}})
"""
    return _laufe(skript)


def test_with_a_running_service_the_window_ends_it_and_does_not_attach():
    ergebnis = _anbinden("{ pid: 31337, port: 8123 }")
    assert ergebnis["attached"] is False
    assert ergebnis["dienstVorgefunden"] is None
    assert ergebnis["asked"] == [["root", False], ["service", 8123, "/root"], ["end", 31337]]


def test_without_a_running_service_the_window_starts_its_own_as_before():
    """The silence probe: nothing found, nothing attached, no line — and
    the start that follows is the one the shell always made."""
    ergebnis = _anbinden("null")
    assert ergebnis["attached"] is False
    assert ergebnis["dienstVorgefunden"] is None
    assert ergebnis["logged"] == []


def test_the_shell_asks_before_it_starts_and_lets_a_found_service_stand():
    quelle = MAIN.read_text(encoding="utf-8")
    assert "if (!(await dienstAnbinden())) await dienstStarten()" in quelle
    vor_dem_ende = _stueck(quelle, r"\napp\.on\('before-quit', \(\) => \{\n.*?\n\}\)\n", "before-quit")
    assert "terminals.stopAll()" in vor_dem_ende
    assert "dienstVorgefunden" in vor_dem_ende
    # The found service is never `kind`, so the stop below never reaches it.
    assert "dienstVorgefunden = gefunden" in quelle
    assert "kind = gefunden" not in quelle


def test_a_running_service_of_ours_is_always_ended_and_the_window_starts_its_own():
    """Falls over without the fix: a service of the same version — every test
    build is called 0.6.13 — or one whose version could not be read was used
    as it was found."""
    ergebnis = _anbinden_mit_dienst()
    assert ergebnis["attached"] is False
    assert ergebnis["dienstVorgefunden"] is None
    assert ergebnis["asked"] == [["end", 31337]]
    assert len(ergebnis["logged"]) == 2
    assert "is running on port 8123 (pid 31337); ending it, this program starts its own" in ergebnis["logged"][0]
    assert "ended (pid 31337; stopped); this program starts its own" in ergebnis["logged"][1]
    assert ergebnis["errors"] == []


def test_the_window_never_asks_which_version_the_running_service_is():
    quelle = MAIN.read_text(encoding="utf-8")
    assert "serviceVersion" not in quelle
    assert "serviceVersion" not in DIENSTSUCHE.read_text(encoding="utf-8")


def test_a_service_that_cannot_be_ended_stays_in_use_and_the_reason_is_logged():
    ergebnis = _anbinden_mit_dienst(stop="refused")
    assert ergebnis["attached"] is True
    assert ergebnis["dienstVorgefunden"] == {"pid": 31337, "port": 8123}
    assert len(ergebnis["errors"]) == 1
    assert "did not end, it is used as it is: the system refused the signal" in ergebnis["errors"][0]


# --- main.js: how the found service is ended --------------------------------


def _endFoundService() -> str:
    quelle = MAIN.read_text(encoding="utf-8")
    return "\n".join([
        _stueck(quelle, r"\nfunction signalProcess\(pid, signal\) \{\n.*?\n\}\n", "signalProcess"),
        _stueck(quelle, r"\nasync function endFoundService\(running\) \{\n.*?\n\}\n", "endFoundService"),
    ])


def _end_found(*, client: str, lives: str) -> dict:
    """`endFoundService` for a process 4242. `client`: `ok` or `fails` (the
    client's stop). `lives`: when the process is gone — `now` (with the
    client's stop), `after-term` (once SIGTERM reached it), `after-kill`
    (only SIGKILL ends it), `never`. The constants are shortened so the test
    runs in a second; the shapes are the real ones."""
    skript = f"""
const KILL_AFTER_MS = 400
const LOOK_PAUSE_MS = 20
const signals = []
let alive = {json.dumps(lives != "now")}
process.kill = (pid, signal) => {{
  signals.push([pid, signal])
  if (signal === 'SIGTERM' && {json.dumps(lives)} === 'after-term') alive = false
  if (signal === 'SIGKILL' && {json.dumps(lives)} === 'after-kill') alive = false
}}
const dienstsuche = {{ processAlive: () => alive }}
async function clientStop() {{
  if ({json.dumps(client)} === 'fails') throw new Error('exe service stop: 1')
  return 'stopped'
}}
{_endFoundService()}
endFoundService({{ pid: 4242, port: 8123 }}).then(
  (words) => process.stdout.write(JSON.stringify({{ words, signals, rejected: null }}) + '\\n'),
  (failure) => process.stdout.write(JSON.stringify({{ words: null, signals, rejected: failure.message }}) + '\\n'),
)
"""
    return _laufe(skript)


def test_a_service_the_client_ends_gets_no_signal():
    """Silence probe: the client's stop works and the process is gone — the
    window sends nothing to anybody."""
    ergebnis = _end_found(client="ok", lives="now")
    assert ergebnis["signals"] == []
    assert ergebnis["words"] == "stopped"


def test_where_the_clients_stop_fails_the_process_is_asked_to_end_by_its_id():
    ergebnis = _end_found(client="fails", lives="after-term")
    assert ergebnis["signals"] == [[4242, "SIGTERM"]]
    assert "the client's stop failed (exe service stop: 1)" in ergebnis["words"]


def test_a_process_that_lives_on_is_killed_after_the_wait():
    ergebnis = _end_found(client="fails", lives="after-kill")
    assert ergebnis["signals"] == [[4242, "SIGTERM"], [4242, "SIGKILL"]]
    assert "ended by force" in ergebnis["words"]


def test_a_process_the_client_could_not_end_is_killed_without_a_second_term():
    ergebnis = _end_found(client="ok", lives="after-kill")
    assert ergebnis["signals"] == [[4242, "SIGKILL"]]


def test_a_process_that_survives_everything_rejects():
    ergebnis = _end_found(client="fails", lives="never")
    assert ergebnis["signals"] == [[4242, "SIGTERM"], [4242, "SIGKILL"]]
    assert "pid 4242 is still alive after SIGKILL" in ergebnis["rejected"]


def test_the_wait_before_the_kill_is_five_seconds():
    assert re.search(r"const KILL_AFTER_MS = 5000\n", MAIN.read_text(encoding="utf-8"))


def test_the_start_and_the_update_both_begin_with_the_clients_stop():
    """One way in: the stop of an update and the stop at the start both run
    the client's `service stop`; the start adds the process id and the kill
    for the service the client cannot end, the update waits as long as it
    lives."""
    quelle = MAIN.read_text(encoding="utf-8")
    assert len(re.findall(r"await endRunningService\(", quelle)) == 1
    assert len(re.findall(r"await endFoundService\(", quelle)) == 1
    assert re.search(r"async function endRunningService\(running\) \{.*?clientStop\(\).*?processAlive", quelle, re.S)
    assert re.search(r"async function endFoundService\(running\) \{.*?clientStop\(\).*?processAlive", quelle, re.S)
