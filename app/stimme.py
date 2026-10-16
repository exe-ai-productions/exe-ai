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
import shutil
import subprocess
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


def programm_finden(llama_server: Path | None) -> Path | None:
    """``llama-tts``, resolved next to the already-resolved ``llama-server``.

    The speech server already names its own binary (app/modellrunner.py,
    ``programm_finden``); asking PATH independently here could hand back a
    build from a different llama.cpp checkout — one that may not carry
    Qwen3-TTS support at all. PATH is only the fallback for a machine where
    the two happen to live apart.
    """
    if llama_server is not None:
        neben = llama_server.parent / BINARNAME
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


class SpeakCancelled(Exception):
    """The sentence was asked for no longer: the program was ended."""


# How often a running program is looked at for the cancel.
_CANCEL_POLL_SECONDS = 0.25


def _laufen(
    befehl: list[str], *, cancel: threading.Event | None, timeout: float
) -> subprocess.CompletedProcess:
    """Runs the program to its end, or ends it: when ``cancel`` is set, or
    when ``timeout`` runs out (raised as ``subprocess.TimeoutExpired``)."""
    prozess = subprocess.Popen(
        befehl, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        encoding="utf-8", errors="replace", **no_window(),
    )
    start = time.monotonic()
    while True:
        try:
            ausgabe, fehler = prozess.communicate(timeout=_CANCEL_POLL_SECONDS)
            return subprocess.CompletedProcess(befehl, prozess.returncode, ausgabe, fehler)
        except subprocess.TimeoutExpired:
            pass
        if cancel is not None and cancel.is_set():
            prozess.kill()
            prozess.communicate()
            raise SpeakCancelled()
        if time.monotonic() - start >= timeout:
            prozess.kill()
            prozess.communicate()
            raise subprocess.TimeoutExpired(befehl, timeout)


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
    not two: what the settings carry beats the constants above, and a value
    they leave out stays at the constant it always was.
    """
    probe = _stimmprobe_pruefen(ordner, stimmprobe) if stimmprobe else None
    werte = {
        "temperature": TEMPERATUR,
        "top_k": TOP_K,
        "top_p": TOP_P,
        "min_p": MIN_P,
        "repeat_penalty": WIEDERHOLUNGSSTRAFE,
        **(sampling or {}),
    }
    with tempfile.TemporaryDirectory() as tmp:
        ziel = Path(tmp) / "stimme.wav"
        befehl = [
            str(programm),
            "-m", str(modell),
            "-mm", str(mmproj),
            "-p", text,
            "--tts-lang", sprache,
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
            "--temp", str(werte["temperature"]),
            "--top-k", str(int(werte["top_k"])),
            "--top-p", str(werte["top_p"]),
            "--min-p", str(werte["min_p"]),
            "--repeat-penalty", str(werte["repeat_penalty"]),
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
    "sample_path",
    "sprechen",
]
