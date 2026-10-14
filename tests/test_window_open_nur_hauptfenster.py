"""A foreign address from ``window.open`` goes to the browser only from the
main window.

A script in a document window used to call ``window.open`` with a foreign
address in a loop, and the shell opened one browser tab after another: the
window rule (``fensterweiche`` in fenster-electron/main.js) sent every foreign
address out without a person's click behind it. Now only the main window's
page — the program's own code, the buttons to a model's page and to an MCP
server's page — may. Any other content is denied and opens nothing; what a
person clicks goes out through the click catcher (linkclicks.js).

``main.js`` requires electron and cannot run outside a packaged window, so
the two functions under test are cut out of its source by name and run for
real in node, with stand-ins for what they touch (the same detour
tests/test_huelle_windows.py takes).
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

SHELL = Path(__file__).resolve().parents[1] / "fenster-electron" / "main.js"


def _piece(pattern: str, name: str) -> str:
    match = re.search(pattern, SHELL.read_text(encoding="utf-8"), re.S)
    assert match, f"{name} not found"
    return match.group(0).strip() + "\n"


def _run(script: str) -> Any:
    if not shutil.which("node"):
        pytest.skip("node is missing")
    run = subprocess.run(
        ["node", "-e", script], capture_output=True, text=True, encoding="utf-8",
        errors="replace", timeout=30,
    )
    assert run.returncode == 0, (run.stdout + run.stderr)[-3000:]
    return json.loads(run.stdout.strip().splitlines()[-1])


@pytest.fixture(scope="module")
def answer() -> dict[str, Any]:
    pieces = "\n".join([
        _piece(r"\nfunction istHauptfenster\(inhalt\) \{\n.*?\n\}\n", "istHauptfenster"),
        _piece(r"\nfunction fensterweiche\(\{ url \}, inhalt\) \{\n.*?\n\}\n", "fensterweiche"),
    ])
    script = f"""
const out = []
const MAIN = {{ name: 'main' }}
const DOC = {{ name: 'document window' }}
const MANUAL = {{ name: 'manual' }}
let fenster = {{ isDestroyed: () => false, webContents: MAIN }}
let hilfefenster = null
function istEigeneSeite(address) {{ return address.startsWith('http://127.0.0.1:8090/') }}
function istHandbuch(address) {{ return address.includes('/hilfe/') }}
function nachDraussen(address) {{ out.push(address) }}
function menuBarOptions() {{ return {{}} }}
const regel = {{ addressForLog: (address) => address }}
{pieces}
const ask = (url, content) => {{
  out.length = 0
  const verdict = fensterweiche({{ url }}, content)
  return {{ verdict: verdict.action, opened: out.slice(), options: verdict.overrideBrowserWindowOptions ?? null }}
}}
const result = {{
  from_main: ask('https://huggingface.co/x', MAIN),
  from_document: ask('https://example.com/', DOC),
  from_manual: ask('https://example.com/', MANUAL),
  from_nothing: ask('https://example.com/', undefined),
  own_from_document: ask('http://127.0.0.1:8090/api/v1/ablage/x.pdf', DOC),
  own_manual: ask('http://127.0.0.1:8090/hilfe/', MANUAL),
}}
// The loop that used to open a tab per call.
out.length = 0
for (let i = 0; i < 3; i++) fensterweiche({{ url: 'https://example.com/' + i }}, DOC)
result.loop_from_document = out.slice()
// The main window gone: nothing counts as the main window any more.
fenster = {{ isDestroyed: () => true, webContents: MAIN }}
result.main_destroyed = ask('https://huggingface.co/x', MAIN)
fenster = null
result.no_main_window = ask('https://huggingface.co/x', MAIN)
console.log(JSON.stringify(result))
"""
    return _run(script)


def test_a_foreign_address_goes_to_the_browser_from_the_main_window(answer):
    assert answer["from_main"] == {
        "verdict": "deny", "opened": ["https://huggingface.co/x"], "options": None,
    }


def test_no_other_content_opens_a_foreign_address(answer):
    """A document window, the manual and a call without a content are
    denied and open nothing — and a loop opens no tab at all."""
    for name in ("from_document", "from_manual", "from_nothing"):
        assert answer[name] == {"verdict": "deny", "opened": [], "options": None}, name
    assert answer["loop_from_document"] == []


def test_without_a_live_main_window_nothing_is_the_main_window(answer):
    for name in ("main_destroyed", "no_main_window"):
        assert answer[name] == {"verdict": "deny", "opened": [], "options": None}, name


def test_silence_an_own_address_opens_as_before(answer):
    """A document or a script of ours in a window of its own, and the manual,
    are decided as they were: the new rule touches foreign addresses only."""
    assert answer["own_from_document"]["verdict"] == "allow"
    assert answer["own_from_document"]["opened"] == []
    assert answer["own_from_document"]["options"] == {"width": 900, "height": 720}
    assert answer["own_manual"]["verdict"] == "allow"
    assert answer["own_manual"]["options"]["title"] == "Exe AI — Help"
