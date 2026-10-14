"""No child process opens a console window on Windows.

The program runs there without a console, so a console program it starts
would get a black window of its own. One place says how that is kept away
(app/no_console.py); these tests hold that every start of a child process
goes through it, and that nothing changes off Windows.
"""

from __future__ import annotations

import ast
import asyncio
import subprocess
import sys
from pathlib import Path

import pytest

from app import bildrunner, model_convert, no_console, skriptlauf
from app.tools import shell

APP = Path(__file__).resolve().parent.parent / "app"

# What the system calls the flag (CreateProcess, "CREATE_NO_WINDOW").
CREATE_NO_WINDOW = 0x08000000

# The ways this program starts a child process.
_SUBPROCESS = {"Popen", "run", "call", "check_call", "check_output"}
# ``_process_from_line`` is the Windows command line's own start
# (app/tools/shell.py): the whole line as one string, no shell around it.
_ASYNCIO = {"create_subprocess_exec", "create_subprocess_shell", "_process_from_line"}

# The two files that open a program for its own window — the browser and
# the file manager. Their windows are the point, so their calls stay as
# they are.
_OWN_WINDOW = {"appfenster.py": 1, "ordner_oeffnen.py": 2}


@pytest.fixture
def windows(monkeypatch):
    """The program as it finds itself on Windows."""
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(subprocess, "CREATE_NO_WINDOW", CREATE_NO_WINDOW, raising=False)


def _starts_a_child(call: ast.Call) -> bool:
    function = call.func
    if isinstance(function, ast.Attribute) and isinstance(function.value, ast.Name):
        return (
            (function.value.id == "subprocess" and function.attr in _SUBPROCESS)
            or (function.value.id == "asyncio" and function.attr in _ASYNCIO)
        )
    # Bound to a bare name: ``from subprocess import Popen``.
    return isinstance(function, ast.Name) and function.id in _ASYNCIO | {"Popen"}


def _through_the_one_place(call: ast.Call) -> bool:
    """The call passes ``**no_window()``."""
    return any(
        keyword.arg is None
        and isinstance(keyword.value, ast.Call)
        and isinstance(keyword.value.func, ast.Name)
        and keyword.value.func.id == "no_window"
        for keyword in call.keywords
    )


def _child_starts() -> dict[str, list[ast.Call]]:
    found: dict[str, list[ast.Call]] = {}
    for file in sorted(APP.rglob("*.py")):
        tree = ast.parse(file.read_text(encoding="utf-8"))
        calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and _starts_a_child(n)]
        if calls:
            found[file.relative_to(APP).as_posix()] = calls
    return found


def test_on_windows_a_child_starts_without_a_console_window(windows):
    assert no_console.no_window() == {"creationflags": CREATE_NO_WINDOW}


def test_off_windows_nothing_is_passed(monkeypatch):
    """Silence: on macOS and Linux a call is what it was — no keyword at
    all, whatever the name of the platform."""
    for platform in ("darwin", "linux"):
        monkeypatch.setattr(sys, "platform", platform)
        assert no_console.no_window() == {}
    monkeypatch.undo()
    if sys.platform != "win32":
        assert no_console.no_window() == {}


def test_every_start_of_a_child_process_goes_through_the_one_place():
    """No call of ``subprocess.Popen``, ``subprocess.run`` or
    ``create_subprocess_exec`` anywhere in the program goes past it, and
    none sets the flag by itself."""
    starts = _child_starts()
    # A floor, so a scan that finds nothing is not read as a program with
    # nothing to find (measured: 25, after the picture copies and the ID
    # photos moved from the system's tools to the library).
    assert sum(len(calls) for calls in starts.values()) >= 25
    for file, calls in starts.items():
        if file in _OWN_WINDOW:
            continue
        for call in calls:
            assert _through_the_one_place(call), f"{file}:{call.lineno}"
            assert not any(k.arg == "creationflags" for k in call.keywords), f"{file}:{call.lineno}"
    for file in APP.rglob("*.py"):
        text = file.read_text(encoding="utf-8")
        if file.name != "no_console.py":
            assert "CREATE_NO_WINDOW" not in text, file.name
        # No start hides behind another name or another way of starting.
        for other in ("import subprocess as", "os.system(", "os.popen(", "os.startfile(", "os.spawn"):
            assert other not in text, (file.name, other)
        # The one name bound out of the module is the one the scan knows.
        for line in text.splitlines():
            if line.startswith("from subprocess import"):
                assert line == "from subprocess import Popen", (file.name, line)


