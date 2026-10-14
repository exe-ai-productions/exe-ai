"""Where the built-in file tools may reach — the shared folders and nothing else.

The rule was written for the shell tool and holds for every tool that touches
the disk, so it lives in one place instead of in five:

* **The share is the boundary.** A working folder shared with the chat IS the
  permission. Inside it nothing asks again.
* **Outside it, the model asks.** The path leaves the shared folders, the
  ordinary confirmation appears above the input field, and only a yes lets the
  call through.
* **Without a shared folder the tools stay shut.** No folder, no file work.

The file tools have it easier than the shell: their path arrives as an
explicit argument, so there is nothing to guess. The shell has to scan a free
command string for anything path-shaped, which is a heuristic and stays in
``shell.py`` where it belongs.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

from app import dokumentablage

# What a tool says when nobody shared a folder with the chat. One wording for
# all of them: the user reads it once and knows what to do.
OHNE_ORDNER = (
    "No working folder is shared with this chat. Ask the user to share one using the folder "
    "icon in the input bar. This tool remains unavailable until then."
)


# What a file tool adds when a path led nowhere in a chat that shares no
# folder of the user's. Such a chat still has a folder of its own — its
# private one in the program's data (app/dokumentablage.py), where a bare
# name lands — and a refusal that only named the path sent the model trying
# the same name again or searching the whole disk. One wording for every
# tool: it says where a relative path points, and nothing else — that folder
# is the chat's place to work, not a state to be put right.
NO_FOLDER_SHARED = (
    "No folder is shared with this chat, so a relative path resolves to the chat's private "
    "folder within the program's data directory."
)


# The files that sit beside the permission rules and hold keys, rules or
# server logins. They are named, because that folder also holds things that
# are no secret.
PRIVATE_FILES = (
    "config.yaml", "config.yaml.sicherung", ".env", "berechtigungen.json", "mcp_servers.json",
)

# What of the data folder stays open to a run besides its own folders: the
# scripts a schedule may start.
OPEN_IN_DATA = ("scripts",)

# What a tool says when a call reaches into a private place of the program.
# One wording for the file tools and the shell.
PRIVATE_PLACE = (
    "'{path}' is a private place of the program (its chats, settings, keys and notes) and is "
    "closed to tools in every mode. Work in the folders shared with this run."
)


class GrenzeVerletzt(Exception):
    """The call cannot run: no shared folder, or the path is unusable."""


def aufgeloest(pfad: str, wurzel: Path) -> Path:
    """The absolute path this argument means, relative ones against the root."""
    roh = Path(pfad).expanduser()
    return (roh if roh.is_absolute() else wurzel / roh).resolve()


def liegt_innerhalb(pfad: Path, ordner: list[Path]) -> bool:
    for freigegeben in ordner:
        try:
            pfad.relative_to(freigegeben)
            return True
        except ValueError:
            continue
    return False


def wurzeln(ordner: list[str]) -> list[Path]:
    """The shared folders as resolved paths, in the order they were shared."""
    return [Path(o).resolve() for o in ordner]


def inside(path: Path, folder: Path) -> bool:
    """Whether ``path`` lies in ``folder``, letter case aside: the Mac's
    disk ignores it, so two spellings of the data folder are the same
    folder there, and a check that told them apart could be walked
    around."""
    inner = str(path.resolve()).casefold()
    outer = str(folder.resolve()).casefold().rstrip(os.sep)
    return inner == outer or inner.startswith(outer + os.sep)


def no_folder_shared(ordner: list[str], data_dir: Path | str | None) -> bool:
    """Whether this run works in a chat that shares no folder of the user's.

    Then the first folder of the run is the chat's private one under the
    data folder (app/dokumentablage.py ``ordner_dieses_chats``) — the folder
    a relative path resolves against. A job run starts in a folder of the
    user's and never in there; without a data folder to measure against (a
    caller of its own) nothing can be said, and the answer is no.
    """
    if not ordner or data_dir is None:
        return False
    return inside(Path(ordner[0]), Path(data_dir) / dokumentablage.CHATDATEIEN)


def missing(ziel: Path, ordner: list[str], data_dir: Path | str | None) -> str:
    """The refusal for a path that does not exist — with the way out when
    the chat shares no folder, where a missing path is no typo but the
    wrong place altogether."""
    text = f"'{ziel}' does not exist."
    if no_folder_shared(ordner, data_dir):
        return f"{text} {NO_FOLDER_SHARED}"
    return text


def _is_own_chat_folder(basis: Path, data_dir: Path | str | None) -> bool:
    """Whether ``basis`` is a chat's own folder under THIS data folder —
    the place the program makes for a chat that shares nothing
    (app/dokumentablage.py ``chatordner``). Measured against the real data
    folder, never against a name: a folder of the user's that happens to
    sit in a ``chat_files`` folder of its own is the user's, and is never
    made behind their back. Without a data folder nothing can be said, and
    the answer is no."""
    if data_dir is None:
        return False
    own = dokumentablage.chatordner(Path(data_dir), basis.name)
    return own is not None and inside(basis, own) and inside(own, basis)


def ordner_pruefen(ordner: list[str], data_dir: Path | str | None = None) -> str | None:
    """Why no path at all can be worked on in these folders, or None.

    The part of ``ziel`` that does not depend on the path — so a caller can
    ask it the moment a call begins, before the model has written a single
    character of an argument that could only be refused afterwards.

    A check and nothing more: it makes no folder. A chat's own folder that
    is not there yet is no reason to refuse — the call that runs makes it
    (``prepare_folders``) — so it passes here; a folder of the user's that
    went missing is theirs to set again.
    """
    if not ordner:
        return OHNE_ORDNER
    basis = Path(ordner[0]).resolve()
    if basis.is_dir() or _is_own_chat_folder(basis, data_dir):
        return None
    return f"The shared folder '{basis}' no longer exists. Ask the user to select it again."


def prepare_folders(ordner: list[str], data_dir: Path | str | None = None) -> str | None:
    """``ordner_pruefen`` for a call that is about to RUN — and the one
    place a missing own chat folder is made.

    That folder the program makes and the user never set, so asking the
    user to set it again leads nowhere: it is made here, and when that
    fails, the reason the operating system gave is what the call is told.
    Only a call that runs gets here; the check at a call's beginning, while
    the model is still writing it, makes nothing.
    """
    grund = ordner_pruefen(ordner, data_dir)
    if grund is not None:
        return grund
    basis = Path(ordner[0]).resolve()
    if not basis.is_dir():
        try:
            basis.mkdir(parents=True, exist_ok=True)
        except OSError as fehler:
            return f"Cannot access directory {basis}: {fehler.strerror or fehler}"
    return None


def ziel(pfad: str, ordner: list[str], data_dir: Path | str | None = None) -> Path:
    """The path a call works on — or an explanation why it cannot work at all.

    Raises when no folder is shared: the tools are shut then, and saying so
    plainly beats returning something that only fails later. Called as the
    call runs, so a chat's own folder is made here when it is missing
    (``prepare_folders``); ``data_dir`` is what tells that folder apart.
    """
    grund = prepare_folders(ordner, data_dir)
    if grund is not None:
        raise GrenzeVerletzt(grund)
    basis = wurzeln(ordner)[0]
    try:
        return aufgeloest(pfad, basis)
    except (OSError, RuntimeError) as fehler:
        raise GrenzeVerletzt(f"'{pfad}' is not a valid path ({fehler}).") from fehler


def aussenpfad(
    argumente: dict[str, Any], ordner: list[str], schluessel: str = "path"
) -> str | None:
    """The path this call reaches to outside the shared folders, or None.

    This is both the reason to ask and the answer to "why am I being asked?" —
    the prompt shows the path, so the decision rests on something visible.
    """
    if not ordner:
        return None
    roh = str(argumente.get(schluessel) or "").strip()
    if not roh:
        return None
    freigaben = wurzeln(ordner)
    try:
        gemeint = aufgeloest(roh, freigaben[0])
    except (OSError, RuntimeError):
        return None
    return None if liegt_innerhalb(gemeint, freigaben) else str(gemeint)


def private_check(
    ordner: list[str],
    data_dir: Path | str | None,
    settings_dir: Path | str | None = None,
) -> Callable[[Path], bool] | None:
    """The test "is this path a private place of the program?", or None
    where the run knows neither the data folder nor the settings folder.

    Private is everything in the data folder — the database with the chats,
    the notes, the folders of other chats — and the files beside the
    permission rules that hold keys (``PRIVATE_FILES``). Open stay the
    folders this run was given that lie in the data folder (its own chat
    folder, the dock, the pictures) and the scripts folder. A share that is
    the data folder or lies above it opens nothing of it: a chat that shares
    the user's home folder does not share the program's chats with it.
    """
    if data_dir is None and settings_dir is None:
        return None
    data = Path(data_dir).resolve() if data_dir is not None else None
    settings = Path(settings_dir).resolve() if settings_dir is not None else None
    given: list[Path] = []
    if data is not None:
        for entry in ordner:
            try:
                folder = Path(entry).resolve()
            except (OSError, RuntimeError):
                continue
            # Strictly below the data folder: a folder above it, or it
            # itself, would hand over everything in it.
            if inside(folder, data) and not inside(data, folder):
                given.append(folder)
        given.extend(data / name for name in OPEN_IN_DATA)

    def private(path: Path) -> bool:
        if data is not None and inside(path, data):
            return not any(inside(path, folder) for folder in given)
        if settings is not None:
            folded = str(path.resolve()).casefold()
            return any(
                folded == str(settings / name).casefold() for name in PRIVATE_FILES
            )
        return False

    return private


def private_target(
    argumente: dict[str, Any],
    ordner: list[str],
    private: Callable[[Path], bool],
    schluessel: str = "path",
) -> str | None:
    """The path this call names when it is a private place, or None.

    A call without a path works in the first shared folder, so that one is
    judged then — a share that is the data folder itself is refused too.
    """
    if not ordner:
        return None
    base = wurzeln(ordner)[0]
    roh = str(argumente.get(schluessel) or "").strip()
    try:
        gemeint = aufgeloest(roh, base) if roh else base
    except (OSError, RuntimeError):
        return None
    return str(gemeint) if private(gemeint) else None
