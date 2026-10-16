"""The engine libraries the kept voice loads: an own, fixed copy.

The kept voice (app/voice_service.py, app/voice_worker.py) talks to
``libllama`` and ``libmtmd`` through their C interface, and that interface
changes from one llama.cpp build to the next — a build it was not written
against is refused. The libraries that lie beside the model server follow
the server's own build, which is chosen, updated and cleaned up on its own.
So the voice does not use them: it loads from a copy of the one build it was
written for (``app/voice_worker.py``, ``LAYOUT_BUILD``), in a folder of its
own, which no choice, update or clean-up of the servers touches.

The copy is fetched the way a server build is (app/serverdownload.py), by an
instance with a root folder of its own, in the same variant as the llama.cpp
that is installed. It starts by itself, once, the first time the voice needs
it and finds it missing; until it is there the voice is not kept and
``llama-tts`` speaks. ``llama-tts`` itself always comes from the build that
is active.

A fetch that did not bring the copy is not tried again for the rest of the
conversation it came up in — a page that announces the conversation every
few seconds would otherwise start one fetch after another while offline.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Callable, Protocol

from app import serverdownload
from app.voice_worker import LAYOUT_BUILD, library_names

log = logging.getLogger(__name__)

# Beside the server builds' own folder (``llama.cpp``), never inside it.
FOLDER = "voice-library"


class Fetch(Protocol):
    """What the library asks of a downloader (``serverdownload.Serverdownload``)."""

    def laeuft(self) -> bool: ...

    def starten(
        self, build: str | None = None, previous: str | None = None, variante: str | None = None
    ) -> object: ...


def libraries_in(folder: Path) -> Path | None:
    """The folder below ``folder`` that holds both libraries of the engine,
    or None when there is none (yet)."""
    core, audio = library_names()
    try:
        for hit in sorted(folder.rglob(core)):
            if hit.is_file() and (hit.parent / audio).is_file():
                return hit.parent
    except OSError:
        return None
    return None


class VoiceLibrary:
    def __init__(
        self,
        data_folder: Path,
        variant: Callable[[], str | None] = lambda: None,
        fetch: Fetch | None = None,
    ) -> None:
        """``variant`` names the variant of the installed llama.cpp when it
        has one (None: the plain build)."""
        root = Path(data_folder).expanduser() / FOLDER
        self._builds = root / serverdownload.ORDNER
        self._variant = variant
        self._fetch: Fetch = fetch or serverdownload.Serverdownload(root)
        self._lock = threading.Lock()
        self._tried = False

    def directory(self) -> Path | None:
        """The folder of the copy's libraries. Without the copy: None, and
        the fetch starts if none ran in this conversation yet."""
        variant = self._variant()
        folder = self._builds / serverdownload.bauordner_name(LAYOUT_BUILD, variant)
        with self._lock:
            # A copy that is being unpacked holds libraries that are not whole.
            if self._fetch.laeuft():
                return None
            found = libraries_in(folder)
            if found is not None or self._tried:
                return found
            self._tried = True
            try:
                self._fetch.starten(build=LAYOUT_BUILD, variante=variant)
            except serverdownload.ServerdownloadFehler as error:
                log.info("The voice's engine copy is not fetched: %s", error.grund)
            else:
                log.info("Fetching the engine copy %s for the kept voice", LAYOUT_BUILD)
        return None

    def conversation_over(self) -> None:
        """A fetch that failed may be tried again in the next conversation."""
        with self._lock:
            self._tried = False


__all__ = ["FOLDER", "VoiceLibrary", "libraries_in"]