def test_a_program_opened_for_its_own_window_stays_as_it_is():
    """Silence: the browser and the file manager are started as before —
    their calls carry neither the keyword nor a flag of their own."""
    starts = _child_starts()
    for file, count in _OWN_WINDOW.items():
        calls = starts[file]
        assert len(calls) == count, file
        for call in calls:
            assert not _through_the_one_place(call), file
            assert not any(k.arg in (None, "creationflags") for k in call.keywords), file


class _Recorded(Exception):
    """Raised by a stand-in start, so nothing is really started."""


def _recording(seen: list[dict]):
    def start(*args, **keywords):
        seen.append(keywords)
        raise _Recorded

    return start


def test_a_painter_s_tool_and_the_device_list_start_without_a_window(windows, tmp_path, monkeypatch):
    """Through real callers: ``Popen`` and ``run`` are handed the flag on
    Windows."""
    seen: list[dict] = []
    monkeypatch.setattr(bildrunner.subprocess, "Popen", _recording(seen))
    with pytest.raises(_Recorded):
        bildrunner.Bildrunner(tmp_path).run_tool(["tool"], timeout=1)
    monkeypatch.setattr(model_convert.subprocess, "run", _recording(seen))
    with pytest.raises(_Recorded):
        model_convert.devices(Path("sd-cli"))
    assert [keywords.get("creationflags") for keywords in seen] == [CREATE_NO_WINDOW] * 2


def test_the_same_callers_pass_no_flag_off_windows(tmp_path, monkeypatch):
    """Silence: on this machine the same two starts carry no
    ``creationflags`` at all."""
    if sys.platform == "win32":
        pytest.skip("the silence of the other systems")
    seen: list[dict] = []
    monkeypatch.setattr(bildrunner.subprocess, "Popen", _recording(seen))
    with pytest.raises(_Recorded):
        bildrunner.Bildrunner(tmp_path).run_tool(["tool"], timeout=1)
    monkeypatch.setattr(model_convert.subprocess, "run", _recording(seen))
    with pytest.raises(_Recorded):
        model_convert.devices(Path("sd-cli"))
    assert all("creationflags" not in keywords for keywords in seen) and len(seen) == 2


def test_a_shell_command_and_a_script_start_without_a_window(windows, monkeypatch):
    """The asyncio starts: every further keyword goes on to ``Popen``, so
    the flag is passed the same way."""
    names = {name for calls in _child_starts().values() for call in calls
             if isinstance(call.func, ast.Attribute) and (name := call.func.attr) in _ASYNCIO}
    # The command processor on Windows is handed its line as one string by the
    # start of its own (``_process_from_line``, called by ``_starten``, which
    # passes the flag like every other start); every other child goes by a
    # list through ``create_subprocess_exec``.
    assert names == {"create_subprocess_exec"}
    shell_calls = _child_starts()["tools/shell.py"]
    line_starts = [c for c in shell_calls if isinstance(c.func, ast.Name) and c.func.id == "_process_from_line"]
    assert len(line_starts) == 1 and _through_the_one_place(line_starts[0])
    for module in (shell, skriptlauf):
        assert module.no_window is no_console.no_window
    seen: list[dict] = []

    async def start(*args, **keywords):
        seen.append(keywords)
        raise _Recorded

    monkeypatch.setattr(asyncio, "create_subprocess_exec", start)

    async def run() -> None:
        with pytest.raises(_Recorded):
            await asyncio.create_subprocess_exec("tool", **shell.no_window())

    asyncio.run(run())
    assert seen == [{"creationflags": CREATE_NO_WINDOW}]
