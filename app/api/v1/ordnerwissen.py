"""Getting a shared folder's ``exe.md`` back from the copy we kept.

app/ordnerwissen.py has been writing a copy of every shared folder's notes
since the day a tool call could destroy the original — the net under the
delete protection, and the only layer that survives a ``run_command``. What
it did not have was an exit: the copy was written, and the only thing that
ever read it back was a test. A safety net nobody can reach is not a safety
net, it is a folder full of bytes.

Two routes, and the second one is the point. The first says whether a copy
is kept for a folder and whether that folder currently has notes at all —
which together are what any offer to restore has to be built on. The second
puts the copy back.

**The road exists now, the button is a separate piece of work.** Nothing in
the interface calls either route yet, and wiring them into the folder
section of the window is its own job. The road comes first on purpose: a
button without a route is a promise, while a route without a button is only
quiet — and quiet is what the copy already was.

**Which folder is never the client's free choice.** Exactly like the route
that shows a folder in the file manager (app/api/v1/arbeitsordner.py), a
request names a chat and one of that chat's shared folders. The path itself
comes out of the chat row, so nothing can ask to have a file written into
somewhere the user never opened up, however it is spelled.

**The outcome travels in the answer, not in the status code.** Putting a
copy back has five endings — written, already identical, nothing kept,
other notes are in the way, the folder refused the write — and they are
statements about one file rather than failures of the request. They come
back as the keys from app/ordnerwissen.py, which the window will turn into
a sentence out of its own catalogue. Only the two boundary checks raise: an
unknown chat and a folder that is not this chat's.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app import ordnerwissen
from app.api.v1.generierung import forget_all_system_messages
from app.api.abhaengigkeiten import (
    hole_benutzer_id,
    hole_config,
    hole_repositories,
    hole_sprache,
)
from app.config import Config
from app.db import Repositories
from app.i18n import t

router = APIRouter(prefix="/ordnerwissen", tags=["ordnerwissen"])


class Ziel(BaseModel):
    """Which chat, and which of its shared folders. Never a free path — the
    handler only accepts one that is already in the chat's list."""

    chat_id: str
    pfad: str


class Stand(BaseModel):
    """What there is to offer for one folder, right now."""

    ordner: str
    sicherung: bool
    zeichen: int = 0
    notiz: bool = False


class Zurueckgeholt(BaseModel):
    """What the attempt did. ``ergebnis`` is one of the keys in
    app/ordnerwissen.py, never a sentence: the wording belongs to the
    interface catalogue, in whichever language the window is open."""

    ordner: str
    ergebnis: str
    zeichen: int = 0


def _pruefen(
    chat_id: str,
    pfad: str,
    repositories: Repositories,
    user_id: str,
    sprache: str,
) -> None:
    """Refuses everything that is not this chat's own shared folder.

    Compared as the strings stand, not as they resolve. Two reasons pull the
    same way: the register in app/ordnerwissen.py is keyed by exactly the
    string a chat carries, so a path that merely leads to the same place
    would find nothing filed under it — and a comparison that resolves is a
    comparison that can be talked into agreeing.
    """
    chat = repositories.chats.holen(chat_id, user_id=user_id)
    if chat is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, t("fehler.chat_nicht_gefunden", sprache)
        )
    if pfad not in (chat.working_dirs or []):
        # Not "not found": the folder may well exist. It is simply not one
        # this chat shared, and that is the whole boundary.
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, t("fehler.ablage_ordner_fremd", sprache)
        )


@router.get("/sicherung", response_model=Stand, summary="Is there a backup?")
def stand(
    chat_id: str,
    pfad: str,
    repositories: Repositories = Depends(hole_repositories),
    config: Config = Depends(hole_config),
    user_id: str = Depends(hole_benutzer_id),
    sprache: str = Depends(hole_sprache),
) -> Stand:
    """Whether a copy is kept for this folder, and whether the notes are
    still there.

    Both halves in one answer, because the offer only makes sense out of the
    pair: a copy is worth showing when the file it copies has gone missing.
    Asking two routes for that would answer about two different moments.
    """
    _pruefen(chat_id, pfad, repositories, user_id, sprache)
    kopie = ordnerwissen.sicherung(pfad, config.datenverzeichnis)
    return Stand(
        ordner=pfad,
        sicherung=kopie is not None,
        # Counted on the text the prompt carries, not on the raw copy, so
        # line endings and trailing blank lines do not add to the number.
        zeichen=len(ordnerwissen.plain_text(kopie or "")),
        # The same reading the prompt does, so "there are notes" means here
        # what it means everywhere else: a file holding only whitespace is
        # no notes at all.
        notiz=bool(ordnerwissen.lesen([pfad])),
    )


@router.post(
    "/wiederherstellen",
    response_model=Zurueckgeholt,
    summary="Restore the backup",
)
def wiederherstellen(
    daten: Ziel,
    repositories: Repositories = Depends(hole_repositories),
    config: Config = Depends(hole_config),
    user_id: str = Depends(hole_benutzer_id),
    sprache: str = Depends(hole_sprache),
) -> Zurueckgeholt:
    """Puts the kept copy back into the folder — or says why it did not.

    The refusal is the interesting half. Notes that say something else are
    never quietly replaced by an older copy; the answer comes back with
    ``IM_WEG`` and the folder is untouched, which leaves the choice with
    whoever can actually read both texts.
    """
    _pruefen(daten.chat_id, daten.pfad, repositories, user_id, sprache)
    ergebnis = ordnerwissen.wiederherstellen(daten.pfad, config.datenverzeichnis)
    if ergebnis.ergebnis == ordnerwissen.ZURUECK:
        # The user's own change: the next message of every chat sharing the
        # folder carries the notes restored, instead of waiting for the next
        # fold the way a change the model made does
        # (app/api/v1/generierung.py, `_system_messages`).
        forget_all_system_messages()
    return Zurueckgeholt(
        ordner=ergebnis.ordner,
        ergebnis=ergebnis.ergebnis,
        zeichen=len(ordnerwissen.plain_text(ergebnis.text)),
    )
