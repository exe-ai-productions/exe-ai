"""Opening a folder — or a single file — in the system's own program.

The counterpart of the folder dialog: that one brings a path in, this one
shows where a path leads. Whoever fetches models wants to see what has
accumulated — and the fastest honest answer is the folder itself, in the
file manager the system already has. A stored document wants the same
answer one level down: not the folder it sits in, but the file itself,
opened by whatever program the system already reads it with.

Three systems, three built-in commands:

* macOS   — ``open``
* Windows — ``explorer``
* Linux   — ``xdg-open``; may be missing on a machine without a desktop,
            which is why the caller gets a clean no instead of a stack trace.

The command is fired and forgotten. ``explorer`` in particular returns exit
codes that mean nothing, so nobody waits for one — the folder window either
appears or the system said no immediately.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import sys
from pathlib import Path

log = logging.getLogger(__name__)


class OeffnenNichtMoeglich(Exception):
    """This system has no way to show a folder."""


def _befehl() -> list[str] | None:
    if sys.platform == "darwin":
        return ["open"]
    if sys.platform.startswith("win"):
        return ["explorer"]
    if shutil.which("xdg-open"):
        return ["xdg-open"]
    return None


def ordner_oeffnen(pfad: Path) -> None:
    """Shows the folder in the file manager, creating it if it is not there.

    Creating first is deliberate: the model folder exists only after the
    first download, but the button that leads here exists before — and a
    button that errors on a fresh machine would be wrong exactly once, at
    the worst moment.
    """
    befehl = _befehl()
    if befehl is None:
        raise OeffnenNichtMoeglich()
    ziel = Path(pfad).expanduser()
    ziel.mkdir(parents=True, exist_ok=True)
    try:
        subprocess.Popen(
            [*befehl, str(ziel)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError as fehler:
        log.warning("Folder cannot be opened: %s", fehler)
        raise OeffnenNichtMoeglich() from None


def datei_oeffnen(pfad: Path) -> None:
    """Opens one file in the system's default program for it.

    Unlike ``ordner_oeffnen`` this never creates anything: a document's file
    either exists because it was stored, or the caller has nothing to hand
    the system. The command itself is the same on every platform — ``open``,
    ``explorer`` and ``xdg-open`` all take a file path exactly as they take a
    folder path.
    """
    befehl = _befehl()
    if befehl is None:
        raise OeffnenNichtMoeglich()
    ziel = Path(pfad).expanduser()
    try:
        subprocess.Popen(
            [*befehl, str(ziel)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError as fehler:
        log.warning("File cannot be opened: %s", fehler)
        raise OeffnenNichtMoeglich() from None


def open_file_in_editor(pfad: Path) -> None:
    """Opens one text file in the computer's text editor, whatever program
    the system has for the file's ending: a file with an ending of no program
    (a template) would otherwise bring up a question of which one to use.

    macOS asks for its default text editor (``open -t``), Windows takes the
    Notepad every installation has, and elsewhere the file goes to whatever
    ``xdg-open`` knows for it.
    """
    ziel = Path(pfad).expanduser()
    if sys.platform == "darwin":
        befehl = ["open", "-t", str(ziel)]
    elif sys.platform.startswith("win"):
        befehl = ["notepad.exe", str(ziel)]
    elif shutil.which("xdg-open"):
        befehl = ["xdg-open", str(ziel)]
    else:
        raise OeffnenNichtMoeglich()
    try:
        subprocess.Popen(befehl, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError as fehler:
        log.warning("File cannot be opened in an editor: %s", fehler)
        raise OeffnenNichtMoeglich() from None


def show_file(pfad: Path) -> None:
    """Shows one file in the file manager, selected in its folder where the
    system can do that (macOS ``open -R``, Windows ``explorer /select,``),
    else the folder it lies in."""
    ziel = Path(pfad).expanduser()
    if sys.platform == "darwin":
        befehl = ["open", "-R", str(ziel)]
    elif sys.platform.startswith("win"):
        befehl = ["explorer", f"/select,{ziel}"]
    elif shutil.which("xdg-open"):
        befehl = ["xdg-open", str(ziel.parent)]
    else:
        raise OeffnenNichtMoeglich()
    try:
        subprocess.Popen(befehl, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError as fehler:
        log.warning("File cannot be shown: %s", fehler)
        raise OeffnenNichtMoeglich() from None
