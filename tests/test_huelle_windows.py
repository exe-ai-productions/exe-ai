"""The Windows side of the Electron shell: the service's path inside its
folder, the menu without the macOS role, the hidden menu bar in every window,
and the quit that leaves the service running — each run with the platform
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
        _piece(r"\nfunction istHauptfenster\(inhalt\) \{\n.*?\n\}\n", "istHauptfenster"),
        _piece(r"\nfunction fensterweiche\(\{ url \}, inhalt\) \{\n.*?\n\}\n", "fensterweiche"),
        _piece(r"\nfunction fensterBauen\(\) \{\n.*?\n\}\n", "fensterBauen"),
    ])


def _quit_piece() -> str:
    return _piece(r"\napp\.on\('before-quit', \(\) => \{\n.*?\n\}\)\n", "before-quit")


def _start_piece() -> str:
    return _piece(r"\nasync function dienstStarten\(\) \{\n.*?\n\}\n", "dienstStarten")


# --- the service's path: the program inside its folder, on every system -----


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


def test_on_macos_the_service_is_the_program_inside_its_folder():
    """Falls over with the one-file path: the service is a folder there too,
    and the shell starts the program inside it, packaged or from source."""
    assert _service_path("darwin", packaged=True) == (
        "/Programme/Exe AI.app/Contents/Resources/exe-ai-terminal/Exe AI"
    )
    assert _service_path("darwin", packaged=False).endswith("/dist/Exe AI/Exe AI")


def test_the_override_wins_on_macos_too():
    assert _service_path("darwin", packaged=True, override="/own/service") == "/own/service"


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


# --- quitting: the service stays, on Windows as on macOS --------------------


def _quit(platform: str, *, found: bool = False, passes: int = 1) -> dict:
    """Runs the quit handler, once or more, with a service stand-in that
    records every way the shell could end it or wait for it — none of which
    may be taken, on either platform."""
    script = f"""
{_platform(platform)}
const PORT = 8123
const calls = {{ kill: [], childKill: [], waited: [], exit: [], terminals: 0, prevented: 0 }}
process.kill = (pid, signal) => {{ calls.kill.push([pid, signal]) }}
const logged = []
console.log = (line) => logged.push(line)
let fenster = null
function geometrieSchreiben() {{}}
let beendet = false
let dienstVorgefunden = {"{ pid: 31337, port: 8123 }" if found else "null"}
let bleibenGesagt = false
const terminals = {{ stopAll() {{ calls.terminals += 1 }} }}
let kind = {{
  pid: 4242,
  once(event) {{ calls.waited.push(event) }},
  on(event) {{ calls.waited.push(event) }},
  kill() {{ calls.childKill.push(4242) }},
}}
const app = {{
  hooks: {{}},
  on(name, f) {{ this.hooks[name] = f }},
  exit(code) {{ calls.exit.push(code) }},
}}
{_quit_piece()}
for (let pass = 0; pass < {passes}; pass++) {{
  app.hooks['before-quit']({{ preventDefault() {{ calls.prevented += 1 }} }})
}}
process.stdout.write(JSON.stringify({{ ...calls, logged, beendet }}) + "\\n")
"""
    return _run(script)


def _leaves_the_service_running(result: dict) -> None:
    assert result["kill"] == [], "no signal to the service"
    assert result["childKill"] == [], "no kill on the child handle"
    assert result["waited"] == [], "no waiting for the service's end"
    assert result["exit"] == [], "no app.exit: the quit goes through as it came"
    assert result["prevented"] == 0
    assert result["beendet"] is True
    assert result["terminals"] == 1, "the terminals in the window end with it"


def test_on_windows_quitting_leaves_the_service_this_window_started_running():
    result = _quit("win32")
    _leaves_the_service_running(result)
    assert result["logged"] == [
        "Service: the service on port 8123 started by this window stays, for the terminal client and the next window"
    ]


def test_on_macos_quitting_leaves_the_service_this_window_started_running():
    """The silence probe across platforms: nothing is platform-specific any more."""
    result = _quit("darwin")
    _leaves_the_service_running(result)
    assert result["logged"] == [
        "Service: the service on port 8123 started by this window stays, for the terminal client and the next window"
    ]


def test_quitting_leaves_a_found_service_running_and_says_so_as_before():
    """The silence probe: a service this window only found was never ended,
    and its line stays what it was."""
    result = _quit("darwin", found=True)
    _leaves_the_service_running(result)
    assert result["logged"] == [
        "Service: the running service on port 8123 stays; this window did not start it"
    ]


def test_quitting_says_once_that_the_service_stays():
    """Closing the window runs before-quit twice; the line is said once."""
    assert len(_quit("win32", passes=2)["logged"]) == 1
    assert len(_quit("darwin", found=True, passes=2)["logged"]) == 1


def test_the_service_is_started_cut_loose_from_the_shell():
    """Read off the source: the service is spawned detached and unreferenced,
    so it outlives the shell on every platform — and the quit handler has no
    way left to end it or to wait for it."""
    start = _start_piece()
    assert "detached: true" in start
    assert "kind.unref()" in start
    quit_ = _quit_piece()
    for forbidden in ("kill", "taskkill", "'exit'", "exit(", "await", "preventDefault"):
        assert forbidden not in quit_, f"{forbidden} in before-quit"
    source = _source()
    for gone in ("stopService", "killService", "STOP_DEADLINE_MS", "execFile"):
        assert gone not in source, f"{gone} is still in the shell"


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
    same resources name on both systems — a folder on each."""
    package = _package()
    build = package["build"]
    assert build["mac"]["target"] == ["dmg", "zip"]
    assert build["dmg"] == {"artifactName": "Exe-AI-${version}-${arch}.dmg"}
    assert package["scripts"]["bauen"] == "CSC_IDENTITY_AUTO_DISCOVERY=false electron-builder --mac --dir"
    assert package["scripts"]["packen"] == "electron-builder --mac --publish never"
    assert {"from": "../dist/Exe AI", "to": "exe-ai-terminal"} in build["extraResources"]


