"""The Windows side of the Electron shell: the service's path inside its
folder, the menu without the macOS role, the hidden menu bar in every window,
and the end of the whole process tree on quit — each run with the platform
set to win32, and each with its silence probe under darwin, where nothing may
change. Alongside: the packer's Windows target and the build description's
folder build.

`fenster-electron/main.js` requires electron and cannot run outside a
packaged window, so the functions under test are extracted from its source by
name and run for real in node (the way the shell's existing test module does),
with the platform set on `process` and thin stand-ins for the electron and
child_process calls each one touches.

The build description (deploy/exe-ai-terminal.spec) runs as the spec it is,
with PyInstaller's build classes replaced by recorders: what EXE and COLLECT
are handed decides whether the service is one file or a folder.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
SHELL = ROOT / "fenster-electron" / "main.js"
PACKAGE = ROOT / "fenster-electron" / "package.json"
SERVICE_SPEC = ROOT / "deploy" / "exe-ai-terminal.spec"


def _source() -> str:
    return SHELL.read_text(encoding="utf-8")


def _piece(pattern: str, name: str) -> str:
    match = re.search(pattern, _source(), re.S)
    assert match, f"{name} not found"
    return match.group(0).strip() + "\n"


def _run(script: str) -> Any:
    if not shutil.which("node"):
        pytest.skip("node is missing")
    # Node writes UTF-8 whatever the console's code page is: the help
    # window's title carries a dash outside ASCII, and read as the system's
    # own page it came back as three other characters (measured on Windows).
    run = subprocess.run(
        ["node", "-e", script], capture_output=True, text=True, encoding="utf-8",
        errors="replace", timeout=30,
    )
    assert run.returncode == 0, (run.stdout + run.stderr)[-3000:]
    return json.loads(run.stdout.strip().splitlines()[-1])


def _platform(name: str) -> str:
    """process.platform cannot be assigned, only redefined."""
    return f"Object.defineProperty(process, 'platform', {{ value: {json.dumps(name)} }})"


# The pieces of main.js under test, by name — outside the scripts below,
# because an f-string expression may not carry a backslash.


def _service_path_piece() -> str:
    return _piece(r"\nfunction dienstpfad\(\) \{\n.*?\n\}\n", "dienstpfad")


def _menu_piece() -> str:
    return _piece(r"\nfunction menueSetzen\(\) \{\n.*?\n\}\n", "menueSetzen")


def _window_pieces() -> str:
    return "\n".join([
        _piece(r"\nfunction menuBarOptions\(\) \{\n.*?\n\}\n", "menuBarOptions"),
        _piece(r"\nfunction fensterweiche\(\{ url \}\) \{\n.*?\n\}\n", "fensterweiche"),
        _piece(r"\nfunction fensterBauen\(\) \{\n.*?\n\}\n", "fensterBauen"),
    ])


def _quit_pieces() -> str:
    return "\n".join([
        _piece(r"\nfunction stopService\(service\) \{\n.*?\n\}\n", "stopService"),
        _piece(r"\nfunction killService\(service\) \{\n.*?\n\}\n", "killService"),
        _piece(r"\napp\.on\('before-quit', async \(ereignis\) => \{\n.*?\n\}\)\n", "before-quit"),
    ])


# --- the service's path: on Windows the exe inside its folder ---------------


def _service_path(platform: str, *, packaged: bool, override: str | None = None) -> str:
    if platform == "win32":
        resources, flavour = "C:\\Programme\\Exe AI\\resources", "win32"
    else:
        resources, flavour = "/Programme/Exe AI.app/Contents/Resources", "posix"
    env = (
        f"process.env.EXE_AI_DIENST = {json.dumps(override)}"
        if override else "delete process.env.EXE_AI_DIENST"
    )
    script = f"""
{_platform(platform)}
{env}
// Joined the way the platform under test joins paths, not the way this machine does.
const path = require('path').{flavour}
process.resourcesPath = {json.dumps(resources)}
const app = {{ isPackaged: {str(packaged).lower()} }}
{_service_path_piece()}
console.log(JSON.stringify(dienstpfad()))
"""
    return _run(script)


def test_packaged_on_windows_the_service_is_the_exe_inside_its_folder():
    assert _service_path("win32", packaged=True) == (
        "C:\\Programme\\Exe AI\\resources\\exe-ai-terminal\\Exe AI.exe"
    )


def test_from_source_on_windows_the_service_is_the_exe_inside_dist():
    assert _service_path("win32", packaged=False).endswith("\\dist\\Exe AI\\Exe AI.exe")


def test_on_macos_the_service_path_is_the_one_file_as_before():
    """The silence probe: nothing is appended on macOS, packaged or not."""
    assert _service_path("darwin", packaged=True) == (
        "/Programme/Exe AI.app/Contents/Resources/exe-ai-terminal"
    )
    assert _service_path("darwin", packaged=False).endswith("/dist/Exe AI")


def test_the_override_wins_on_windows_too():
    assert _service_path("win32", packaged=True, override="D:\\own\\service.exe") == (
        "D:\\own\\service.exe"
    )


# --- the menu: the appMenu role on macOS only -------------------------------


def _menu_roles(platform: str) -> list:
    script = f"""
{_platform(platform)}
let applied = null
const Menu = {{
  buildFromTemplate: (template) => template,
  setApplicationMenu: (menu) => {{ applied = menu }},
}}
{_menu_piece()}
menueSetzen()
console.log(JSON.stringify(applied.map((item) => item.role || item.label)))
"""
    return _run(script)


def test_on_windows_the_menu_carries_no_app_menu_role():
    assert _menu_roles("win32") == ["editMenu", "View", "windowMenu"]


def test_on_macos_the_menu_starts_with_the_app_menu_as_before():
    assert _menu_roles("darwin") == ["appMenu", "editMenu", "View", "windowMenu"]


# --- every window: the bar hidden on Windows, no such option on macOS -------


def _windows(platform: str) -> dict:
    script = f"""
{_platform(platform)}
const path = require('path')
const BREITE = 1280, HOEHE = 820, MIN_BREITE = 720, MIN_HOEHE = 480
function geometrieLesen() {{ return null }}
function geometrieSchreiben() {{}}
function frameColourRead() {{ return null }}
function frameSchemeRead() {{ return null }}
function frameSchemeApply() {{ return false }}
let dienstFehlgeschlagen = false
function fehlstartSchreiben() {{}}
let fenster = null
let hilfefenster = null
const app = {{ quit() {{}} }}
const built = []
class BrowserWindow {{
  constructor(options) {{ built.push(options); this.webContents = {{ on() {{}} }} }}
  loadFile() {{}}
  on() {{}}
}}
function istEigeneSeite() {{ return true }}
function istHandbuch(address) {{ return address.includes('/hilfe/') }}
function nachDraussen() {{}}
{_window_pieces()}
fensterBauen()
const manual = fensterweiche({{ url: 'http://127.0.0.1:8090/hilfe/' }})
const doc = fensterweiche({{ url: 'http://127.0.0.1:8090/api/v1/ablage/x.pdf' }})
console.log(JSON.stringify({{
  main: built[0],
  manual: manual.overrideBrowserWindowOptions,
  doc: doc.overrideBrowserWindowOptions,
}}))
"""
    return _run(script)


def test_on_windows_every_window_of_the_shell_hides_its_menu_bar():
    windows = _windows("win32")
    assert windows["main"]["autoHideMenuBar"] is True
    assert windows["manual"] == {
        "width": 880, "height": 720, "title": "Exe AI — Help", "autoHideMenuBar": True,
    }
    assert windows["doc"] == {"width": 900, "height": 720, "autoHideMenuBar": True}


def test_on_macos_no_window_gets_the_menu_bar_option():
    """The silence probe: the three windows open with the options they had."""
    windows = _windows("darwin")
    assert "autoHideMenuBar" not in windows["main"]
    assert windows["manual"] == {"width": 880, "height": 720, "title": "Exe AI — Help"}
    assert windows["doc"] == {"width": 900, "height": 720}


# --- quitting: the whole process tree on Windows, SIGTERM on macOS ----------


def _quit(platform: str, *, service_ends: bool, taskkill_fails: bool = False) -> dict:
    """Runs the quit handler with a service stand-in that ends after 5 ms or
    never, against a deadline of 300 ms — wide enough that a loaded machine
    cannot push the one case over the line of the other."""
    script = f"""
{_platform(platform)}
const STOP_DEADLINE_MS = 300
const calls = {{ kill: [], taskkill: [], childKill: [] }}
process.kill = (pid, signal) => {{ calls.kill.push([pid, signal]) }}
function execFile(command, args, done) {{
  calls.taskkill.push([command, args])
  done({str(taskkill_fails).lower()} ? new Error('taskkill: not found') : null)
}}
let fenster = null
function geometrieSchreiben() {{}}
let beendet = false
let stopping = false
let onExit = null
let kind = {{
  pid: 4242,
  once(event, f) {{ if (event === 'exit') onExit = f }},
  kill() {{ calls.childKill.push(4242) }},
}}
let exitCode = null
const app = {{
  hooks: {{}},
  on(name, f) {{ this.hooks[name] = f }},
  exit(code) {{ exitCode = code }},
}}
{_quit_pieces()}
const start = Date.now()
const quitting = app.hooks['before-quit']({{ preventDefault() {{}} }})
if ({str(service_ends).lower()}) setTimeout(() => onExit(), 5)
quitting.then(() => {{
  console.log(JSON.stringify({{ ...calls, exitCode, waitedMs: Date.now() - start }}))
}})
"""
    return _run(script)


TASKKILL = [["taskkill", ["/PID", "4242", "/T", "/F"]]]


def test_on_windows_quitting_ends_the_whole_process_tree_and_waits_for_it():
    result = _quit("win32", service_ends=True)
    assert result["taskkill"] == TASKKILL
    assert result["kill"] == [], "no process.kill on Windows — it would end the service alone, hard"
    assert result["childKill"] == [], "taskkill ran; nothing falls back"
    assert result["exitCode"] == 0
    assert result["waitedMs"] < 200, "the shell ends as soon as the service has ended"


def test_on_windows_a_service_that_does_not_end_does_not_hold_the_shell_past_the_deadline():
    result = _quit("win32", service_ends=False)
    assert result["taskkill"] == TASKKILL
    assert result["kill"] == [], "taskkill /F has already killed; there is no harder step"
    assert result["childKill"] == []
    assert result["exitCode"] == 0
    assert result["waitedMs"] >= 290


def test_on_windows_the_service_is_ended_alone_when_taskkill_cannot_run():
    """taskkill not on the path, or denied: the one way left is the hard end
    of the service itself — never silence."""
    result = _quit("win32", service_ends=True, taskkill_fails=True)
    assert result["taskkill"] == TASKKILL
    assert result["childKill"] == [4242]
    assert result["kill"] == []
    assert result["exitCode"] == 0


def test_on_macos_quitting_sends_sigterm_and_never_taskkill():
    """The silence probe: SIGTERM, and after the deadline SIGKILL, as before."""
    ended = _quit("darwin", service_ends=True)
    assert ended["kill"] == [[4242, "SIGTERM"]]
    assert ended["taskkill"] == []
    assert ended["exitCode"] == 0
    stuck = _quit("darwin", service_ends=False)
    assert stuck["kill"] == [[4242, "SIGTERM"], [4242, "SIGKILL"]]
    assert stuck["taskkill"] == []
    assert stuck["exitCode"] == 0


# --- the packer: a Windows installer beside the macOS image -----------------


def _package() -> dict:
    return json.loads(PACKAGE.read_text(encoding="utf-8"))


def test_the_shell_packs_an_installer_for_windows():
    package = _package()
    build = package["build"]
    assert build["win"] == {
        "target": [{"target": "nsis", "arch": ["x64"]}],
        "icon": "../deploy/icon.ico",
    }
    assert (ROOT / "deploy" / "icon.ico").is_file()
    # The installer keeps electron-builder's defaults; only its file name
    # follows the pattern of the DMG.
    assert build["nsis"] == {"artifactName": "Exe-AI-${version}-${arch}.exe"}
    assert package["scripts"]["pack:win"] == "electron-builder --win --publish never"


def test_the_macos_build_is_untouched():
    """The silence probe: the Windows installer changes nothing about the mac
    and dmg blocks or the two mac scripts, and the service ships under the
    same resources name on both systems — the one file on macOS, the folder
    on Windows."""
    package = _package()
    build = package["build"]
    assert build["mac"]["target"] == ["dmg", "zip"]
    assert build["dmg"] == {"artifactName": "Exe-AI-${version}-${arch}.dmg"}
    assert package["scripts"]["bauen"] == "CSC_IDENTITY_AUTO_DISCOVERY=false electron-builder --mac --dir"
    assert package["scripts"]["packen"] == "electron-builder --mac --publish never"
    assert {"from": "../dist/Exe AI", "to": "exe-ai-terminal"} in build["extraResources"]


# --- the build description: one file on macOS, a folder on Windows ----------


def _spec_calls(monkeypatch: pytest.MonkeyPatch, platform: str) -> dict[str, list]:
    hooks = pytest.importorskip("PyInstaller.utils.hooks")
    # Imported before the platform changes: PyInstaller reads sys.platform
    # once, on import. The time-zone data is a package of its own and not what
    # this test is about.
    monkeypatch.setattr(hooks, "collect_data_files", lambda name: [])
    monkeypatch.setattr(sys, "platform", platform)
    calls: dict[str, list] = {"EXE": [], "COLLECT": [], "BUNDLE": []}

    def recorder(name: str):
        def build(*args, **kwargs):
            calls[name].append((args, kwargs))
            return name
        return build

    class Analysis:
        def __init__(self, *args, **kwargs):
            self.scripts = ["scripts"]
            self.binaries = ["binaries"]
            self.datas = ["datas"]
            self.pure = ["pure"]

    namespace = {
        "SPECPATH": str(SERVICE_SPEC.parent),
        "Analysis": Analysis,
        "PYZ": lambda pure: "pyz",
        "EXE": recorder("EXE"),
        "COLLECT": recorder("COLLECT"),
        "BUNDLE": recorder("BUNDLE"),
    }
    exec(compile(SERVICE_SPEC.read_text(encoding="utf-8"), str(SERVICE_SPEC), "exec"), namespace)  # noqa: S102 - the spec is ours
    return calls


def test_on_windows_the_service_is_built_as_a_folder(monkeypatch):
    calls = _spec_calls(monkeypatch, "win32")
    ((exe_args, exe_kwargs),) = calls["EXE"]
    assert exe_args[:2] == ("pyz", ["scripts"])
    assert exe_args[2] == [] and exe_args[3] == [], "binaries and datas go to COLLECT, not into the exe"
    assert exe_kwargs["exclude_binaries"] is True
    assert exe_kwargs["name"] == "Exe AI"
    assert exe_kwargs["console"] is False
    assert exe_kwargs["icon"].endswith("icon.ico")
    ((coll_args, coll_kwargs),) = calls["COLLECT"]
    assert coll_args == ("EXE", ["binaries"], ["datas"])
    assert coll_kwargs["name"] == "Exe AI", "the folder's name is the path the shell starts"
    assert calls["BUNDLE"] == []


def test_on_macos_the_service_is_one_file_in_its_bundle_as_before(monkeypatch):
    """The silence probe."""
    calls = _spec_calls(monkeypatch, "darwin")
    ((exe_args, exe_kwargs),) = calls["EXE"]
    assert exe_args[2:4] == (["binaries"], ["datas"])
    assert exe_kwargs["exclude_binaries"] is False
    assert exe_kwargs["console"] is True
    assert exe_kwargs["icon"] is None
    assert calls["COLLECT"] == []
    ((bundle_args, bundle_kwargs),) = calls["BUNDLE"]
    assert bundle_args == ("EXE",)
    assert bundle_kwargs["name"] == "Exe AI Terminal.app"
