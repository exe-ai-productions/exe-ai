"""The voices of the operating system as a voice for the speech.

A Mac lists its voices with ``say -v '?'`` and speaks with ``say``; Windows
lists and speaks through the speech synthesis of Windows, reached through
PowerShell. Neither program is started here: the one runner of the module is
replaced by one that records the command and plays the part of the program.

What must hold on both systems: the text of a person and the name of a voice
never become part of a command line that a shell reads; a voice the system did
not list is never asked for; a machine starts with its own voice (a Mac
"Anna", Windows "Microsoft Katja", Linux none).
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from app import stimme, system_voice

MAC_LIST = """\
Albert              en_US    # Hello! My name is Albert.
Anna                de_DE    # Hallo! Ich heiße Anna.
Anna (Premium)      de_DE    # Hallo! Ich heiße Anna.
Eddy (Deutsch (Deutschland)) de_DE    # Hallo! Ich heiße Eddy.
Zarvox              en_US    # That looks like a peaceful planet.
a line that is none
"""

WINDOWS_LIST = "Microsoft Katja|de-DE\r\nMicrosoft Zira|en-US\r\n\r\nnonsense without a bar\r\n"


class _Run:
    """What the module takes for a finished program."""

    def __init__(self, stdout: str = "", returncode: int = 0, stderr: str = "") -> None:
        self.stdout = stdout
        self.returncode = returncode
        self.stderr = stderr


@pytest.fixture
def system(monkeypatch):
    """A system whose runner is the test's: ``system.platform`` picks the
    system, ``system.runs`` collects every command with its input, and
    ``system.answer`` is what the program does."""

    class Stand:
        platform = "darwin"
        runs: list[dict]
        answer = staticmethod(lambda command, eingabe: _Run())

    stand = Stand()
    stand.runs = []

    def run(command, *, cancel, timeout, eingabe=None):
        record = {"command": list(command), "eingabe": eingabe, "timeout": timeout}
        if "-File" in command:
            # The scripts of PowerShell are read from disk: keep what they say
            # and the data they are handed before the folder goes.
            script = Path(command[command.index("-File") + 1])
            record["script"] = script.read_bytes()
            if len(command) > command.index("-File") + 2:
                record["data"] = json.loads(Path(command[-1]).read_text(encoding="utf-8"))
        stand.runs.append(record)
        return stand.answer(command, eingabe)

    monkeypatch.setattr(system_voice, "_platform", lambda: stand.platform)
    monkeypatch.setattr(system_voice, "programm_laufen", run)
    system_voice.forget_voices()
    yield stand
    system_voice.forget_voices()


def test_the_list_of_a_mac_is_read_with_names_that_hold_spaces_and_brackets():
    voices = system_voice.parse_say_list(MAC_LIST)
    assert [v.name for v in voices] == [
        "Albert", "Anna", "Anna (Premium)", "Eddy (Deutsch (Deutschland))", "Zarvox",
    ]
    assert voices[1] == system_voice.SystemVoice("Anna", "de_DE")
    assert voices[2].language == "de_DE"


def test_the_list_of_windows_is_read_one_voice_to_a_line():
    voices = system_voice.parse_windows_list(WINDOWS_LIST)
    assert voices == [
        system_voice.SystemVoice("Microsoft Katja", "de-DE"),
        system_voice.SystemVoice("Microsoft Zira", "en-US"),
    ]


def test_a_machine_starts_with_its_own_voice(monkeypatch):
    for platform, expected in (("darwin", "Anna"), ("win32", "Microsoft Katja"), ("linux", "")):
        monkeypatch.setattr(system_voice, "_platform", lambda platform=platform: platform)
        assert system_voice.factory_voice() == expected
    monkeypatch.setattr(system_voice, "_platform", lambda: "linux")
    assert not system_voice.available()
    monkeypatch.setattr(system_voice, "_platform", lambda: "win32")
    assert system_voice.available()
    # No name is the voice the system itself uses.
    assert system_voice.default_voice() == ""


def test_the_mac_is_asked_for_its_voices_once_a_minute(system):
    system.answer = lambda command, eingabe: _Run(MAC_LIST)
    assert [v.name for v in system_voice.list_voices()][:2] == ["Albert", "Anna"]
    assert system_voice.has_voice("Anna (Premium)")
    assert not system_voice.has_voice("Katja")
    assert not system_voice.has_voice("")
    assert [run["command"] for run in system.runs] == [["say", "-v", "?"]]
    system_voice.forget_voices()
    system_voice.list_voices()
    assert len(system.runs) == 2


def test_windows_is_asked_through_a_script_file_not_through_the_command_line(system):
    system.platform = "win32"
    system.answer = lambda command, eingabe: _Run(WINDOWS_LIST)
    assert [v.name for v in system_voice.list_voices()] == ["Microsoft Katja", "Microsoft Zira"]
    run = system.runs[0]
    assert run["command"][0] == "powershell.exe"
    assert "-File" in run["command"] and "-Command" not in run["command"]
    # PowerShell 5.1 reads a script as ANSI unless it opens with a byte order mark.
    assert run["script"].startswith(b"\xef\xbb\xbf")
    assert b"AllVoices" in run["script"]


def test_linux_has_no_voices_and_nothing_is_started(system):
    system.platform = "linux"
    assert system_voice.list_voices() == []
    assert system.runs == []


def test_a_list_that_cannot_be_read_is_an_empty_one(system):
    def broken(command, eingabe):
        raise OSError("no say")

    system.answer = broken
    assert system_voice.list_voices() == []


def test_the_mac_speaks_with_the_text_on_the_standard_input(system):
    """A text that starts with a hyphen is never taken for a switch, and no
    word of a person is part of the command."""

    def say(command, eingabe):
        Path(command[command.index("-o") + 1]).write_bytes(b"RIFF-WAV")
        return _Run()

    system.answer = lambda command, eingabe: _Run(MAC_LIST) if "?" in command else say(command, eingabe)
    text = "-v Zarvox; rm -rf / `whoami` $(id)"
    assert system_voice.speak(text, "Anna") == b"RIFF-WAV"
    command = system.runs[-1]["command"]
    assert command[:3] == ["say", "-v", "Anna"]
    assert command[-2:] == ["-f", "-"]
    assert "--file-format=WAVE" in command
    assert system.runs[-1]["eingabe"] == text
    assert all(text not in part for part in command)


def test_the_default_voice_of_the_system_is_asked_without_a_name(system):
    def say(command, eingabe):
        Path(command[command.index("-o") + 1]).write_bytes(b"RIFF-WAV")
        return _Run()

    system.answer = say
    assert system_voice.speak("Hallo", "") == b"RIFF-WAV"
    assert "-v" not in system.runs[-1]["command"]


def test_a_voice_the_system_did_not_list_is_never_asked_for(system):
    system.answer = lambda command, eingabe: _Run(MAC_LIST)
    with pytest.raises(stimme.SprechenNichtMoeglich) as refusal:
        system_voice.speak("Hallo", "--output-file=/etc/passwd")
    assert refusal.value.grund == "stimme_fehlgeschlagen"
    # Only the list was asked for.
    assert [run["command"] for run in system.runs] == [["say", "-v", "?"]]


def test_a_program_that_fails_says_so(system, caplog):
    system.answer = lambda command, eingabe: _Run(MAC_LIST) if "?" in command else _Run(returncode=1, stderr="boom")
    with caplog.at_level("WARNING", logger="app.system_voice"):
        with pytest.raises(stimme.SprechenNichtMoeglich) as refusal:
            system_voice.speak("Hallo", "Anna")
    assert refusal.value.grund == "stimme_fehlgeschlagen"
    assert "boom" in caplog.text


def test_windows_speaks_with_the_text_and_the_name_in_a_file_of_data(system):
    system.platform = "win32"

    def powershell(command, eingabe):
        if "voices.ps1" in command[command.index("-File") + 1]:
            return _Run(WINDOWS_LIST)
        data = json.loads(Path(command[-1]).read_text(encoding="utf-8"))
        Path(data["out"]).write_bytes(b"RIFF-WAV")
        return _Run()

    system.answer = powershell
    text = 'say "hello"; Remove-Item -Recurse C:\\ ; $(calc)'
    assert system_voice.speak(text, "Microsoft Katja") == b"RIFF-WAV"
    run = system.runs[-1]
    assert run["data"]["text"] == text
    assert run["data"]["voice"] == "Microsoft Katja"
    # Neither the text nor the name is a part of the command line.
    assert all(text not in part and "Katja" not in part for part in run["command"])
    assert "-Command" not in run["command"]
    assert run["script"].startswith(b"\xef\xbb\xbf")
    assert b"SynthesizeTextToStreamAsync" in run["script"]


def test_the_runner_hands_the_input_to_the_program_once():
    """The real runner: a text that starts with a hyphen reaches the program
    as data, however long the program takes to read it."""
    program = [sys.executable, "-c", "import sys, time; time.sleep(0.6); sys.stdout.write(sys.stdin.read())"]
    run = stimme.programm_laufen(program, cancel=None, timeout=30.0, eingabe="-n hello\n")
    assert run.returncode == 0
    assert run.stdout == "-n hello\n"
    assert isinstance(run, subprocess.CompletedProcess)