# --- the packer: the command on the path, per system ------------------------

BUILD = ROOT / "fenster-electron" / "build"


def test_the_mac_app_carries_the_command_beside_the_service():
    """Contents/Resources/bin/exe — the file the links point at — next to
    the folder Contents/Resources/exe-ai-terminal, to whose program it hands
    over."""
    build = _package()["build"]
    assert {"from": "../deploy/exe", "to": "bin/exe"} in build["mac"]["extraResources"]
    assert (ROOT / "deploy" / "exe").read_text(encoding="utf-8").rstrip().endswith(
        'exec "$here/../exe-ai-terminal/Exe AI" --cli "$@"'
    )


def test_the_windows_installer_puts_the_command_on_the_users_path():
    """Read off the script the packer takes by its name: exe.cmd in a bin
    folder of its own, pointing at the client exe in the service folder, and
    that folder — not the service's — on the user's PATH."""
    script = (BUILD / "installer.nsh").read_text(encoding="utf-8")
    assert "!macro customInstall" in script and "!macro customUnInstall" in script
    assert 'FileOpen $R0 "$INSTDIR\\bin\\exe.cmd" w' in script
    assert "@\"%~dp0..\\resources\\exe-ai-terminal\\exe.exe\" %*" in script
    assert script.count('WriteRegExpandStr HKCU "Environment" "Path"') == 2
    assert 'HKLM' not in script, "the machine's PATH is not this installer's"


def test_the_windows_installer_never_writes_a_path_it_could_not_read_whole():
    """Every write of the PATH sits behind the two guards: the value was
    read whole, and the result still fits into one of the installer's
    strings. An update keeps the PATH; only an uninstall takes the folder
    out. Each pass of the build declares only the string function it calls."""
    script = (BUILD / "installer.nsh").read_text(encoding="utf-8")
    install = script.split("!macro customInstall", 1)[1].split("!macroend", 1)[0]
    uninstall = script.split("!macro customUnInstall", 1)[1].split("!macroend", 1)[0]
    for body in (install, uninstall):
        guard = body.index('${If} $R2 == "1"')
        assert "${AndIf} $R3 < ${NSIS_MAX_STRLEN}" in body
        assert guard < body.index("WriteRegExpandStr"), "the write comes after the guard"
        assert "!insertmacro exeUserPathRead" in body[:guard]
    assert "${IfNot} ${isUpdated}" in uninstall
    assert uninstall.index("${IfNot} ${isUpdated}") < uninstall.index("DeleteRegValue")
    declared = script.split("!ifndef BUILD_UNINSTALLER", 1)[1].split("!endif", 1)[0]
    in_installer, in_uninstaller = declared.split("!else")
    assert in_installer.split() == ["${StrStr}"] and in_uninstaller.split() == ["${UnStrRep}"]
    assert "${StrStr} $R4" in install and "${UnStrRep} $R4" in uninstall
    assert "StrStr" not in uninstall and "StrRep" not in install


