"""Starting and stopping a model server, with everything it does in view.

The program has always waited for a model server somebody else had started.
Everything that mattered about that server — how much context it holds, how
much of it sits on the graphics card, which file it loaded, why — lived in a
shell script nobody opens, and its output went into a log file nobody reads.

This module runs the server itself, so those things can be shown.

**GGUF only, on purpose.** `llama-server` is a plain program with prebuilt
versions for macOS, Windows and Linux, which means it can travel with an
installer. MLX is a Python package and would mean carrying a second Python
into a frozen program; it is a fine way to run a model on this machine and a
poor way to hand one to somebody else.

Three rules hold the whole thing together:

* **One server at a time.** Two would fight over the port and, worse, over
  the memory — the second one usually takes the machine down with it.
* **Only files from the model folder.** The path never comes from outside;
  a name is looked up in the folder, and what is not in there cannot start.
* **No shell.** The program is called directly with its arguments, so
  nothing in a file name can turn into a command.
"""

from __future__ import annotations

import json
import logging
import os
import re
import secrets
import shutil
import socket
import subprocess
import sys
import threading
import time

from app import modellzuordnung
from app import prozessstopp
from app.feineinstellungen import Feineinstellungen, flags as feinflags
from app.ggufmtp import BEIFAHRER, MODELL, dateiart, traegt_eingebettetes_mtp
from app.modelldownload import alle_teile, teil_von
from app.modellprofil import startflags
from app.no_console import no_window
from app.prozessspeicher import rss_gb
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

log = logging.getLogger(__name__)

# How long the reader waits for a process whose pipe has closed to become
# reapable. Only ever a moment in practice; the ceiling is there so a helper
# that outlived its parent and kept the pipe cannot hold the thread for good.
NACHLAUF_FRIST = 5.0

# Where a package manager puts it. Searched after PATH, because somebody who
# put it somewhere of their own means it.
BEKANNTE_ORTE = (
    "/opt/homebrew/bin/llama-server",
    "/usr/local/bin/llama-server",
    "/usr/bin/llama-server",
)

# How much of the output is kept. Enough to see a start fail, not enough to
# grow into a memory leak on a server that runs for days.
PROTOKOLL_ZEILEN = 400

# The log verbosity every server is started with. At the engine's default
# level the load report stays silent — measured on the engine itself: 12
# lines, none of them about flash attention — so the lines read back below
# only exist from this level on. Measured cost: ~230 lines for a small
# model's start, ~250 for a 16-GB one, both inside the ring buffer above;
# a request then adds a fixed handful of lines, not one per token, so a
# server that runs for days stays cheap to read.
PROTOKOLL_STUFE = 4

# The flag we send is always "auto" — the engine decides for itself. Newer
# engine builds say what they DECIDED in a line of their own at load time:
#   "resolve_fused_ops: Flash Attention enabled"
# while their configuration line ("llama_context: flash_attn    = auto")
# only repeats the wish. Older builds put the result into that very line
# ("enabled"/"disabled"), so it stays as the fallback — and it also carries
# the answer when the flag is forced off, where the newer line does not
# appear at all.
_FLASH_ATTN_ERGEBNIS_MUSTER = re.compile(
    r"resolve_fused_ops:\s*Flash Attention\s+(\w+)"
)
_FLASH_ATTN_MUSTER = re.compile(r"flash_attn\s*=\s*(\w+)")

# The drafter (multi-token prediction / speculative decoding) prints exactly
# one line as it initialises, and it comes BEFORE the "model loaded" line:
#   "common_speculative_init_result: loading draft model '…'"
# Read it back the same way flash attention is read back. A drafter can be
# *configured* at start and still never engage; this line is the proof it did.
# If the server reaches "model loaded" without it, the pairing did not take.
#
# The same line covers a model drafting against its OWN embedded weights
# (no separate --model-draft): the engine's every speculative backend
# (draft-simple, draft-mtp, draft-eagle3, …) funnels through this one log
# call, confirmed by the engine's own build carrying exactly one instance
# of this string regardless of which backend fires. No second pattern
# needed for the embedded case — still worth the one live run to see the
# real line before trusting it in practice.
_MTP_MUSTER = re.compile(r"common_speculative_init_result")
# The line that follows the one above when no speculative backend was chosen
# at all: the server loaded the draft file and then drafts with nothing.
# That is the proof the pairing did not take, and it comes before "model
# loaded", so it is read the same way.
_NO_BACKEND_PATTERN = re.compile(r"no implementations specified for speculative decoding")
_BEREIT_MUSTER = re.compile(r"llama_server:\s*model loaded")
# The line llama-server writes when a file's architecture is not one it
# knows, measured with diffusiongemma-26B-A4B-it-Q5_K_M.gguf on build 10310:
#   E llama_model_load: error loading model: unknown model architecture: 'diffusion-gemma'
_UNKNOWN_ARCH_PATTERN = re.compile(r"unknown model architecture: '([^']+)'")

# Where the started server's process id is noted. The server outlives the
# service on purpose (its own process group, so a service crash does not
# take the model down mid-answer) — but after a restart the service must
# find its own orphan again, or the next start dies quietly on a taken port.
PID_DATEI = ".modellserver.pid"

# The environment variable both sides share: the started llama-server reads
# it as its API key, the provider reads it to sign requests. Loopback keeps
# strangers out of the network; the key keeps out the browser on this very
# machine, where any open web page may knock on localhost. It travels as
# environment on purpose — on the command line it would sit in plain sight
# in the process list and the window that shows the command.
SCHLUESSEL_VARIABLE = "EXE_RUNNER_API_KEY"


