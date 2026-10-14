"""On Windows the command line runs in exactly one cmd.exe.

The platform is imitated (``WINDOWS`` true, the process start replaced): what
is checked is what the tool hands to the system. Handed to asyncio's shell
start, the line `cmd.exe /v:on /c "…"` is wrapped a second time, and the outer
cmd reads a `<` or `>` inside the user's double quotes as a redirection.
"""

from __future__ import annotations

import asyncio
import inspect
from types import SimpleNamespace

import pytest

from app.tools import shell

COMSPEC = r"C:\Windows\System32\cmd.exe"


@pytest.fixture
def windows(monkeypatch):
    """The Windows branch with its two ways of starting a process recorded."""
    seen: dict = {}

    async def from_line(line, **kwargs):
        seen["line"] = line
        seen["kwargs"] = kwargs
        return SimpleNamespace()

    async def no_shell(*args, **kwargs):  # pragma: no cover - must not run
        raise AssertionError("the line went through asyncio's shell start")

    monkeypatch.setattr(shell, "WINDOWS", True)
    monkeypatch.setattr(shell, "_process_from_line", from_line)
    monkeypatch.setattr(asyncio, "create_subprocess_shell", no_shell)
    monkeypatch.setenv("COMSPEC", COMSPEC)
    return seen


@pytest.mark.asyncio
async def test_the_line_goes_to_the_system_as_one_string_for_one_cmd(windows, tmp_path):
    command = "echo hallo"
    await shell._starten(command, tmp_path)
    assert windows["line"] == f'{COMSPEC} /v:on /c "{shell._mit_ordnermarke(command)}"'
    assert windows["kwargs"]["cwd"] == str(tmp_path)
    assert windows["kwargs"]["env"]["PYTHONUNBUFFERED"] == "1"


@pytest.mark.asyncio
async def test_a_command_with_angle_brackets_in_quotes_arrives_as_written(windows, tmp_path):
    command = """python -c "open('x.html','w').write('<h1>a</h1>')" """.strip()
    await shell._starten(command, tmp_path)
    assert command in windows["line"]
    # Not one character of it is escaped or rewritten on the way.
    assert windows["line"].count(command) == 1


@pytest.mark.asyncio
async def test_without_a_comspec_the_system_default_is_named(windows, tmp_path, monkeypatch):
    monkeypatch.delenv("COMSPEC")
    await shell._starten("dir", tmp_path)
    assert windows["line"].startswith('cmd.exe /v:on /c "')


def test_the_folder_marker_carries_no_double_quote_of_its_own(monkeypatch):
    """Silence probe: the part the tool writes itself stays free of quotes, so
    the processor can read the line the way it was written."""
    monkeypatch.setattr(shell, "WINDOWS", True)
    line = shell._mit_ordnermarke("echo x")
    assert '"' not in line
    assert "!ERRORLEVEL!" in line and "!CD!" in line


@pytest.mark.asyncio
async def test_the_process_is_started_from_the_whole_line_without_a_shell(monkeypatch):
    """The transport gets the line as its program, shell off, both outputs
    piped — the same transport ``create_subprocess_exec`` uses."""
    call: dict = {}

    class _Transport:
        def get_pid(self):
            return 4711

    async def make_transport(protocol, args, use_shell, stdin, stdout, stderr, bufsize, **kwargs):
        call.update(args=args, shell=use_shell, stdin=stdin, stdout=stdout, stderr=stderr,
                      bufsize=bufsize, kwargs=kwargs)
        return _Transport()

    loop = asyncio.get_running_loop()
    monkeypatch.setattr(loop, "_make_subprocess_transport", make_transport, raising=False)

    process = await shell._process_from_line('cmd.exe /v:on /c "echo <x>"', cwd="C:\\w", env={"A": "1"})
    assert process.pid == 4711
    assert call["args"] == 'cmd.exe /v:on /c "echo <x>"'
    assert call["shell"] is False
    assert call["stdin"] is None
    assert call["stdout"] == asyncio.subprocess.PIPE
    assert call["stderr"] == asyncio.subprocess.PIPE
    assert call["kwargs"] == {"cwd": "C:\\w", "env": {"A": "1"}}


@pytest.mark.asyncio
async def test_off_windows_the_shell_is_started_with_a_list_as_before(monkeypatch, tmp_path):
    """Silence probe: POSIX starts `$SHELL -c <line>`, never the string path."""
    call: dict = {}

    async def record_exec(*args, **kwargs):
        call["args"] = args
        return SimpleNamespace()

    async def no_line_start(*args, **kwargs):  # pragma: no cover - must not run
        raise AssertionError("the string path is for Windows only")

    monkeypatch.setattr(shell, "WINDOWS", False)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", record_exec)
    monkeypatch.setattr(shell, "_process_from_line", no_line_start)
    monkeypatch.setenv("SHELL", "/bin/zsh")
    await shell._starten("echo hallo", tmp_path)
    assert call["args"][:2] == ("/bin/zsh", "-c")
    assert "echo hallo" in call["args"][2]


@pytest.mark.asyncio
async def test_the_loops_transport_start_still_takes_the_arguments_the_line_start_passes():
    """The line start calls a private method of the event loop; this pins the
    names and the order it is called with, so an interpreter upgrade that
    changes them fails here and not on a Windows machine."""
    loop = asyncio.get_running_loop()
    names = list(inspect.signature(loop._make_subprocess_transport).parameters)
    assert names[:7] == ["protocol", "args", "shell", "stdin", "stdout", "stderr", "bufsize"]
    assert "kwargs" in names
    # The two classes the start wraps its transport in.
    assert list(inspect.signature(asyncio.subprocess.Process).parameters) == ["transport", "protocol", "loop"]
    protocol = inspect.signature(asyncio.subprocess.SubprocessStreamProtocol).parameters
    assert list(protocol) == ["limit", "loop"]
