"""One program at a time: the Electron shell takes the single-instance lock
before it builds a window or starts a service. A second start quits at once;
the first instance is told and brings its window forward, restored if it was
minimised. A second instance, which holds neither window nor service, is let
out of before-quit without a wait.

`fenster-electron/main.js` requires electron and cannot run outside a
packaged window, so the pieces under test are cut from its source by name
and run for real in node, with thin stand-ins for `app` and the window.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
SHELL = ROOT / "fenster-electron" / "main.js"


def _source() -> str:
    return SHELL.read_text(encoding="utf-8")


def _piece(pattern: str, name: str) -> str:
    match = re.search(pattern, _source(), re.S)
    assert match, f"{name} not found"
    return match.group(0).strip() + "\n"


def _run(script: str) -> Any:
    if not shutil.which("node"):
        pytest.skip("node is missing")
    run = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=30)
    assert run.returncode == 0, (run.stdout + run.stderr)[-3000:]
    return json.loads(run.stdout.strip().splitlines()[-1])


def _lock_pieces() -> str:
    return "\n".join([
        _piece(r"\nfunction bringWindowForward\(\) \{\n.*?\n\}\n", "bringWindowForward"),
        _piece(r"\nif \(app\.requestSingleInstanceLock\(\)\) \{\n.*?\n\}\n", "the lock"),
    ])


def _quit_pieces() -> str:
    return "\n".join([
        _piece(r"\nfunction stopService\(service\) \{\n.*?\n\}\n", "stopService"),
        _piece(r"\nfunction killService\(service\) \{\n.*?\n\}\n", "killService"),
        _piece(r"\napp\.on\('before-quit', async \(ereignis\) => \{\n.*?\n\}\)\n", "before-quit"),
    ])


def _start(*, lock: bool, minimised: bool = False, window: bool = True) -> dict:
    """Runs the start of the shell with the lock granted or refused, then —
    if the first instance listens for it — a second start."""
    script = f"""
const calls = []
const listeners = {{}}
const app = {{
  requestSingleInstanceLock: () => {str(lock).lower()},
  on(name, f) {{ listeners[name] = f }},
  whenReady: () => ({{ then() {{ calls.push('whenReady') }} }}),
  quit: () => calls.push('quit'),
}}
console.log = () => {{}}
const fenster = {str(window).lower()} ? {{
  isDestroyed: () => false,
  isMinimized: () => {str(minimised).lower()},
  restore: () => calls.push('restore'),
  show: () => calls.push('show'),
  focus: () => calls.push('focus'),
}} : null
{_lock_pieces()}
const listening = Object.keys(listeners).sort()
if (listeners['second-instance']) listeners['second-instance']()
process.stdout.write(JSON.stringify({{ calls, listening }}) + "\\n")
"""
    return _run(script)


def test_a_second_start_quits_before_a_window_or_a_service_exists():
    """Refused the lock, the shell neither waits for ready nor listens for
    anything: it quits, and that is all it does."""
    assert _start(lock=False) == {"calls": ["quit"], "listening": []}


def test_the_first_instance_starts_and_listens_for_a_second_start():
    """The silence probe: with the lock the start is the start as before, plus
    the one listener — and a second start raises the window."""
    result = _start(lock=True)
    assert result["listening"] == ["second-instance"]
    assert result["calls"] == ["whenReady", "show", "focus"]


def test_a_second_start_restores_a_minimised_window_first():
    assert _start(lock=True, minimised=True)["calls"] == ["whenReady", "restore", "show", "focus"]


def test_a_second_start_before_the_window_exists_raises_nothing():
    assert _start(lock=True, window=False)["calls"] == ["whenReady"]


def test_the_lock_is_taken_before_ready_and_before_any_window():
    """Read off the source: the lock stands at module level, ahead of the
    whenReady that builds the window and starts the service — not inside it."""
    source = _source()
    lock = source.index("app.requestSingleInstanceLock()")
    ready = source.index("app.whenReady()")
    assert lock < ready
    inside = source[lock:ready]
    assert "fensterBauen()" not in inside and "dienstStarten()" not in inside


def test_a_second_instance_leaves_before_quit_without_a_wait():
    """A second instance holds no window and no service: before-quit neither
    holds the quit nor ends anything — the quit simply goes through."""
    script = f"""
const calls = []
process.kill = (pid, signal) => calls.push(['kill', pid, signal])
function execFile(command, args) {{ calls.push(['taskkill', command, args]) }}
const STOP_DEADLINE_MS = 50
let fenster = null
function geometrieSchreiben() {{ calls.push('geometry') }}
let beendet = false
let stopping = false
let kind = null
let prevented = false
const app = {{ hooks: {{}}, on(name, f) {{ this.hooks[name] = f }}, exit: (code) => calls.push(['exit', code]) }}
{_quit_pieces()}
app.hooks['before-quit']({{ preventDefault() {{ prevented = true }} }}).then(() => {{
  process.stdout.write(JSON.stringify({{ calls, prevented, beendet }}) + "\\n")
}})
"""
    assert _run(script) == {"calls": [], "prevented": False, "beendet": True}
