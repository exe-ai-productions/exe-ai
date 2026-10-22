"""The voices the operating system brings along, as a voice for the speech.

A voice is either a voice model read by ``llama-tts`` (app/stimme.py) or one
of these: on a Mac every voice ``say -v '?'`` names, on Windows every voice
of ``Windows.Media.SpeechSynthesis``; Linux has none. Which one speaks follows
from the chosen name — there is no second field and no switch for the kind.

A voice of the system speaks one WAV per piece, over the same route as the
voice model, and needs no process kept alive: ``say`` and PowerShell start,
speak and end.

Nothing of a person's text and no voice name ever becomes part of a command
line that a shell reads. The text goes to ``say`` through its standard input,
so a text that starts with a hyphen is never taken for a switch; to PowerShell
text and name go through a file of data that the script reads. The voice name
is also checked against the voices the system itself listed before it is used.
"""

from __future__ import annotations

import json
import logging
import re
import sys
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from app.stimme import SprechenNichtMoeglich, programm_laufen

log = logging.getLogger(__name__)

# The voice a machine starts with while nothing is chosen. A voice that is
# not installed there falls back to the default voice of the system.
FACTORY_VOICES = {"darwin": "Anna", "win32": "Microsoft Katja"}

# A process safety valve, like the one of ``llama-tts``, far shorter: a piece
# is a sentence or two.
SPEAK_SECONDS = 120.0
LIST_SECONDS = 30.0
# How long a list of voices is believed: Windows needs a PowerShell start to
# read it, and the window asks for it with every answer about the speech
# server. A voice installed meanwhile shows up within this time.
LIST_KEPT_SECONDS = 60.0


@dataclass(frozen=True)
class SystemVoice:
    """One voice of the system: its name as the system gives it, and the
    language of the voice as the system names it (``de_DE``, ``de-DE``)."""

    name: str
    language: str


def _platform() -> str:
    return sys.platform


def available() -> bool:
    """Whether this system has a voice to ask at all (a Mac, Windows)."""
    return _platform() in FACTORY_VOICES


def factory_voice() -> str:
    """The voice a machine starts with, or an empty string where it has none."""
    return FACTORY_VOICES.get(_platform(), "")


# The Mac's list has one voice to a line: its name (which may hold spaces
# and brackets, "Anna (Premium)"), padding, the language, a hash and the
# sentence the voice says about itself.
_SAY_LINE = re.compile(r"^(?P<name>.+?)\s+(?P<language>[A-Za-z]{2,3}[_-][A-Za-z0-9]+)\s+#")


def parse_say_list(output: str) -> list[SystemVoice]:
    """The voices out of the text of ``say -v '?'``; a line that is none is
    skipped."""
    voices: list[SystemVoice] = []
    for line in output.splitlines():
        hit = _SAY_LINE.match(line.strip())
        if hit:
            voices.append(SystemVoice(hit["name"].strip(), hit["language"]))
    return voices


def parse_windows_list(output: str) -> list[SystemVoice]:
    """The voices out of what the PowerShell part prints: one ``name|language``
    to a line."""
    voices: list[SystemVoice] = []
    for line in output.splitlines():
        name, separator, language = line.strip().partition("|")
        if separator and name.strip():
            voices.append(SystemVoice(name.strip(), language.strip()))
    return voices


# PowerShell 5.1 reads a script as ANSI unless it starts with a byte order
# mark, so the file is written with one (measured on Windows 11 with a script
# that carries umlauts). The voices of WinRT need `AsTask` to be waited for.
_POWERSHELL_PRELUDE = r"""
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$asTask = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
    $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and
    $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
function Wait-Operation($operation, [Type]$type) {
    $task = $asTask.MakeGenericMethod($type).Invoke($null, @($operation))
    $task.Wait(-1) | Out-Null
    $task.Result
}
[void][Windows.Media.SpeechSynthesis.SpeechSynthesizer, Windows.Media.SpeechSynthesis, ContentType = WindowsRuntime]
[void][Windows.Storage.Streams.DataReader, Windows.Storage.Streams, ContentType = WindowsRuntime]
"""

_POWERSHELL_LIST = _POWERSHELL_PRELUDE + r"""
foreach ($voice in [Windows.Media.SpeechSynthesis.SpeechSynthesizer]::AllVoices) {
    '{0}|{1}' -f $voice.DisplayName, $voice.Language
}
"""

# Reads one file of data: {"voice": ..., "text": ..., "out": ...}.
_POWERSHELL_SPEAK = _POWERSHELL_PRELUDE + r"""
$request = Get-Content -Raw -Encoding UTF8 -LiteralPath $args[0] | ConvertFrom-Json
$synthesizer = New-Object Windows.Media.SpeechSynthesis.SpeechSynthesizer
if ($request.voice) {
    $chosen = [Windows.Media.SpeechSynthesis.SpeechSynthesizer]::AllVoices |
        Where-Object { $_.DisplayName -eq $request.voice } | Select-Object -First 1
    if ($chosen) { $synthesizer.Voice = $chosen }
}
$stream = Wait-Operation ($synthesizer.SynthesizeTextToStreamAsync($request.text)) ([Windows.Media.SpeechSynthesis.SpeechSynthesisStream])
$reader = New-Object Windows.Storage.Streams.DataReader($stream.GetInputStreamAt(0))
$size = [uint32]$stream.Size
Wait-Operation ($reader.LoadAsync($size)) ([uint32]) | Out-Null
$bytes = New-Object byte[] $size
$reader.ReadBytes($bytes)
[IO.File]::WriteAllBytes($request.out, $bytes)
"""


