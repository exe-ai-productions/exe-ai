"""Is this process id our llama-server? Asked before an orphan is ended.

Windows has no ``ps``: the question raised, the answer was always "no", and a
server left behind by a crashed service was never ended there. ``tasklist``
answers it instead (app/modellrunner.py, ``_ist_llama_server``).
"""

from __future__ import annotations

import subprocess

from app import modellrunner


def _tasklist(stdout: str, seen: list):
    def run(command, **kwargs):
        seen.append(command)
        return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr="")

    return run


def test_on_windows_the_check_asks_tasklist(monkeypatch):
    seen: list = []
    line = '"llama-server.exe","4242","Console","1","1.498.588 K"\r\n'
    monkeypatch.setattr(modellrunner.sys, "platform", "win32")
    monkeypatch.setattr(modellrunner.subprocess, "run", _tasklist(line, seen))

    assert modellrunner._ist_llama_server(4242) is True
    assert seen[0][:3] == ["tasklist", "/FI", "PID eq 4242"]


def test_on_windows_a_foreign_process_is_not_ours(monkeypatch):
    line = '"python.exe","4242","Console","1","53.028 K"\r\n'
    monkeypatch.setattr(modellrunner.sys, "platform", "win32")
    monkeypatch.setattr(modellrunner.subprocess, "run", _tasklist(line, []))

    assert modellrunner._ist_llama_server(4242) is False


def test_on_windows_no_task_is_not_ours(monkeypatch):
    line = "INFO: No tasks are running which match the specified criteria.\r\n"
    monkeypatch.setattr(modellrunner.sys, "platform", "win32")
    monkeypatch.setattr(modellrunner.subprocess, "run", _tasklist(line, []))

    assert modellrunner._ist_llama_server(4242) is False


def test_silence_outside_windows_the_check_asks_ps(monkeypatch):
    seen: list = []
    monkeypatch.setattr(modellrunner.sys, "platform", "darwin")
    monkeypatch.setattr(modellrunner.subprocess, "run", _tasklist("llama-server\n", seen))

    assert modellrunner._ist_llama_server(4242) is True
    assert seen[0][0] == "ps"
