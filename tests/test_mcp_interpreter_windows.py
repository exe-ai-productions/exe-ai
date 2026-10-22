"""The shipped server list names the venv's Python the POSIX way.

Run from source on Windows, ``.venv/bin/python`` is no file — the web search
server never started ("[WinError 2]") and its two tools were missing. The
command is translated where the server is started (app/tools/registry.py,
``_interpreter``); the list itself keeps saying what it says.
"""

from __future__ import annotations

import sys

from app.tools import registry


def test_on_windows_the_venv_path_becomes_the_running_interpreter(monkeypatch):
    monkeypatch.setattr(registry.sys, "platform", "win32")
    assert registry._interpreter(".venv/bin/python") == sys.executable
    assert registry._interpreter(".venv/bin/python3") == sys.executable
    assert registry._interpreter(".venv\\bin\\python") == sys.executable


def test_silence_other_commands_stay_as_they_stand(monkeypatch):
    monkeypatch.setattr(registry.sys, "platform", "win32")
    assert registry._interpreter("node") == "node"
    assert registry._interpreter("C:/Tools/python.exe") == "C:/Tools/python.exe"
    assert registry._interpreter("uvx") == "uvx"


def test_silence_outside_windows_the_path_stays(monkeypatch):
    monkeypatch.setattr(registry.sys, "platform", "darwin")
    assert registry._interpreter(".venv/bin/python") == ".venv/bin/python"
