"""Checking a list of shared working folders before it is stored or used.

The same rule holds for a chat's shares and for the folders picked in the job
start window, so it lives in one place instead of being copied into each route
where the two could quietly drift apart on what counts as a valid share:

* an absolute path — a relative one has no fixed meaning once the working
  directory is whatever the desktop handed over;
* that exists and is a folder — a share pointing at nothing only fails later;
* resolved, with duplicates merged — sharing the same folder twice is not an
  error but not a second share either.

There is no cap on how many: a project shares all of its folders with every
chat in it, and nothing technical depends on a number.

A bad entry raises ``HTTPException`` with the same wording the chat route
already used, so the message a user sees does not depend on where they shared
the folder.

**A folder already shared is not checked again.** It was checked when it was
set, and since then it may have been moved away — which the window now says
out loud instead of leaving it silent (app/ordnerstand.py). A missing share
stays in the list until the user decides what to do with it, and while it
stands there every OTHER change to the list would fail on it: adding a folder,
and above all re-choosing the SECOND missing folder while the first is still
waiting. So the caller names what this chat already had, and those entries
pass through as they are.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from fastapi import HTTPException

from app import ordnerwissen
from app.i18n import t

def pruefen(
    rohe: list[str], sprache: str, bekannte: Sequence[str] = ()
) -> list[str]:
    """The folders, cleaned and resolved — or an ``HTTPException`` saying why not.

    ``bekannte`` are the shares this chat already carries: they keep their
    stored spelling and are not looked for on disk again. Everything else is
    a new share and gets the full check.
    """
    gepruefte: list[str] = []
    for eintrag in rohe:
        if eintrag in bekannte:
            if eintrag not in gepruefte:
                gepruefte.append(eintrag)
            continue
        pfad = Path(eintrag).expanduser()
        if not pfad.is_absolute():
            raise HTTPException(400, t("fehler.arbeitsverzeichnis_relativ", sprache))
        if not pfad.exists():
            raise HTTPException(400, t("fehler.arbeitsverzeichnis_fehlt", sprache))
        if not pfad.is_dir():
            raise HTTPException(400, t("fehler.arbeitsverzeichnis_kein_ordner", sprache))
        aufgeloest = str(pfad.resolve())
        if aufgeloest not in gepruefte:
            gepruefte.append(aufgeloest)
    return gepruefte


def share(
    folders: list[str], language: str, known: Sequence[str] = (), data_dir: Path | None = None
) -> list[str]:
    """What sharing folders does, wherever the share is made — the folder
    chip (app/api/v1/chats.py) and the tool ``create_folder``
    (app/tools/create_folder.py): the list is checked as above, and a folder
    new to it gets its ``exe.md`` (app/ordnerwissen.py) — no dialogue, no
    question, never over a file that is already there, and a failure there
    is logged and swallowed. Here rather than inside ``pruefen``, which the
    job start window calls too. Returns the checked list; storing it is the
    caller's, who knows whether it belongs to a chat or to its project."""
    checked = pruefen(folders, language, bekannte=known)
    ordnerwissen.anlegen([folder for folder in checked if folder not in known], data_dir)
    return checked