def _ist_llama_server(pid: int) -> bool:
    """Is this process id really our kind of server?

    Asked before an orphan is ended: process ids get recycled, and ending
    whatever happens to hold one now would hit an innocent program.
    """
    try:
        antwort = subprocess.run(
            ["ps", "-p", str(pid), "-o", "comm="],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=5,
            **no_window(),
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return "llama-server" in antwort.stdout


def programm_finden(vorgabe: str | None = None) -> Path | None:
    """The llama-server binary, or nothing if this machine has none.

    The program the settings name always wins. On the Mac the copy the
    program fetched itself comes next — its pinned build is the one tested
    here and uses the Mac's graphics chip, while a package manager's
    llama-server on PATH is whatever version happened to be installed —
    then PATH and the package managers' places. On Windows and Linux the
    own copy is a build for the processor alone, so PATH and the package
    managers' places come first: a llama-server installed there may well
    be built for the graphics card, and that one is meant.
    """
    if vorgabe:
        pfad = Path(vorgabe).expanduser()
        return pfad if pfad.is_file() and os.access(pfad, os.X_OK) else None

    from app.paketierung import daten
    from app.serverdownload import gefundener_server

    eigener = gefundener_server(daten())
    if eigener is not None and not os.access(eigener, os.X_OK):
        eigener = None
    if eigener is not None and sys.platform == "darwin":
        return eigener

    gefunden = shutil.which("llama-server")
    if gefunden:
        return Path(gefunden)

    for ort in BEKANNTE_ORTE:
        pfad = Path(ort)
        if pfad.is_file() and os.access(pfad, os.X_OK):
            return pfad
    return eigener


@dataclass
class Modelldatei:
    name: str
    groesse_gb: float


def ist_mmproj(name: str) -> bool:
    """A vision projector, not a model.

    It belongs NEXT to a model (llama-server's ``--mmproj``) and cannot be
    started on its own — offered as a model it would sit in the picker as
    one that never answers.
    """
    return "mmproj" in name.lower()


def ist_mtp(pfad: Path) -> bool:
    """A multi-token-prediction module, not a model.

    It cannot chat on its own, but it is the best draft a model can get:
    a few hundred megabytes trained alongside the big file to guess its
    next words. Started with ``--spec-type draft-mtp`` it rides along;
    offered as a model it would sit in the picker as one that never
    answers. The file's own header decides (``ggufmtp.dateiart``), never
    its name: a whole model with its prediction layers built in may well
    carry "mtp" in its name.
    """
    return dateiart(pfad) == BEIFAHRER


# The companions live in their own sub-folders of the model folder, so the
# model folder itself shows only startable models — and the drafter folder
# shows only drafters, the vision folder only projectors. The file names stay
# the same, so the manifest and the name heuristics keep binding.
MTP_ORDNER = "mtp"
VISION_ORDNER = "vision"


def _begleiter_ordner(ordner: Path, rolle: str) -> Path:
    """The sub-folder a companion of this role lives in."""
    return ordner / (MTP_ORDNER if rolle == "mtp" else VISION_ORDNER)


def draft_path(folder: Path, model: str, drafter: str) -> Path | None:
    """Where a chosen draft model lies, or None when it lies nowhere allowed.

    A prediction module lives in ``mtp/``; a small sibling model drafting by
    the plain path is a whole model and stays in the model folder itself, so
    both folders are asked, ``mtp/`` first. A draft is a plain file name,
    never a path, and nothing outside the two folders can be reached through
    it. In the model folder the name is judged the way the model list judges
    it, and the main model's own file is never its draft.
    """
    if not drafter or Path(drafter).name != drafter:
        return None
    for base in (_begleiter_ordner(folder, "mtp"), folder):
        candidate = base / drafter
        if not candidate.is_file() or candidate.resolve().parent != base.resolve():
            continue
        if base == folder and (
            not drafter.endswith(".gguf")
            or ist_mmproj(drafter)
            or ist_mtp(candidate)
            or candidate.samefile(folder / model)
        ):
            continue
        return candidate
    return None


# One sorting at a time: the listings below are asked from several threads
# at once, and of two that move the same file the second would find its
# source gone.
_sorting = threading.Lock()
# The loose files that stayed where they lay, said once each: the folder is
# read again and again while a window shows it, and a file that stays is
# one line in the log, not one per reading.
_left_lying: set[Path] = set()
# The folders the start sorted. A reading sorts these and no other: a folder
# that holds another kind of model has no companions to keep apart, and
# nothing in it is moved.
_tended: set[Path] = set()


def begleiter_einsortieren(ordner: Path) -> None:
    """Move loose companion files out of the model folder into their own
    sub-folders, so each folder shows only its own kind — and a whole model
    out of ``mtp/`` back into the model folder. Done when the service starts.

    A plain rename inside the same folder — the name is kept, so the manifest
    bond and the name heuristics still hold. A name already taken in the
    target is left where it lies (a log line says so), never overwritten.
    Drafters are told apart by their header, both ways: a drafter lying in
    the model folder moves into ``mtp/``, and a whole model lying in
    ``mtp/`` (sorted there once by its name) moves back. A header that says
    neither leaves the file where it is.

    From here on every reading of this folder sorts what is laid into it
    loose (``_loose_companions_sorted``).
    """
    _tended.add(ordner)
    _sort_companions(ordner, models_back=True)


def _loose_companions_sorted(ordner: Path) -> None:
    """The same sorting with every reading of the folder (the three listings
    below), for what lies loose: a model laid into the folder by hand while
    the program runs brings its projector along loose, and the pairing reads
    ``vision/`` alone — that model would have no eyes until the next start.

    The way back is left to the start: a whole model lying in ``mtp/`` still
    drafts from there (``draft_path`` asks that folder first), so nothing is
    missing while it waits.
    """
    if ordner in _tended:
        _sort_companions(ordner, models_back=False)


def _sort_companions(ordner: Path, *, models_back: bool) -> None:
    """Nothing here fails the reading it is part of. A file that cannot be
    renamed right now — locked by whoever is still copying it — stays where
    it lies and is tried again with the next reading, and a folder that
    cannot be looked through is left to the listing itself."""
    with _sorting:
        try:
            if not ordner.is_dir():
                return
            # A file that is gone has nothing left to be said about.
            for gone in [p for p in _left_lying if not p.exists()]:
                _left_lying.discard(gone)
            for p in sorted(ordner.glob("*.gguf")):
                if not p.is_file():
                    continue
                if ist_mmproj(p.name):
                    unter = VISION_ORDNER
                elif ist_mtp(p):
                    unter = MTP_ORDNER
                else:
                    continue
                _umziehen(p, ordner / unter / p.name)
            mtp_ordner = ordner / MTP_ORDNER
            if models_back and mtp_ordner.is_dir():
                for p in sorted(mtp_ordner.glob("*.gguf")):
                    if p.is_file() and not ist_mmproj(p.name) and dateiart(p) == MODELL:
                        _umziehen(p, ordner / p.name)
        except OSError as fault:
            log.debug("companions not sorted in %s: %s", ordner, fault)


def _umziehen(p: Path, ziel: Path) -> None:
    """A plain rename that never overwrites and never fails its caller: a
    taken name stays where it is, and so does a file that cannot be moved
    right now. Either is said once for the file."""
    try:
        if ziel.exists():
            reason = f"target taken: {ziel}"
        else:
            ziel.parent.mkdir(exist_ok=True)
            p.rename(ziel)
            _left_lying.discard(p)
            return
    except OSError as fault:
        reason = f"it cannot be moved right now ({fault.strerror or fault}): {p}"
    if p not in _left_lying:
        _left_lying.add(p)
        log.warning("companion stays in place, %s", reason)


def modelle_auflisten(ordner: Path) -> list[Modelldatei]:
    """The startable GGUF files in the model folder, largest first.

    Companion files are not models: vision projectors (mmproj) belong NEXT
    to a model, and multi-token-prediction modules (mtp) ride along as
    draft modules — offered as models, both would sit in the picker as
    entries that never answer. They live in sub-folders (a flat glob passes
    them by), and one lying loose is moved there before the folder is read;
    the projector's name filter and the drafter's header check stay as a
    safety net for one that could not be moved.

    A split model is one entry: part 1 names it and carries the size of all
    parts — the server is started with part 1 and finds the rest beside it.
    Parts 2 to N never appear on their own, and a version with a part
    missing does not appear at all, because it cannot start.
    """
    if not ordner.is_dir():
        return []
    _loose_companions_sorted(ordner)
    dateien = []
    for p in sorted(ordner.glob("*.gguf")):
        if not p.is_file() or ist_mmproj(p.name):
            continue
        teil = teil_von(p.name)
        if teil is None:
            if not ist_mtp(p):
                dateien.append(Modelldatei(name=p.name, groesse_gb=round(p.stat().st_size / 1e9, 1)))
            continue
        if teil[1] != 1:
            continue
        teile = [p.with_name(name) for name in alle_teile(p.name)]
        if all(t.is_file() for t in teile):
            summe = sum(t.stat().st_size for t in teile)
            dateien.append(Modelldatei(name=p.name, groesse_gb=round(summe / 1e9, 1)))
    return sorted(dateien, key=lambda d: d.groesse_gb, reverse=True)


def mtp_auflisten(ordner: Path) -> list[Modelldatei]:
    """The draft modules lying in the ``mtp/`` sub-folder, with their sizes.

    Sizes ride along because the draft is a passenger in the memory plan —
    a quarter gigabyte is honest weight, just not much of it. Only a file
    whose header says drafter is offered; anything else lying there is not.
    One lying loose in the model folder is moved here first.
    """
    _loose_companions_sorted(ordner)
    unter = ordner / MTP_ORDNER
    if not unter.is_dir():
        return []
    return [
        Modelldatei(name=p.name, groesse_gb=round(p.stat().st_size / 1e9, 1))
        for p in sorted(unter.glob("*.gguf"))
        if p.is_file() and not ist_mmproj(p.name) and ist_mtp(p)
    ]


def mmproj_auflisten(ordner: Path) -> list[str]:
    """The vision companions lying in the ``vision/`` sub-folder — names only.

    The name check stays even though the folder already sorts by kind: a file
    hand-dropped into vision/ that is not a projector is not offered as one.
    A projector lying loose in the model folder is moved here first, so one
    laid down while the program runs is found without a restart.
    """
    _loose_companions_sorted(ordner)
    unter = ordner / VISION_ORDNER
    if not unter.is_dir():
        return []
    return sorted(p.name for p in unter.glob("*.gguf") if p.is_file() and ist_mmproj(p.name))


def passende_mmproj(ordner: Path, modell: str) -> Path | None:
    """The projector that belongs to this model, or nothing.

    The tie is the file name: the projector must read ``<prefix>mmproj…``
    where ``<prefix>`` is also how the model file starts, at least four
    characters of it. That keeps ``Qwen3.6-35B-A3B-mmproj…`` away from
    ``Qwen3.6-27B-…`` — their shared prefix ends before the word mmproj —
    and a bare ``mmproj-BF16.gguf`` away from everything, because nothing
    guarantees whose eyes those are.
    """
    beste: tuple[int, Path] | None = None
    for name in mmproj_auflisten(ordner):
        laenge = 0
        # Stopping at the shorter name is the point of a prefix measure.
        for a, b in zip(name, modell, strict=False):
            if a != b:
                break
            laenge += 1
        rest = name[laenge:]
        # The shared prefix may end right before a separator — the model
        # continues with its quant, the projector with "-mmproj".
        if rest[:1] in "-._":
            rest = rest[1:]
        if laenge < 4 or not rest.startswith("mmproj"):
            continue
        if beste is None or laenge > beste[0]:
            beste = (laenge, ordner / VISION_ORDNER / name)
    return beste[1] if beste else None


@dataclass
class Lauf:
    """What is running right now — the answer to every status question."""

    modell: str
    kontext: int
    schichten: int
    port: int
    # The draft model for speculative decoding, when one was chosen — a
    # small model guesses ahead, the big one only checks.
    drafter: str | None = None
    # The vision projector this server was started with, when one was chosen
    # by hand — otherwise the auto-paired one leaves no name here.
    vision: str | None = None
    # The engine levers this server was started with. Kept because they are
    # otherwise unreadable afterwards: they leave no trace in the answer, and
    # a form that cannot show them makes the user set them again from
    # scratch — or, worse, believe the defaults are what is running.
    fein: Feineinstellungen | None = None


# The engine's own names for the five generation values the speech settings
# carry (app/diktatsprachewahl.py): only what is set travels, and it stands
# AFTER the model's published lore — the engine reads last-wins, so a set
# value beats the card's habit without editing it.
_SAMPLING_FLAGS = {
    "temperature": "--temp",
    "top_k": "--top-k",
    "top_p": "--top-p",
    "min_p": "--min-p",
    "repeat_penalty": "--repeat-penalty",
}


def samplingflags(werte: dict[str, float] | None) -> list[str]:
    """The set generation values as engine flags, in a fixed order."""
    if not werte:
        return []
    zeile: list[str] = []
    for name, flag in _SAMPLING_FLAGS.items():
        wert = werte.get(name)
        if wert is None:
            continue
        zeile += [flag, str(wert)]
    return zeile


class Modellrunner:
    """One model server, started and stopped from the program."""

    def __init__(
        self,
        modelle_ordner: Path,
        programm: str | None = None,
        *,
        port: int = 8080,
        pid_datei: str = PID_DATEI,
        schluessel_variable: str = SCHLUESSEL_VARIABLE,
        zusatzflags: tuple[str, ...] = (),
        sampling_flags: bool = True,
        bereit_callback: Callable[[str, float], None] | None = None,
        zustand_callback: Callable[[bool, bool | None, str | None, str | None], None]
        | None = None,
    ) -> None:
        """One server of one kind.

        Everything that could collide between two of these is a parameter:
        the port, the note that finds an orphan again, the environment
        variable carrying the key, and the flags that make the difference
        between a chat server and an embedding server. The first build had
        them as module constants, and a second server would have taken the
        first one's port and overwritten its key on start.

        ``bereit_callback`` (model, load time in seconds) fires
        once per start, the moment the server's own log says it is ready —
        never for the embedding or vision-encoder runners, which have
        nothing to preload ahead of.

        ``zustand_callback`` (running, flash attention, drafter, unknown
        architecture) fires whenever any of those four answers changes, so a
        window can be told instead of asking. Built the same way and for the
        same reason as the one above: this module knows about no bus and no
        window, and whoever hands the callback in decides which runner is
        worth announcing — every server of the program hands one in, each
        under its own name (app/runnerzustand.py).
        """
        self._ordner = Path(modelle_ordner).expanduser()
        self._programm_vorgabe = programm
        self._port = port
        self._pid_datei = pid_datei
        self._schluessel_variable = schluessel_variable
        self._zusatzflags = tuple(zusatzflags)
        self._sampling_flags = sampling_flags
        self._bereit_callback = bereit_callback
        self._zustand_callback = zustand_callback
        # When the current start began — read once, at the readiness line,
        # to turn it into a duration.
        self._start_zeit: float | None = None
        self._prozess: subprocess.Popen | None = None
        self._lauf: Lauf | None = None
        # Whether the server that was up last went down because somebody
        # ended it here, rather than dying on its own. `laeuft()` answers
        # False for both, and so does `lauf()` — the difference exists in
        # this class and nowhere else (see `von_hand_gestoppt`).
        self._von_hand_gestoppt = False
        # The key this server was started with. Kept here as well as in the
        # environment: the environment is one namespace for the whole
        # process, and whoever wants to talk to THIS server should ask THIS
        # runner rather than a global.
        self._schluessel: str | None = None
        self._protokoll: deque[str] = deque(maxlen=PROTOKOLL_ZEILEN)
        # Flash attention's state, caught the moment its line passes by.
        # The log is a ring buffer — a busy server pushes the one load-time
        # line out of it, so the answer must be kept, not re-searched.
        self._flash_attn: bool | None = None
        # The drafter's real state, caught the same way. Whether one was asked
        # for, whether its init line passed, whether the server reported ready:
        # the three together are the honest answer, because "configured" is
        # not "running".
        self._drafter_gewuenscht: bool = False
        self._mtp_gesehen: bool = False
        self._mtp_no_backend: bool = False
        self._bereit_gesehen: bool = False
        self._unknown_arch: str | None = None
        self._schloss = threading.Lock()
        # The announcement's own lock, and the last thing it said. Both
        # belong to `_zustand_melden` alone — see there for why the order of
        # two threads' announcements has to be held, not just their reading.
        self._meldeschloss = threading.Lock()
        self._zuletzt_gemeldet: tuple[bool, bool | None, str | None, str | None] | None = None

    # --- What can be seen without starting anything ------------------------

    @property
    def programm(self) -> Path | None:
        return programm_finden(self._programm_vorgabe)

    @property
    def ordner(self) -> Path:
        return self._ordner

    @property
    def port_vorgabe(self) -> int:
        return self._port

    @property
    def schluessel(self) -> str | None:
        """The key this server signs with, or nothing while it is down."""
        return self._schluessel if self.laeuft() else None

    def modelle(self) -> list[Modelldatei]:
        return modelle_auflisten(self._ordner)

    def mmproj(self) -> list[str]:
        return mmproj_auflisten(self._ordner)

    def mtp(self) -> list[Modelldatei]:
        return mtp_auflisten(self._ordner)

    def laeuft(self) -> bool:
        # Read once into a local. Two loads of the field is a hole a thread
        # can fall through: the reader thread asks this while a stop clears
        # the field between the check and the call, and the answer is an
        # AttributeError on None instead of False.
        prozess = self._prozess
        return prozess is not None and prozess.poll() is None

    def lauf(self) -> Lauf | None:
        return self._lauf if self.laeuft() else None

    def von_hand_gestoppt(self) -> bool:
        """Whether the last server this runner held was ended through
        ``stoppen`` rather than dying on its own.

        Nothing else can answer it. ``laeuft()`` is False for a server that
        never came up, one that died mid-load and one that was switched off,
        and ``lauf()`` hides behind ``laeuft()`` and answers None for all
        three alike. Measured, on this class: after ``stoppen`` the run and
        the process handle are cleared and the pid note is deleted, while a
        killed process leaves all three standing — so the difference IS
        readable from the outside, but only by reading private state or a
        file on disk. This says it out loud instead.

        Whoever needs it: app/modellvorlauf.py, where a stop pressed while
        the nineteen gigabytes were still being read used to look exactly
        like a load that died on the way up — same missing measurement, same
        cold server — and put the preload of that file to sleep for good.
        """
        return self._von_hand_gestoppt

    def protokoll(self) -> list[str]:
        return list(self._protokoll)

    def unknown_architecture(self) -> str | None:
        """The architecture the last start failed on because llama-server
        does not know it, named the way the server named it — or nothing
        while a server runs, or when the start failed for another reason.
        Shown when the start fails, not guessed beforehand: only the server
        knows which architectures it carries."""
        return None if self.laeuft() else self._unknown_arch

    def flash_attn_zustand(self) -> bool | None:
        """Whether flash attention ended up on, read off the server's own
        words instead of asked for — the flag sent is always "auto", so that
        line is the only place the true answer lives. Caught when the line
        passes through the log and kept, because the ring buffer forgets.
        None while the log has not reached it yet (server still loading, or
        not running). A bool, so the engine's wording lives in this one
        method and nowhere else."""
        if not self.laeuft():
            return None
        return self._flash_attn

    def _mtp_antwort(self) -> str | None:
        """The drafter's answer read off the flags alone, without asking
        whether the process is still alive.

        Split out so a state snapshot can be taken cheaply and ATOMICALLY:
        whoever already knows the liveness answer must not go and ask for it
        a second time, because between the two questions it can change, and
        a triple built from two different moments describes no moment at
        all. ``mtp_zustand`` below is this plus the guard.
        """
        if not self._drafter_gewuenscht:
            return None
        # The draft file was loaded, but the server says that no way of
        # drafting with it was chosen: it never took, whatever else it said.
        if self._mtp_no_backend:
            return "fehler"
        if self._mtp_gesehen:
            return "aktiv"
        if self._bereit_gesehen:
            return "fehler"
        return None

    def mtp_zustand(self) -> str | None:
        """The drafter's honest state, read off the server's own words — not
        the flag sent at start, which only proves it was *configured*.

        ``None``   → server down, no drafter asked for, or still loading:
                       nothing to show. The liveness guard matters: the
                       log flags survive a stopped process, the state must
                       not.
        ``"aktiv"``  → the speculative-init line passed, so the draft truly
                       engaged (blue).
        ``"fehler"`` → the server reached "model loaded" without that line, or
                       said that no way of drafting was chosen at all: a
                       drafter was configured but never took — a broken
                       pairing (red).
        """
        if not self.laeuft():
            return None
        return self._mtp_antwort()

    def _zustand_melden(self) -> None:
        """Says out loud whether the server runs, whether flash attention
        ended up on, whether the drafter engaged, and which architecture the
        last start failed on because the build does not know it — the four
        facts the window shows without ever having asked for them.

        ONE LIVENESS READ, and the whole triple built from it. Asking three
        times gave three answers from three moments: a server that exits
        between the first and the second turns into ``(True, None, None)``,
        which is byte-identical to the honest "just started, nothing known
        yet" and would latch a window onto a dead server.

        UNDER ITS OWN LOCK, and the callback with it. Two threads announce
        here — the request that starts or stops the server, and the thread
        reading the server's log — and without it they interleave: the
        reader reads "running", is overtaken by a stop that announces "gone",
        and then announces "running" after it. The lock is this method's
        alone and is never held while anything else is taken, so it cannot
        meet ``_schloss`` in a deadlock; the callback is inside it because
        the ORDER of the two announcements is the thing being protected, not
        just the reading.

        UNCHANGED IS UNSAID. Every fire point may call this whenever it
        likes; a triple equal to the last one announced goes no further.
        That is what lets the coarse "something moved" test in the line
        reader stay coarse, and what makes the announcement at the end of
        the reader thread free after an ordinary stop.

        A callback that throws costs the announcement and nothing else —
        the same rule the readiness one follows, and for the same reason:
        this is a reader thread that must not die.
        """
        if self._zustand_callback is None:
            return
        try:
            with self._meldeschloss:
                laeuft = self.laeuft()
                zustand = (
                    laeuft,
                    self._flash_attn if laeuft else None,
                    self._mtp_antwort() if laeuft else None,
                    # Read from the same liveness answer: while a server runs
                    # it has no failed start to name.
                    None if laeuft else self._unknown_arch,
                )
                if zustand == self._zuletzt_gemeldet:
                    return
                self._zustand_callback(*zustand)
                # Written only once it has actually gone out. Recording it
                # first latches a state as "said" that was never said, and
                # every later attempt to say the same thing is then swallowed
                # as a repeat — for good.
                self._zuletzt_gemeldet = zustand
        except Exception:  # noqa: BLE001 - a broken listener must not stop the reader
            log.exception("Status report of the model server failed")

    def _zeile_aufnehmen(self, zeile: str, quelle=None) -> None:
        if quelle is not None and quelle is not self._prozess:
            # Asked again here, as late as possible before the first write.
            # The reader's own check is a whole line older by the time it
            # gets here, and a server that was replaced in between must not
            # have its words written into its successor's state.
            return
        zeile = zeile.rstrip("\n")
        self._protokoll.append(zeile)
        # The two answers this line could move, read before and after. Both
        # are settled here and nowhere else — the server prints them on its
        # own, seconds after it was started — so a start announcement alone
        # would leave both at "unknown" under a server that had long been up.
        #
        # The ANSWERS, not the raw flags behind them: `_bereit_gesehen`
        # moves on every start without moving anything the window shows, and
        # comparing flags would announce that. `_mtp_antwort` costs three
        # attribute reads and asks the process nothing, so this is exact and
        # cheap at once — and `_zustand_melden` swallows a repeat anyway, so
        # this test only has to be coarse enough not to MISS a change.
        vorher = (self._flash_attn, self._mtp_antwort())
        # The decision line first, the configuration line as fallback: on a
        # line that carries both words the result is the one that counts.
        # Values other than enabled/disabled — the newer builds' "auto" in
        # the configuration line — say nothing and change nothing.
        treffer = _FLASH_ATTN_ERGEBNIS_MUSTER.search(zeile)
        if treffer is None:
            treffer = _FLASH_ATTN_MUSTER.search(zeile)
        if treffer:
            wert = treffer.group(1).lower()
            if wert in ("enabled", "disabled"):
                self._flash_attn = wert == "enabled"
        if _MTP_MUSTER.search(zeile):
            self._mtp_gesehen = True
        if _NO_BACKEND_PATTERN.search(zeile):
            self._mtp_no_backend = True
        unknown = _UNKNOWN_ARCH_PATTERN.search(zeile)
        if unknown:
            self._unknown_arch = unknown.group(1)
        if _BEREIT_MUSTER.search(zeile) and not self._bereit_gesehen:
            self._bereit_gesehen = True
            if self._bereit_callback is not None and self._start_zeit is not None:
                dauer = time.monotonic() - self._start_zeit
                modell = self._lauf.modell if self._lauf else ""
                try:
                    self._bereit_callback(modell, dauer)
                except Exception:  # noqa: BLE001 - a broken store must not stop the reader
                    log.exception("Load time measurement for '%s' not saved", modell)
        if (self._flash_attn, self._mtp_antwort()) != vorher:
            self._zustand_melden()

    def befehl(
        self,
        modell: str,
        kontext: int,
        schichten: int,
        port: int,
        drafter: str | None = None,
        fein: Feineinstellungen | None = None,
        vision: str | None = None,
        faeden: int | None = None,
        sampling: dict[str, float] | None = None,
    ) -> list[str]:
        """The command as it will be run — the same list, shown and executed.

        Building it in one place is the point: what the window shows cannot
        drift away from what actually starts.
        """
        zeile = [
            str(self.programm or "llama-server"),
            "--model", str(self._ordner / modell),
            "--ctx-size", str(kontext),
            "--n-gpu-layers", str(schichten),
            "--host", "127.0.0.1",
            "--port", str(port),
            # Without this the engine's load report never appears, and the
            # flash-attention state (and any future line read back the same
            # way) would stay unknown forever. See PROTOKOLL_STUFE.
            "--log-verbosity", str(PROTOKOLL_STUFE),
        ]
        # Zero means "the engine decides", the same reading the threads
        # lever has everywhere else — so it travels as no flag at all.
        if faeden:
            zeile += ["-t", str(faeden)]
        # --jinja plus the family's published sampling lore — without these
        # a model's tool calls arrive in a language it was never taught. An
        # embedding server has no sampling and no tools, so it gets none of
        # it; what it needs instead is in `zusatzflags`.
        if self._sampling_flags:
            zeile += startflags(modell)
            # The set generation values stand behind the lore: last wins.
            zeile += samplingflags(sampling)
        zeile += list(self._zusatzflags)
        # The advanced section's levers. They say nothing where they agree
        # with the engine, so a command with none of them set looks exactly
        # as it did before the section existed.
        zeile += feinflags(fein)
        if drafter:
            draft = draft_path(self._ordner, modell, drafter)
            if draft is None:
                raise RunnerFehler("kein_modell")
            zeile += ["--model-draft", str(draft)]
            # The engine's default is no speculative backend at all, so a
            # draft file alone loads and then drafts with nothing. A
            # prediction module needs its own mode — fed into the plain
            # draft path it fails to build a context — and a small sibling
            # model is the plain path, named as such.
            zeile += ["--spec-type", "draft-mtp" if ist_mtp(draft) else "draft-simple"]
        elif traegt_eingebettetes_mtp(self._ordner / modell):
            # No separate draft file chosen, and the model's own header
            # says it carries its prediction layers already — the engine
            # drafts against itself, no --model-draft needed. Never both
            # paths at once: a chosen drafter always wins the branch above.
            zeile += ["--spec-type", "draft-mtp"]
        # A model whose eyes lie next to it gets them attached — that is the
        # whole difference between a vision model and the same model mute.
        # The declared projector wins over the name heuristic: the manifest is
        # written when the pair is fetched together, while the heuristic reads
        # shared prefixes and can pick the wrong one when two models share one.
        # A projector chosen by the caller wins over both the manifest and
        # the name heuristic: it is the escape for a companion whose file name
        # does not follow the "<model>-mmproj" convention, so the two can be
        # paired by hand. The name obeys the same folder boundary as every
        # other file a start may reach.
        if vision:
            basis = _begleiter_ordner(self._ordner, "mmproj").resolve()
            gewaehlt = (basis / vision).resolve()
            augen = gewaehlt if gewaehlt.parent == basis and gewaehlt.is_file() else None
        elif vision == "":
            # Chosen: none. The two empties are different answers here, the
            # same way they are for the draft above (see `starten`, where
            # `drafter is None` is what lets the manifest step in): `None` is
            # "nobody said", `""` is "said: no projector". Without this a
            # model whose eyes were switched off by hand got them back from
            # the name heuristic on the next start, and the row in the window
            # said "none" about a command line carrying --mmproj.
            augen = None
        else:
            augen = self._manifest_pfad(modell, "mmproj")
            if augen is None:
                augen = passende_mmproj(self._ordner, modell)
        if augen is not None:
            zeile += ["--mmproj", str(augen)]
        return zeile

    def _manifest_pfad(self, modell: str, rolle: str) -> Path | None:
        """The manifest companion for a model, as a path inside the folder.

        The name comes back validated and existing from the manifest; the
        resolve check here is the same folder boundary a start obeys, so a
        hand-edited note can never point a flag outside the model folder.
        """
        name = modellzuordnung.fuer(self._ordner, modell).get(rolle)
        if not name:
            return None
        # The companion lives in its own sub-folder; the boundary check is that
        # sub-folder, so a hand-edited note can still never point outside it.
        basis = _begleiter_ordner(self._ordner, rolle).resolve()
        pfad = (basis / name).resolve()
        if pfad.parent != basis or not pfad.is_file():
            return None
        return pfad

    # --- Starting and stopping ---------------------------------------------

    def belegt_gb(self) -> float | None:
        """Live resident memory of the running server, or None when idle."""
        with self._schloss:
            if self._prozess is None or self._prozess.poll() is not None:
                return None
            return rss_gb(self._prozess.pid)

    def starten(self, modell: str, *, kontext: int = 16384, schichten: int = 99,
                port: int | None = None, drafter: str | None = None,
                fein: Feineinstellungen | None = None,
                vision: str | None = None,
                faeden: int | None = None,
                sampling: dict[str, float] | None = None) -> Lauf:
        port = self._port if port is None else port
        with self._schloss:
            if self.laeuft():
                raise RunnerFehler("laeuft_schon")
            # A new start answers for itself, also when it is refused below:
            # the architecture an earlier start failed on is not its reason.
            self._unknown_arch = None

            programm = self.programm
            if programm is None:
                raise RunnerFehler("kein_programm")

            # A name, never a path: whatever is in the folder can start, and
            # nothing else can be reached by writing ../ in front of it.
            ziel = (self._ordner / modell).resolve()
            if ziel.parent != self._ordner.resolve() or not ziel.is_file():
                raise RunnerFehler("kein_modell")

            # No draft chosen by the caller: fall back to the one the manifest
            # declared for this model, so the bond survives a restart and the
            # status reports it. The manifest returns a validated, existing
            # name; the guard below is the same folder boundary either way.
            if drafter is None:
                drafter = modellzuordnung.fuer(self._ordner, modell).get("mtp")

            # The draft model obeys the same rule as the main one: a name
            # from its folders (mtp/ or, for a sibling model, the model
            # folder) or nothing.
            if drafter and draft_path(self._ordner, modell, drafter) is None:
                raise RunnerFehler("kein_modell")

            # The chosen projector, if any, obeys the same rule: a name from
            # the vision folder or nothing.
            if vision:
                vbasis = (self._ordner / VISION_ORDNER).resolve()
                vziel = (vbasis / vision).resolve()
                if vziel.parent != vbasis or not vziel.is_file():
                    raise RunnerFehler("kein_modell")

            # A taken port would let the new server die quietly while the
            # old one keeps answering — the settings in the form would then
            # look applied and never be.
            with socket.socket() as fuehler:
                if fuehler.connect_ex(("127.0.0.1", port)) == 0:
                    raise RunnerFehler("port_belegt")

            self._protokoll.clear()
            self._flash_attn = None
            # The bolt watches for the SAME proof either way: a chosen
            # drafter file, or the main model's own header carrying its
            # prediction layers. Both ask the engine to draft; only the
            # engine's own log line says whether it actually did.
            self._drafter_gewuenscht = bool(drafter) or traegt_eingebettetes_mtp(ziel)
            self._mtp_gesehen = False
            self._mtp_no_backend = False
            self._bereit_gesehen = False
            # A fresh server, nobody has stopped it yet — the answer belongs
            # to the run that is starting here, not to the one before it.
            self._von_hand_gestoppt = False
            self._start_zeit = time.monotonic()
            # A fresh key per start; the service keeps it in its own
            # environment, where the provider picks it up to sign requests.
            schluessel = secrets.token_urlsafe(24)
            os.environ[self._schluessel_variable] = schluessel
            self._schluessel = schluessel
            self._prozess = subprocess.Popen(
                self.befehl(modell, kontext, schichten, port, drafter, fein, vision, faeden, sampling),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                # The server writes UTF-8 whatever the system's own code page
                # is — read as that, or an umlaut in its log arrives broken.
                encoding="utf-8",
                # A byte that is not valid UTF-8 must never stop the reader.
                # At the verbosity this starts servers with, the engine
                # prints the model's whole vocabulary, and a vocabulary is
                # not text — one model's dump carries a lone 0xC4 sixty lines
                # in. Without this the reader thread dies on it, nothing
                # drains the pipe any more, and the server BLOCKS mid-load
                # for good: the process is alive, the port never opens, and
                # the window waits forever with no error anywhere. Measured
                # on a speech model; nothing about the fault is specific to
                # speech, and every runner of this class was exposed to it.
                errors="replace",
                bufsize=1,
                env={**os.environ, "LLAMA_API_KEY": schluessel},
                # No shell, and its own process group so stopping takes the
                # whole thing and not just the parent.
                start_new_session=True,
                **no_window(),
            )
            self._lauf = Lauf(
                modell=modell,
                kontext=kontext,
                schichten=schichten,
                port=port,
                drafter=drafter,
                vision=vision,
                fein=fein,
            )
            self._pid_merken(self._prozess.pid)
            # Before the reader thread, not after: that thread announces the
            # flash state the moment the line goes by, and a server whose
            # log reaches it first would have "flash known" arrive ahead of
            # "server up" — leaving the window with the older answer as the
            # newer one.
            self._zustand_melden()
            threading.Thread(target=self._mitlesen, daemon=True).start()
            return self._lauf

    def _mitlesen(self) -> None:
        """Keeps the output where it can be shown instead of in a file, and
        says so when the server goes away without anyone asking it to.

        The pipe closes exactly when the process ends, which makes the end
        of this loop the one place that learns about a death nobody ordered
        — an out-of-memory kill, a crash, a `kill` from a terminal. None of
        the other fire points can: they are all deliberate transitions, and
        a server that is merely loaded and idle prints no line at all. Left
        unsaid, the window keeps a green dot over a server that is gone,
        because nothing asks any more.

        A reader whose server has been REPLACED says nothing and reads no
        further. Stopping does not wait for this thread, so a stop pressed
        mid-load leaves a buffer of the old server's words still to come;
        written into the flags after a new server has started, they would be
        published as the new one's state — an old "flash disabled" turning
        the new server's dot red, and an old "model loaded" eating the latch
        that records the new one's load time.
        """
        prozess = self._prozess
        if prozess is None or prozess.stdout is None:
            return
        for zeile in prozess.stdout:
            if prozess is not self._prozess:
                return
            self._zeile_aufnehmen(zeile, prozess)
        if prozess is not self._prozess:
            return
        # The end of the pipe says the process has ended. It does NOT say the
        # kernel has made it reapable yet, and that is exactly what `laeuft()`
        # asks — so without this the death is announced as "still running",
        # which is word for word what was already said, and is swallowed as a
        # repeat. Measured at roughly one death in eighty, and unrecoverable
        # when it hits: nothing asks again.
        try:
            prozess.wait(timeout=NACHLAUF_FRIST)
        except subprocess.TimeoutExpired:
            pass
        with self._schloss:
            # A stop or a restart may have run while we waited, and either
            # has already said its piece. Safe to take the lock here and
            # nowhere else in this thread: the pipe is at its end, so nothing
            # is left to drain and a stop that holds the lock cannot be
            # waiting on us to drain it.
            if prozess is not self._prozess:
                return
            # Nobody else will. A death nobody ordered otherwise leaves the
            # handle, the run, the note on disk and the key in the
            # environment standing — and the next service start reads a note
            # whose process id may by then belong to somebody else.
            self._handle_loslassen()
        self._zustand_melden()

    def _handle_loslassen(self) -> None:
        """Lets go of the server this runner was holding: the handle, the
        run, the note on disk and the key.

        Its own method because two paths need all four and neither may do
        three of them — the ordinary stop, and the stop pressed on a server
        that had already died. The key dies with the server it belonged to,
        and it is THIS runner's key rather than the module constant: several
        runners share this class, each carrying the name of its own variable.
        """
        self._prozess = None
        self._lauf = None
        self._pid_vergessen()
        os.environ.pop(self._schluessel_variable, None)

    def stoppen(self) -> bool:
        with self._schloss:
            if self._prozess is None:
                return False
            if not self.laeuft():
                # It fell over on its own. There is nothing left to signal,
                # but this runner is still holding a dead handle and a note
                # that outlives it, and a window may still be showing the
                # server as up. Letting go and saying so is what makes a
                # stop pressed on a stale readout a way back to the truth
                # rather than a button that does nothing.
                self._handle_loslassen()
                self._zustand_melden()
                return False
            # The whole tree: llama-server starts helpers of its own, and a
            # signal to the parent alone leaves them holding the port. How
            # that is reached differs per system, which is why it lives in
            # its own module.
            prozessstopp.beenden(self._prozess)
            # Somebody ended this one; it did not fall over. Set before the
            # note is dropped, so the answer never depends on a file.
            self._von_hand_gestoppt = True
            self._handle_loslassen()
            self._zustand_melden()
            return True

    # --- The orphan after a service restart --------------------------------

    def _pid_merken(self, pid: int) -> None:
        try:
            self._ordner.mkdir(parents=True, exist_ok=True)
            (self._ordner / self._pid_datei).write_text(
                json.dumps({"pid": pid}), encoding="utf-8"
            )
        except OSError:
            # A note that cannot be written costs the cleanup after a crash,
            # never the start itself.
            pass

    def _pid_vergessen(self) -> None:
        (self._ordner / self._pid_datei).unlink(missing_ok=True)

    def aufraeumen(self, ist_unserer=_ist_llama_server) -> bool:
        """Ends the server a previous service run left behind.

        The server lives in its own process group, so a service crash or
        restart leaves it running — holding the port, answering with
        yesterday's settings, and making every new start die quietly. At
        service start this reads the note, makes sure the process really is
        a llama-server (ids get recycled), and ends it.
        """
        datei = self._ordner / self._pid_datei
        try:
            pid = int(json.loads(datei.read_text(encoding="utf-8"))["pid"])
        except (OSError, ValueError, KeyError, TypeError):
            return False
        self._pid_vergessen()
        if not ist_unserer(pid):
            return False
        if not prozessstopp.beenden_nach_pid(pid):
            return False
        # Announced although this runner never held that process: from the
        # window's side a port that was answering a moment ago is now dark,
        # which is the same fact as a stop and reads the same on the dot.
        self._zustand_melden()
        return True


class RunnerFehler(Exception):
    """Carries the key of the sentence to show, not the sentence itself."""

    def __init__(self, grund: str) -> None:
        super().__init__(grund)
        self.grund = grund
