"""Every text pipe of a child process names its encoding.

Python on Windows reads a text pipe in the system's own code page (cp1252)
unless told otherwise; llama-server, sd-cli, the embedder and PowerShell
write UTF-8, so an umlaut or a "·" arrived broken or stopped the reader.
The house rule here is read from the source: no ``subprocess`` call with
``text=True`` without an ``encoding``. The two readers that carry text
somebody reads — the picture's prompt and the server's log — are run for
real against a child that writes UTF-8.
"""

from __future__ import annotations

import ast
import json
import subprocess
import sys
import time
from pathlib import Path


from app import ordner_dialog, picture_info

APP = Path(__file__).resolve().parent.parent / "app"
_STARTS = {"run", "Popen", "check_output", "check_call"}
LINE = "Höchstens ein Hund · zwei Katzen"


def _text_pipe_without_encoding(call: ast.Call) -> bool:
    """A ``subprocess`` start in text mode that names no encoding."""
    function = call.func
    if isinstance(function, ast.Attribute):
        if not (isinstance(function.value, ast.Name) and function.value.id == "subprocess"):
            return False
        name = function.attr
    elif isinstance(function, ast.Name):
        name = function.id
    else:
        return False
    if name not in _STARTS:
        return False
    keywords = {k.arg: k.value for k in call.keywords if k.arg}
    flags = (keywords.get("text"), keywords.get("universal_newlines"))
    text = any(isinstance(flag, ast.Constant) and flag.value is True for flag in flags)
    return text and "encoding" not in keywords


def test_no_text_pipe_in_the_program_is_read_without_a_named_encoding():
    unnamed: list[str] = []
    for file in sorted(APP.rglob("*.py")):
        tree = ast.parse(file.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and _text_pipe_without_encoding(node):
                unnamed.append(f"{file.relative_to(APP)}:{node.lineno}")
    assert unnamed == [], f"text pipes without an encoding: {unnamed}"


# --- the readers, run for real against a child that writes UTF-8 --------


def _utf8_child(code: str) -> list[str]:
    """A child that writes UTF-8 whatever the system's own code page is."""
    return [sys.executable, "-X", "utf8", "-c", code]


def _run_as_utf8_child(code: str, seen: dict):
    """A ``subprocess.run`` that keeps the caller's keywords — the encoding
    under test among them — and runs the child above in the command's
    place."""
    real = subprocess.run

    def run(command, **keywords):
        seen.update(keywords)
        return real(_utf8_child(code), **keywords)

    return run


def test_the_picture_s_prompt_arrives_as_written(monkeypatch, tmp_path):
    answer = json.dumps({"keyword": "parameters", "text": f"{LINE}\nSteps: 20, Seed: 7"})
    seen: dict = {}
    monkeypatch.setattr(picture_info.subprocess, "run",
                        _run_as_utf8_child(f"import sys; sys.stdout.write({answer!r})", seen))
    values = picture_info.read(tmp_path / "sd-cli", tmp_path / "picture.png")
    assert values["prompt"] == LINE
    assert values["schritte"] == 20 and values["seed"] == 7
    # Named, so Windows reads the program's UTF-8 and not its own code page.
    assert seen["encoding"] == "utf-8" and seen["errors"] == "replace"


def test_an_ascii_prompt_arrives_as_before(monkeypatch, tmp_path):
    """The silence probe."""
    answer = json.dumps({"keyword": "parameters", "text": "a plain dog\nSteps: 4"})
    monkeypatch.setattr(picture_info.subprocess, "run",
                        _run_as_utf8_child(f"import sys; sys.stdout.write({answer!r})", {}))
    assert picture_info.read(tmp_path / "sd-cli", tmp_path / "picture.png")["prompt"] == "a plain dog"


def test_the_server_s_log_line_arrives_as_written(tmp_path, monkeypatch):
    """The model runner's reader thread, fed by a child that writes UTF-8."""
    import app.modellrunner as mr

    (tmp_path / "klein.gguf").write_bytes(b"x" * 2000)
    program = tmp_path / "llama-server"
    program.write_text("#!/bin/sh\nsleep 30\n", encoding="utf-8")
    program.chmod(0o755)
    seen: dict = {}
    real_popen = mr.subprocess.Popen

    def popen(command, *args, **keywords):
        seen.update(keywords)
        code = f"print({LINE!r}, flush=True); import time; time.sleep(30)"
        return real_popen(_utf8_child(code), *args, **keywords)

    monkeypatch.setattr(mr.subprocess, "Popen", popen)
    runner = mr.Modellrunner(tmp_path, programm=str(program))
    try:
        runner.starten("klein.gguf", port=18103)
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and not any(LINE in z for z in runner.protokoll()):
            time.sleep(0.05)
        assert any(LINE in z for z in runner.protokoll()), runner.protokoll()
    finally:
        runner.stoppen()
    assert seen["encoding"] == "utf-8" and seen["errors"] == "replace"


# --- PowerShell answers in UTF-8 -------------------------------------------


UTF8_FIRST = "[Console]::OutputEncoding = [Text.Encoding]::UTF8; "


def test_the_folder_dialog_s_script_switches_powershell_to_utf8():
    command = ordner_dialog._befehl_windows("Choose", None)
    assert command[-1].startswith(UTF8_FIRST)
    assert "FolderBrowserDialog" in command[-1]

