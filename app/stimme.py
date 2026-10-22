"""Text to speech, through the one program already installed for chat.

The engine behind a voice is ``llama-tts``, part of the very same llama.cpp
build as ``llama-server`` (app/modellrunner.py) — not a server, a one-shot
program: handed a model, a projector, a voice sample and a sentence, it
writes one WAV file and exits. A voice is a subprocess call, not a fourth
runner with its own port and its own start button: it has no "running",
nothing to poll, nothing to stop.

The generation values below come from the model's own
``generation_config.json`` (Qwen/Qwen3-TTS-12Hz-1.7B-Base), measured to hold
natural-length speech — a generic default once made the same model speak for
96 seconds over 133 characters. They are what a voice starts with; every one
of them is a setting the speech panel carries (app/diktatsprachewahl.py), and
whatever is set there beats the constant. A different temperature does not
cure a sentence spoken twice: measured over forty runs of one sentence, it
came out doubled about as often at 0.3 as at 0.9, and without a voice sample
too.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

from app.no_console import no_window
from app.voice_worker import VOICE_CONTEXT_SIZE

log = logging.getLogger(__name__)

BINARNAME = "llama-tts"

# From Qwen/Qwen3-TTS-12Hz-1.7B-Base's own generation_config.json. The
# temperature is only the value a voice starts with; the stored setting wins.
TEMPERATUR = 0.9
TOP_K = 50
TOP_P = 1.0
MIN_P = 0.0
WIEDERHOLUNGSSTRAFE = 1.05

# A process safety valve, not a speech-length ceiling — the length of the
# speech itself is deliberately unbounded. The figure matches one already
# measured against this engine.
ZEITGRENZE = 600.0


class SprechenNichtMoeglich(Exception):
    """The voice could not be asked to speak.

    ``grund`` is a locale key, the same idiom ``RunnerFehler`` uses
    (app/modellrunner.py) — the route turns it into the user's language,
    this module never does.
    """

    def __init__(self, grund: str) -> None:
        self.grund = grund
        super().__init__(grund)


def _program_file_name() -> str:
    """The name the program file carries on this system. llama.cpp's Windows
    builds ship ``llama-tts.exe`` beside ``llama-server.exe``."""
    return f"{BINARNAME}.exe" if sys.platform == "win32" else BINARNAME


def programm_finden(llama_server: Path | None) -> Path | None:
    """``llama-tts``, resolved next to the already-resolved ``llama-server``.

    The speech server already names its own binary (app/modellrunner.py,
    ``programm_finden``); asking PATH independently here could hand back a
    build from a different llama.cpp checkout — one that may not carry
    Qwen3-TTS support at all. PATH is only the fallback for a machine where
    the two happen to live apart.

    On Windows the sibling is looked for with its ending: the bare name is
    never a file there, and the voice answered "llama-tts not found" with the
    program lying right beside the server.
    """
    if llama_server is not None:
        neben = llama_server.parent / _program_file_name()
        if neben.is_file():
            return neben
    gefunden = shutil.which(BINARNAME)
    return Path(gefunden) if gefunden else None


def proben_auflisten(ordner: Path) -> list[str]:
    """The voice samples lying flat in the speech folder — names only, the
    same shape ``modelle_auflisten`` answers for the GGUF files beside them
    (app/modellrunner.py)."""
    if not ordner.is_dir():
        return []
    return sorted(p.name for p in ordner.glob("*.wav") if p.is_file())


def _stimmprobe_pruefen(ordner: Path, name: str) -> Path:
    """The voice sample, or a refusal when it does not live in the voice
    folder — the same containment check the model picker itself relies on
    (app/modellrunner.py, the loader behind ``passende_mmproj``)."""
    ziel = (ordner / name).resolve()
    if ziel.parent != ordner.resolve() or not ziel.is_file():
        raise SprechenNichtMoeglich("stimmprobe_ungueltig")
    return ziel


# What a recording made in the window is called: this word and the lowest
# free number, so the first one is ``stimmprobe-1.wav`` and, once that is
# deleted, the next one takes the number again.
PROBE_VORSATZ = "stimmprobe-"


def naechste_probe(ordner: Path) -> str:
    """The lowest ``stimmprobe-N.wav`` whose name is not taken in the folder
    — by a file, a folder or anything else lying under that name."""
    nummer = 1
    while os.path.lexists(ordner / f"{PROBE_VORSATZ}{nummer}.wav"):
        nummer += 1
    return f"{PROBE_VORSATZ}{nummer}.wav"


def probe_sichern(ordner: Path, daten: bytes) -> str:
    """Writes one recording into the voice folder under the next free name
    and answers that name. Only a WAV is kept: the voice model reads nothing
    else, and a file that is none would stand in the list as a sample that
    can never speak."""
    if daten[:4] != b"RIFF" or daten[8:12] != b"WAVE":
        raise SprechenNichtMoeglich("stimmprobe_ungueltig")
    ordner.mkdir(parents=True, exist_ok=True)
    while True:
        name = naechste_probe(ordner)
        try:
            # Exclusive creation: a second recording saved at the same
            # moment cannot overwrite the first one's name.
            datei = open(ordner / name, "xb")  # noqa: SIM115 - closed below
        except FileExistsError:
            continue
        try:
            with datei:
                datei.write(daten)
        except OSError:
            # A recording that did not fit must not stay behind as a sample.
            (ordner / name).unlink(missing_ok=True)
            raise
        return name


def probe_pfad(ordner: Path, name: str) -> Path:
    """A voice sample for the window to hand out or delete: inside the voice
    folder as speaking requires, and a WAV by its name as well — the folder
    also holds the models, and a delete that took any file of it would take
    those too."""
    if not name.lower().endswith(".wav"):
        raise SprechenNichtMoeglich("stimmprobe_ungueltig")
    return _stimmprobe_pruefen(ordner, name)


def probe_loeschen(ordner: Path, name: str) -> None:
    """Deletes one voice sample."""
    probe_pfad(ordner, name).unlink()


def probe_dauer(pfad: Path) -> float | None:
    """The length of a WAV in seconds, read from its header alone — the
    chunk with the byte rate and the chunk with the data size. ``None`` for
    a file that is not laid out that way."""
    try:
        with open(pfad, "rb") as datei:
            kopf = datei.read(12)
            if kopf[:4] != b"RIFF" or kopf[8:12] != b"WAVE":
                return None
            byterate = 0
            while True:
                chunk = datei.read(8)
                if len(chunk) < 8:
                    return None
                kennung, groesse = chunk[:4], int.from_bytes(chunk[4:], "little")
                if kennung == b"fmt ":
                    if groesse > 64:
                        return None
                    format_ = datei.read(groesse)
                    if len(format_) < 12:
                        return None
                    byterate = int.from_bytes(format_[8:12], "little")
                elif kennung == b"data":
                    # A header written before the length was known says so
                    # with all ones: no length to read from it.
                    if not byterate or groesse == 0xFFFFFFFF:
                        return None
                    return round(groesse / byterate, 2)
                else:
                    datei.seek(groesse, 1)
                # Chunks are padded to an even length.
                if groesse % 2:
                    datei.seek(1, 1)
    except OSError:
        return None


class SpeakCancelled(Exception):
    """The sentence was asked for no longer: the program was ended."""


# How often a running program is looked at for the cancel.
_CANCEL_POLL_SECONDS = 0.25


def _laufen(
    befehl: list[str], *, cancel: threading.Event | None, timeout: float, eingabe: str | None = None,
) -> subprocess.CompletedProcess:
    """Runs the program to its end, or ends it: when ``cancel`` is set, or
    when ``timeout`` runs out (raised as ``subprocess.TimeoutExpired``).
    ``eingabe`` is handed to the program on its standard input."""
    prozess = subprocess.Popen(
        befehl, stdin=subprocess.PIPE if eingabe is not None else None,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        encoding="utf-8", errors="replace", **no_window(),
    )
    start = time.monotonic()
    while True:
        try:
            ausgabe, fehler = prozess.communicate(input=eingabe, timeout=_CANCEL_POLL_SECONDS)
            return subprocess.CompletedProcess(befehl, prozess.returncode, ausgabe, fehler)
        except subprocess.TimeoutExpired:
            # The input has been handed over with the first call; the next
            # calls only wait for the end.
            eingabe = None
        if cancel is not None and cancel.is_set():
            prozess.kill()
            prozess.communicate()
            raise SpeakCancelled()
        if time.monotonic() - start >= timeout:
            prozess.kill()
            prozess.communicate()
            raise subprocess.TimeoutExpired(befehl, timeout)


# The same runner, for the voices of the system (app/system_voice.py).
programm_laufen = _laufen


def sample_path(ordner: Path, name: str) -> Path:
    """The voice sample as a path inside the voice folder, or a refusal —
    for the one who loads the voice once for a whole conversation
    (app/voice_service.py) and so does not go through ``sprechen``."""
    return _stimmprobe_pruefen(ordner, name)


def sprechen(
    programm: Path,
    modell: Path,
    mmproj: Path,
    text: str,
    *,
    sprache: str,
    ordner: Path,
    stimmprobe: str | None = None,
    sampling: dict[str, float] | None = None,
    schichten: int | None = None,
    faeden: int = 0,
    cancel: threading.Event | None = None,
) -> bytes:
    """One sentence, spoken once, as WAV bytes. ``cancel``, once set, ends the
    program and raises ``SpeakCancelled``.

    ``llama-tts`` only writes to a file (``-o``), never to standard output,
    so a temporary target is unavoidable — read back and removed before
    this returns.

    The five generation values arrive as one dict (``sampling``) — one door,
    not two. Without a dict the values of the constants above stand in. With
    one, exactly the values it carries go to the program, each as its flag,
    and a value it leaves out is no flag at all: the program takes its own
    ("Auto"). An empty ``sprache`` is no ``--tts-lang`` either.
    """
    probe = _stimmprobe_pruefen(ordner, stimmprobe) if stimmprobe else None
    werte = (
        {
            "temperature": TEMPERATUR,
            "top_k": TOP_K,
            "top_p": TOP_P,
            "min_p": MIN_P,
            "repeat_penalty": WIEDERHOLUNGSSTRAFE,
        }
        if sampling is None
        else sampling
    )
    with tempfile.TemporaryDirectory() as tmp:
        ziel = Path(tmp) / "stimme.wav"
        befehl = [
            str(programm),
            "-m", str(modell),
            "-mm", str(mmproj),
            "-p", text,
            *(["--tts-lang", sprache] if sprache else []),
            "-o", str(ziel),
            # The model's own values stand in the constants above and are
            # beaten by whatever the settings carry (app/diktatsprachewahl.py),
            # in the engine's own flag order. The layer flag spells its long
            # name: llama-tts knows -ngl, --gpu-layers and --n-gpu-layers,
            # and --ngl is not one of them. No count named is the engine's
            # own "auto": the flag is left out.
            *(["--n-gpu-layers", str(schichten)] if schichten is not None else []),
            # The context is named, as the kept voice names its own: without
            # it the engine takes the model's (32768) and a Mac with 8 GB
            # cannot hold the cache of one sentence.
            "-c", str(VOICE_CONTEXT_SIZE),
            *(["--temp", str(werte["temperature"])] if "temperature" in werte else []),
            *(["--top-k", str(int(werte["top_k"]))] if "top_k" in werte else []),
            *(["--top-p", str(werte["top_p"])] if "top_p" in werte else []),
            *(["--min-p", str(werte["min_p"])] if "min_p" in werte else []),
            *(["--repeat-penalty", str(werte["repeat_penalty"])] if "repeat_penalty" in werte else []),
        ]
        # Zero means "the engine decides", exactly as on the chat servers —
        # and it travels as no flag at all.
        if faeden:
            befehl += ["-t", str(faeden)]
        if probe is not None:
            befehl += ["--tts-speaker-file", str(probe)]
        start = time.monotonic()
        try:
            antwort = _laufen(befehl, cancel=cancel, timeout=ZEITGRENZE)
        except subprocess.TimeoutExpired:
            raise SprechenNichtMoeglich("stimme_zeitueberschreitung") from None
        dauer = time.monotonic() - start
        if antwort.returncode != 0 or not ziel.exists():
            log.warning(
                "llama-tts failed after %.1fs (code %s): %s",
                dauer, antwort.returncode, antwort.stderr[-500:],
            )
            raise SprechenNichtMoeglich("stimme_fehlgeschlagen")
        wav = ziel.read_bytes()
        log.info(
            "llama-tts spoke %d bytes in %.1fs (%d characters, voice=%s)",
            len(wav), dauer, len(text), probe.name if probe else "-",
        )
        return wav


__all__ = [
    "BINARNAME",
    "MIN_P",
    "TEMPERATUR",
    "TOP_K",
    "TOP_P",
    "WIEDERHOLUNGSSTRAFE",
    "ZEITGRENZE",
    "SpeakCancelled",
    "SprechenNichtMoeglich",
    "proben_auflisten",
    "programm_finden",
    "programm_laufen",
    "sample_path",
    "sprechen",
]