def _write_script(folder: Path, name: str, text: str) -> Path:
    path = folder / name
    path.write_bytes(b"\xef\xbb\xbf" + text.encode("utf-8"))
    return path


def _powershell() -> str:
    return "powershell.exe"


_list_lock = threading.Lock()
_list_cache: tuple[float, list[SystemVoice]] | None = None


def _read_voices() -> list[SystemVoice]:
    if _platform() == "darwin":
        run = programm_laufen(["say", "-v", "?"], cancel=None, timeout=LIST_SECONDS)
        return parse_say_list(run.stdout) if run.returncode == 0 else []
    if _platform() == "win32":
        with tempfile.TemporaryDirectory() as tmp:
            script = _write_script(Path(tmp), "voices.ps1", _POWERSHELL_LIST)
            run = programm_laufen(
                [_powershell(), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                 "-File", str(script)],
                cancel=None, timeout=LIST_SECONDS,
            )
        return parse_windows_list(run.stdout) if run.returncode == 0 else []
    return []


def list_voices() -> list[SystemVoice]:
    """Every voice of the system, in the order the system gives them; empty
    where the system has none or cannot be asked. Kept for a minute."""
    global _list_cache
    with _list_lock:
        now = time.monotonic()
        if _list_cache is not None and now - _list_cache[0] < LIST_KEPT_SECONDS:
            return list(_list_cache[1])
        try:
            voices = _read_voices()
        except Exception as error:  # noqa: BLE001 - a list that cannot be read is an empty one
            log.warning("The voices of the system could not be listed: %s", error)
            voices = []
        _list_cache = (now, voices)
        return list(voices)


def forget_voices() -> None:
    """Drops the kept list, so the next one is read afresh."""
    global _list_cache
    with _list_lock:
        _list_cache = None


def has_voice(name: str) -> bool:
    """Whether the system names a voice with exactly this name."""
    return bool(name) and any(voice.name == name for voice in list_voices())


def default_voice() -> str:
    """The voice to ask for to get the one the system itself uses: an empty
    name, which ``say`` and ``SpeechSynthesizer`` read as their default."""
    return ""


def speak(text: str, voice: str, *, cancel: threading.Event | None = None) -> bytes:
    """One piece, spoken by the system as WAV bytes. ``voice`` is a name the
    system listed, or an empty string for the voice the system itself uses;
    any other name is refused before anything is started.

    ``cancel``, once set, ends the program and raises ``stimme.SpeakCancelled``.
    """
    if voice and not has_voice(voice):
        raise SprechenNichtMoeglich("stimme_fehlgeschlagen")
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "voice.wav"
        started = time.monotonic()
        if _platform() == "darwin":
            command = ["say"]
            if voice:
                command += ["-v", voice]
            # The text comes in on the standard input (`-f -`): it is data,
            # and a text that starts with a hyphen is never read as a switch.
            command += ["-o", str(target), "--file-format=WAVE", "--data-format=LEI16@22050", "-f", "-"]
            run = programm_laufen(command, cancel=cancel, timeout=SPEAK_SECONDS, eingabe=text)
        elif _platform() == "win32":
            script = _write_script(Path(tmp), "speak.ps1", _POWERSHELL_SPEAK)
            data = Path(tmp) / "request.json"
            data.write_text(
                json.dumps({"voice": voice, "text": text, "out": str(target)}), encoding="utf-8",
            )
            run = programm_laufen(
                [_powershell(), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                 "-File", str(script), str(data)],
                cancel=cancel, timeout=SPEAK_SECONDS,
            )
        else:
            raise SprechenNichtMoeglich("stimme_fehlgeschlagen")
        if run.returncode != 0 or not target.exists():
            log.warning(
                "The voice of the system failed after %.1fs (code %s): %s",
                time.monotonic() - started, run.returncode, (run.stderr or "")[-500:],
            )
            raise SprechenNichtMoeglich("stimme_fehlgeschlagen")
        wav = target.read_bytes()
        log.info(
            "The voice of the system spoke %d bytes in %.1fs (%d characters, voice=%s)",
            len(wav), time.monotonic() - started, len(text), voice or "-",
        )
        return wav


__all__ = [
    "FACTORY_VOICES",
    "available",
    "SystemVoice",
    "default_voice",
    "factory_voice",
    "forget_voices",
    "has_voice",
    "list_voices",
    "parse_say_list",
    "parse_windows_list",
    "speak",
]