def test_the_store_package_announces_the_command_as_an_alias():
    build = _package()["build"]
    assert build["appx"]["customExtensionsPath"] == "build/appx-extensions.xml"
    import xml.etree.ElementTree as tree

    text = (BUILD / "appx-extensions.xml").read_text(encoding="utf-8")
    # The fragment borrows one prefix from the manifest it is spliced into.
    wrapped = (
        '<Extensions xmlns:desktop="http://schemas.microsoft.com/appx/manifest/desktop/windows10">'
        + text + "</Extensions>"
    )
    (extension,) = tree.fromstring(wrapped)
    uap3 = "{http://schemas.microsoft.com/appx/manifest/uap/windows10/3}"
    desktop = "{http://schemas.microsoft.com/appx/manifest/desktop/windows10}"
    assert extension.tag == uap3 + "Extension"
    assert extension.attrib == {
        "Category": "windows.appExecutionAlias",
        "Executable": "app\\resources\\exe-ai-terminal\\exe.exe",
        "EntryPoint": "Windows.FullTrustApplication",
    }
    (alias,) = extension.iter(desktop + "ExecutionAlias")
    assert alias.attrib == {"Alias": "exe.exe"}


def test_the_windows_installer_is_otherwise_untouched():
    """The silence probe: the packer finds the script by its name; nothing
    about the installer's own options changed for it."""
    assert _package()["build"]["nsis"] == {"artifactName": "Exe-AI-${version}-${arch}.exe"}
    assert "buildResources" not in _package()["build"]["directories"]


# --- the build description: a folder on every system ------------------------


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
    (exe_args, exe_kwargs), _client = calls["EXE"]
    assert exe_args[:2] == ("pyz", ["scripts"])
    assert exe_args[2] == [] and exe_args[3] == [], "binaries and datas go to COLLECT, not into the exe"
    assert exe_kwargs["exclude_binaries"] is True
    assert exe_kwargs["name"] == "Exe AI"
    assert exe_kwargs["console"] is False
    assert exe_kwargs["icon"].endswith("icon.ico")
    ((coll_args, coll_kwargs),) = calls["COLLECT"]
    assert coll_args == ("EXE", "EXE", ["binaries"], ["datas"])
    assert coll_kwargs["name"] == "Exe AI", "the folder's name is the path the shell starts"
    assert calls["BUNDLE"] == []


def test_on_windows_the_command_is_a_console_exe_in_the_same_folder(monkeypatch):
    """The command on the path: the same program under the name exe, with a
    console — the service's exe has none —, laid out in the one folder
    beside it rather than in a folder of its own."""
    calls = _spec_calls(monkeypatch, "win32")
    (service_args, _service), (client_args, client_kwargs) = calls["EXE"]
    assert client_args[:2] == service_args[:2], "one analysis, one program"
    assert client_args[2] == [] and client_args[3] == []
    assert client_kwargs["exclude_binaries"] is True
    assert client_kwargs["name"] == "exe"
    assert client_kwargs["console"] is True
    assert client_kwargs["icon"].endswith("icon.ico")
    assert len(calls["COLLECT"]) == 1


def test_on_macos_the_service_is_built_as_a_folder_and_its_bundle_takes_the_folder(monkeypatch):
    """Falls over with the one-file build: nothing rides inside the program,
    so nothing is unpacked into the system's temporary folder on a start.
    One program only — the command on macOS is the script deploy/exe."""
    calls = _spec_calls(monkeypatch, "darwin")
    ((exe_args, exe_kwargs),) = calls["EXE"]
    assert exe_args[2] == [] and exe_args[3] == [], "binaries and datas go to COLLECT, not into the program"
    assert exe_kwargs["exclude_binaries"] is True
    assert exe_kwargs["name"] == "Exe AI"
    assert exe_kwargs["console"] is True
    assert exe_kwargs["icon"] is None
    ((coll_args, coll_kwargs),) = calls["COLLECT"]
    assert coll_args == ("EXE", ["binaries"], ["datas"])
    assert coll_kwargs["name"] == "Exe AI", "the folder's name is the path the shell starts"
    ((bundle_args, bundle_kwargs),) = calls["BUNDLE"]
    assert bundle_args == ("COLLECT",)
    assert bundle_kwargs["name"] == "Exe AI Terminal.app"


def test_no_system_gets_a_one_file_build(monkeypatch):
    """Anywhere else the build is the same folder: one program, no bundle."""
    calls = _spec_calls(monkeypatch, "linux")
    ((exe_args, exe_kwargs),) = calls["EXE"]
    assert exe_args[2] == [] and exe_args[3] == []
    assert exe_kwargs["exclude_binaries"] is True
    ((coll_args, _coll_kwargs),) = calls["COLLECT"]
    assert coll_args == ("EXE", ["binaries"], ["datas"])
    assert calls["BUNDLE"] == []
