"""Managing chats and messages."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from app.api.abhaengigkeiten import (
    hole_benutzer_id,
    hole_config,
    hole_repositories,
    hole_sprache,
)
from app.config import Config
from app.api.v1.bilder import bilder_entfernen, bilder_verzeichnis
from app.api.v1.generierung import (
    hole_discovery,
    hole_generierungen,
    ordner_umzug_melden,
    ordner_umzug_vergessen,
    forget_system_message,
)
from app.api.v1.schemas import (
    ChatAendern,
    ChatAnlegen,
    ChatAntwort,
    ChatCompact,
    ChatCompactResult,
    LaufendeGenerierung,
    NachrichtAnlegen,
    NachrichtAntwort,
    NachrichtenSeite,
    OffeneFrage,
    OrdnerStand,
)
from app.db import Repositories
from app.db.repositories.einstellungen import chat_bereich
from app.discovery import Discovery
from app.events import Ereignisse, bus
from app.generationen import Generierungsverwaltung
from app.i18n import t
from app.tools.hintergrund import laeufe
from app import arbeitsordnerpruefung, bildfensterwahl, ordnerstand
from app import (
    chatverdichtung,
    dokumentbudget,
    dokumentcache,
    faltpause,
    tokenmass,
    verdichtung,
    verdichtungswahl,
)
from app.verlaufsbau import werkzeuggewicht, zeilentext

log = logging.getLogger(__name__)

router = APIRouter(prefix="/chats", tags=["chats"])

# Metrics keys a client may NOT set through the message route. The block a
# user turn carries in front of its text is the request route's own
# (``app/api/v1/generierung.py``, ``messages.set_clock_sentence``), and
# ``app/verlaufsbau.py`` reads the key back from the stored row for every
# later request of that chat: written from outside, it puts words of its own
# in front of a user's turn and changes what that request opens with. A
# record of what went out has to be what went out.
#
# ``werkzeuge`` is the record of a round that went out as a CALL: the same
# rebuild hands those entries back to the model as rounds it called itself —
# as calls (``_werkzeugzuege``), as a text block for a request that offers no
# tools (``_werkzeuge_als_text``), and into a fold's own request
# (``app/chatverdichtung.py``). Written from outside, a client picks the
# call's name and its result text without limit — a way to write anything at
# all into the model's context, through a round that never happened.
#
# ``skill_invocation`` and ``wake_notice`` are the same kind of record: the
# picked skill's note and instruction, and a wake's notice, both written by
# the request route and sent with their row on every later request
# (``app/verlaufsbau.py``, ``_with_invocation``, ``_with_wake_notice``). Written from outside, either
# puts any text at all into the model's context, in front of a user's words
# or behind a report.
#
# Everything else in `stats` stays as it is — a client's own numbers are its
# business; only the service's own fields are taken off.
DIENSTSCHLUESSEL = frozenset({"clock_sentence", "werkzeuge", "skill_invocation", "wake_notice"})


def _chat_oder_404(
    repositories: Repositories, chat_id: str, user_id: str, sprache: str
):
    chat = repositories.chats.holen(chat_id, user_id=user_id)
    if chat is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=t("fehler.chat_nicht_gefunden", sprache),
        )
    return chat


@router.post("", response_model=ChatAntwort, status_code=201, summary="Create a chat")
async def chat_anlegen(
    daten: ChatAnlegen,
    repositories: Repositories = Depends(hole_repositories),
    config: Config = Depends(hole_config),
    user_id: str = Depends(hole_benutzer_id),
    sprache: str = Depends(hole_sprache),
) -> ChatAntwort:
    # No more copying on creation: the system prompt lives in a file and is
    # freshly prepended on every request, and model parameters come from the
    # settings cascade rather than being carried along per chat.
    chat = repositories.chats.erstellen(
        user_id=user_id,
        title=daten.title or t("chat.unbenannt", sprache),
        endpoint_id=daten.endpoint_id,
    )
    await bus.veroeffentlichen(Ereignisse.CHAT_ERSTELLT, chat_id=chat.id, user_id=user_id)
    return ChatAntwort.aus(chat)


@router.get("", response_model=list[ChatAntwort], summary="List chats")
def chats_auflisten(
    suche: str | None = Query(
        default=None, description="Filters by title and message content."
    ),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    archived: bool = Query(default=False, description="List archived chats instead"),
    repositories: Repositories = Depends(hole_repositories),
    user_id: str = Depends(hole_benutzer_id),
    generierungen: Generierungsverwaltung = Depends(hole_generierungen),
) -> list[ChatAntwort]:
    chats = repositories.chats.auflisten(
        user_id=user_id, suche=suche, limit=limit, offset=offset, archived=archived
    )
    # One pass over the running generations, not one `fuer_chat` lookup per
    # chat in the list — the sidebar's own ring used to know only THIS
    # window's own runs; every window reloading this list now sees the
    # service's own answer.
    laufende_chat_ids = {g.chat_id for g in generierungen.laufende()}
    return [
        ChatAntwort.aus(chat, laeuft=chat.id in laufende_chat_ids) for chat in chats
    ]


@router.get("/{chat_id}", response_model=ChatAntwort, summary="Get a chat")
def chat_holen(
    chat_id: str,
    repositories: Repositories = Depends(hole_repositories),
    user_id: str = Depends(hole_benutzer_id),
    sprache: str = Depends(hole_sprache),
) -> ChatAntwort:
    return ChatAntwort.aus(_chat_oder_404(repositories, chat_id, user_id, sprache))


@router.get(
    "/{chat_id}/ordnerstand",
    response_model=OrdnerStand,
    summary="Missing working folders for a chat",
)
def ordnerstand_holen(
    chat_id: str,
    repositories: Repositories = Depends(hole_repositories),
    user_id: str = Depends(hole_benutzer_id),
    sprache: str = Depends(hole_sprache),
) -> OrdnerStand:
    """Which of this chat's shared folders are no longer there.

    Asked once, when the chat is opened. It looks and nothing else: no tool
    runs, nothing is removed from the list, nothing is searched for on the
    disk. The folder stays shared until the user says where it went — the
    window is where that is said.
    """
    chat = _chat_oder_404(repositories, chat_id, user_id, sprache)
    return OrdnerStand(fehlend=ordnerstand.fehlende(list(chat.working_dirs or [])))


@router.patch("/{chat_id}", response_model=ChatAntwort, summary="Update a chat")
def chat_aendern(
    chat_id: str,
    daten: ChatAendern,
    repositories: Repositories = Depends(hole_repositories),
    config: Config = Depends(hole_config),
    user_id: str = Depends(hole_benutzer_id),
    sprache: str = Depends(hole_sprache),
    generierungen: Generierungsverwaltung = Depends(hole_generierungen),
) -> ChatAntwort:
    vorher = _chat_oder_404(repositories, chat_id, user_id, sprache)
    felder = daten.model_dump(exclude_unset=True)
    # Travels beside the list, not inside it: which missing folder was
    # re-chosen and where it lies now. Taken out before the update, the way
    # pinning is, because no column of that name exists.
    ersatz = felder.pop("ordner_ersatz", None)

    # Where the chat lies once this change is done: a chat in a project works
    # in the project's folders, so a list sent along belongs to that project
    # — the whole new list of it — and not to one the chat may be leaving. A
    # project that is not this user's, or lies in the archive, takes no chat.
    # `known_folders` are the ones already shared where the chat ends up:
    # leaving a project, it keeps that project's folders as its own.
    project_now = vorher.project_id
    known_folders = vorher.working_dirs or []
    target = felder.pop("project_id", vorher.project_id)
    if target != vorher.project_id:
        if target:
            project = repositories.projects.get(target, user_id=user_id)
            if project is None or project.archived:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=t("fehler.project_not_found", sprache),
                )
            known_folders = project.working_dirs
        project_now = target or None

    # The working folders are checked BEFORE saving: only absolute paths to
    # existing folders, resolved. The rule lives in one module
    # (app/arbeitsordnerpruefung.py) so the chat and the job start window
    # cannot drift apart on it — and here, not just in the frontend, because it
    # belongs where it cannot be bypassed. An empty list deselects.
    if felder.get("working_dirs") is not None:
        # What this chat already shares is handed in so it is not looked for
        # on disk a second time. A folder that has been MOVED AWAY stays in
        # the list until the user decides about it, and without this every
        # other change to the list would fail on it — including re-choosing
        # the second missing folder while the first one still waits.
        # Checked, and a folder new to this chat gets its exe.md — the one
        # step every share takes, which the tool `create_folder` goes through
        # as well (app/arbeitsordnerpruefung.py, `share`).
        felder["working_dirs"] = arbeitsordnerpruefung.share(
            felder["working_dirs"], sprache, known=known_folders, data_dir=config.datenverzeichnis
        )

    # Into a project, or out of it — after the folders passed their check,
    # so a refused list leaves the chat where it was. Both move folders
    # between the chat and the project, so they run on their own
    # (ProjectRepository).
    if project_now != vorher.project_id:
        if project_now:
            repositories.projects.add_chat(project_now, chat_id)
        else:
            repositories.projects.remove_chat(chat_id)
    if (archived := felder.pop("archived", None)) is not None:
        repositories.chats.set_archived(chat_id, archived)

    # A chat in a project works in the project's folders: the change is the
    # project's, and every chat in it sees it.
    if project_now and felder.get("working_dirs") is not None:
        repositories.projects.update(project_now, working_dirs=felder.pop("working_dirs"))

    # Pinning runs separately because it must not change 'last used'.
    if (angeheftet := felder.pop("pinned", None)) is not None:
        repositories.chats.anheften(chat_id, angeheftet)

    # A rename or a pin must not read the ring dark for a chat that is
    # actually running — the response here replaces the sidebar's own entry
    # for it directly (frontend/src/lib/zustand.svelte.js), no round trip
    # through the list.
    laeuft = generierungen.fuer_chat(chat_id) is not None
    antwort = (
        ChatAntwort.aus(repositories.chats.aktualisieren(chat_id, **felder), laeuft=laeuft)
        if felder
        else ChatAntwort.aus(repositories.chats.holen(chat_id), laeuft=laeuft)
    )

    # A folder was not added but RE-CHOSEN: the documents that lay in it are
    # told where it went, in one go. Which folder is never the client's free
    # choice — the same boundary the route that shows a folder draws
    # (app/api/v1/arbeitsordner.py): the old path has to be one this chat
    # really shared and has to be gone from the new list, the new one has to
    # be in it. Anything else rewrites nothing and says nothing, because a
    # pair that does not describe what just happened is not an instruction.
    if ersatz:
        alter_pfad = ersatz["alt"]
        neuer_pfad = str(Path(ersatz["neu"]).expanduser().resolve())
        if (
            alter_pfad in (vorher.working_dirs or [])
            and alter_pfad not in antwort.working_dirs
            and neuer_pfad in antwort.working_dirs
        ):
            # In a project the folder was every chat's, so every chat's
            # documents and history move along.
            affected = repositories.projects.chat_ids(project_now) if project_now else [chat_id]
            moved = 0
            for affected_chat in affected:
                moved += repositories.documents.pfade_umziehen(
                    chat_id=affected_chat, alt=alter_pfad, neu=neuer_pfad
                )
                # The model's own history still names the old path — read_file
                # calls made from it would otherwise run into a refusal instead
                # of an answer (app/api/v1/generierung.py, `_ordner_umzug_satz`).
                ordner_umzug_melden(affected_chat, alter_pfad, neuer_pfad)
            log.info("Folder re-chosen: %d document path(s) moved along", moved)

    return antwort


def _document_plan(repositories: Repositories, chat_id: str, zeilen: list, fenster: int):
    """What each document of the chat would travel with, read from the rows
    alone.

    The same share-out an answer works out for its own request, minus what
    only an answer knows — the system text, the tool offer and a ceiling the
    user set: a hand-made fold has no request of its own to measure against.
    ``None`` where the chat has no documents.
    """
    if not repositories.documents.anzahl(chat_id=chat_id):
        return None
    kennungen: list[str] = []
    for zeile in reversed(zeilen):
        for kennung in reversed(zeile.dokument_ids()):
            if kennung not in kennungen:
                kennungen.append(kennung)
    dokumente = [
        d
        for d in (dokumentcache.holen(repositories, k) for k in kennungen)
        if d is not None and d.extracted_text
    ]
    belegt = sum(
        tokenmass.tokens(zeilentext(z, repositories, volltext_mitschicken=False))
        + werkzeuggewicht(z) // tokenmass.ZEICHEN_JE_TOKEN_ROH
        for z in zeilen
    )
    return dokumentbudget.verteilen(
        dokumente, dokumentbudget.budget_tokens(fenster, None, belegt)
    )


@router.post(
    "/{chat_id}/compact",
    response_model=ChatCompactResult,
    summary="Compact a chat by hand",
)
async def compact_chat(
    chat_id: str,
    daten: ChatCompact,
    repositories: Repositories = Depends(hole_repositories),
    discovery: Discovery = Depends(hole_discovery),
    generierungen: Generierungsverwaltung = Depends(hole_generierungen),
    user_id: str = Depends(hole_benutzer_id),
    sprache: str = Depends(hole_sprache),
    config: Config = Depends(hole_config),
) -> ChatCompactResult:
    """Folds the middle of a chat once, now.

    No threshold and no brake: the user asked, so a chat under its threshold
    folds too, and so does a middle an earlier try found too thin to be
    worth a summary. The pause a failed fold left behind is lifted first —
    after the user asked, the model gets asked — and a success clears the
    run of failures as any success does, so the automatic fold works again
    from here.

    The chat is claimed the way an answer claims it: a fold rewrites the
    history, and an answer being written into it at the same time would be
    built from rows that are folded under it. That claim is also what the
    stop button reaches by the chat's id: a stop while the summary is being
    written closes the request and answers ``stopped``.
    """
    chat = _chat_oder_404(repositories, chat_id, user_id, sprache)
    endpoint_id = daten.endpoint_id or chat.endpoint_id
    if not endpoint_id:
        raise HTTPException(400, t("fehler.kein_modell_verfuegbar", sprache))
    gefunden = discovery.aufloesen(endpoint_id)
    if gefunden is None:
        raise HTTPException(
            404, t("fehler.modell_nicht_erreichbar", sprache, name=endpoint_id)
        )
    zustand, modellname = gefunden
    if not zustand.erreichbar:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            t("fehler.modell_nicht_erreichbar", sprache, name=zustand.endpunkt.name),
        )
    if not generierungen.reservieren(chat.id):
        raise HTTPException(
            status.HTTP_409_CONFLICT, t("fehler.antwort_laeuft_schon", sprache)
        )
    try:
        with dokumentcache.aktiv():
            zeilen = repositories.messages.fuer_das_modell(chat_id=chat.id)
            schwelle = verdichtungswahl.schwelle(
                repositories, modell=endpoint_id, chat=chat.id
            )
            faltpause.freigeben(chat.id)
            kennung, ergebnis = await chatverdichtung.erzwungen_verdichten(
                zustand=zustand,
                repositories=repositories,
                chat=chat,
                endpoint_id=endpoint_id,
                modellname=modellname,
                zeilen=zeilen,
                budget=verdichtung.schwanz_budget(zustand.context_tokens, schwelle),
                dokumentplan=_document_plan(
                    repositories, chat.id, zeilen, zustand.context_tokens or 0
                ),
                topic=(daten.topic or "").strip() or None,
                # The claim above carries the stop button's signal: pressed
                # while the summary is being written, the request is closed,
                # nothing is folded and nothing is booked.
                stopp=generierungen.anspruch(chat.id),
                config=config,
            )
            if ergebnis.gestoppt:
                return ChatCompactResult(result="stopped")
            if kennung is None:
                if ergebnis.keine_mitte:
                    word = "too_short"
                elif ergebnis.ohne_ersparnis:
                    word = "no_saving"
                else:
                    word = "failed"
                return ChatCompactResult(result=word)
        # The fold is where what the model wrote meanwhile comes into the
        # system message: the next send builds it anew.
        forget_system_message(chat.id)
        return ChatCompactResult(result="folded", replaced=ergebnis.ersetzt)
    finally:
        generierungen.freigeben(chat.id)


@router.delete(
    "/{chat_id}",
    status_code=204,
    response_class=Response,
    response_model=None,
    summary="Delete a chat",
)
async def chat_loeschen(
    chat_id: str,
    repositories: Repositories = Depends(hole_repositories),
    generierungen: Generierungsverwaltung = Depends(hole_generierungen),
    user_id: str = Depends(hole_benutzer_id),
    sprache: str = Depends(hole_sprache),
    config: Config = Depends(hole_config),
) -> None:
    _chat_oder_404(repositories, chat_id, user_id, sprache)
    await remove_chat(
        chat_id,
        repositories=repositories,
        generierungen=generierungen,
        user_id=user_id,
        config=config,
        sprache=sprache,
    )


async def remove_chat(
    chat_id: str,
    *,
    repositories: Repositories,
    generierungen: Generierungsverwaltung,
    user_id: str,
    config: Config,
    sprache: str,
) -> None:
    """Deletes one chat for good, with everything that hangs off it.

    The chat's own route and a project deleted from the archive both end a
    chat through here, so a chat never goes in two different ways.

    The chat is deleted only once its run has ended: a run that is still
    writing would meet a chat that is gone. A run that does not end in time
    leaves the chat where it is and the answer is a 409.
    """
    # The answer being written here, if there is one, is stopped before the
    # row goes.
    #
    # Neither kind ends on its own here: a user-asked
    # answer is unbound from its request the same way a WOKEN answer
    # (app/hintergrundwecken.py) always was — that is what lets both survive
    # a window closing. Deleting a chat means the window that held it is
    # gone, but the run itself does not notice: it would go on writing into
    # a chat that no longer exists, go on running tools in the shared
    # folder, and could not even be reached to be stopped, since the button
    # that would have sent its chat_id went out of the sidebar with the
    # chat. It ends only here.
    #
    # The same signal the stop route sends, not a cancellation. The run
    # reads it at its next chunk and finishes itself the way the stop button
    # finishes it — nothing is torn out from under a tool that is mid-run.
    generierungen.alle_im_chat_abbrechen(chat_id)
    # Its end is waited for before the row goes: the run writes its closing
    # rows into the chat and deregisters after that, and a chat that is
    # already gone fails that write and leaves the run registered for good.
    # A run that does not end in time keeps the chat — nothing below has
    # happened yet, so the same delete can simply be pressed again.
    if not await generierungen.wait_for_chat_runs(chat_id):
        raise HTTPException(
            status.HTTP_409_CONFLICT, t("fehler.chat_loeschen_lauf_laeuft", sprache)
        )
    # And the agents it started, with every run under them: nobody could
    # reach them any more to stop them, and their report would come back to
    # a chat that is gone. Imported here: the jobs module imports the chat
    # run, which this module sits beside.
    from app.api.v1.auftraege import stop_jobs_of_chat

    stop_jobs_of_chat(repositories, generierungen, chat_id)
    # The data folder travels in because the repository has no config of
    # its own: it is what tells the delete where this chat's own document
    # folder lies, so the files go with the row instead of outliving it.
    # The pictures its rows name and its picture studio holds — a start, end
    # or reference picture, a guide picture, a mask: one laid into the
    # studio is named by no row. Read while rows and studio are still there.
    bilder = list(dict.fromkeys([
        *repositories.messages.bilder_von(chat_id=chat_id),
        *sorted(bildfensterwahl.held_pictures(
            repositories.einstellungen.holen(chat_bereich(chat_id), bildfensterwahl.SCHLUESSEL)
        )),
    ]))
    geloescht = repositories.chats.loeschen(
        chat_id, user_id=user_id, datenverzeichnis=config.datenverzeichnis
    )
    # They go with it from the picture folder — but one that a row of
    # another chat still names stays: a picture lies there once and belongs
    # to every chat that names it. So does one another chat's picture
    # studio holds in any of those places: no row names it there, and the
    # studio would open on an empty picture. A copy saved elsewhere is
    # never touched.
    if geloescht and bilder:
        bleiben = repositories.messages.noch_genannt(bilder)
        bleiben |= repositories.einstellungen.named_by_other_chats(
            bilder, key=bildfensterwahl.SCHLUESSEL,
            named_in=bildfensterwahl.held_pictures, except_chat=chat_id,
        )
        bilder_entfernen(bilder_verzeichnis(config), [name for name in bilder if name not in bleiben])
    # What the database holds goes with the row (foreign keys, cascade).
    # What lives in memory has to be told: this chat's little run history —
    # its commands, its drawing jobs, the events they reported, and
    # everything hung off
    # `Laufverwaltung.beim_vergessen` (bildlauf's dial list). This is the
    # only place a chat actually dies, so without the call here that record
    # is kept for the life of the process for a conversation nobody can
    # open any more.
    laeufe.vergessen(chat_id)
    ordner_umzug_vergessen(chat_id)
    forget_system_message(chat_id)
    await bus.veroeffentlichen(Ereignisse.CHAT_GELOESCHT, chat_id=chat_id, user_id=user_id)


# --- Messages ------------------------------------------------------------


@router.get(
    "/{chat_id}/messages",
    response_model=NachrichtenSeite,
    summary="Chat messages",
)
def nachrichten_auflisten(
    chat_id: str,
    antwort: Response,
    limit: int = Query(default=500, ge=1, le=2000),
    offset: int = Query(default=0, ge=0),
    neueste: bool = Query(default=False),
    repositories: Repositories = Depends(hole_repositories),
    user_id: str = Depends(hole_benutzer_id),
    sprache: str = Depends(hole_sprache),
    generierungen: Generierungsverwaltung = Depends(hole_generierungen),
) -> NachrichtenSeite:
    """One page of a chat, oldest first.

    ``neueste`` says which END the page is counted from. It is off by
    default, so a caller that asks for nothing keeps getting exactly what it
    got before; the window asks for the newest page, because that is the end
    a conversation is read at. Past its five hundredth row a chat used to
    hand the window its BEGINNING and drop its end, which is the shape of
    the defect: the messages that had just been typed were the missing ones.
    """
    chat = _chat_oder_404(repositories, chat_id, user_id, sprache)
    nachrichten = repositories.messages.auflisten(
        chat_id=chat_id, limit=limit, offset=offset, neueste=neueste
    )

    # How long the chat actually is, beside the page that was served. There
    # is no honest way for a caller to work this out from the page alone —
    # a full page and an exactly-full chat look identical — and a truncation
    # nobody can see is a truncation nobody fixes. In a header rather than in
    # the body because `NachrichtenSeite` is the shape of a MESSAGE LIST, and
    # how much of the chat that list is, is not a message.
    #
    # Counted only when the page came back full: a page with room left in
    # it IS the end of the chat, so the length is the offset plus what was
    # served, and the count is a second query every ordinary chat open paid
    # for a number nobody read. Only a full page leaves the question open.
    if len(nachrichten) < limit:
        gesamt = offset + len(nachrichten)
    else:
        gesamt = repositories.messages.anzahl(chat_id=chat_id)
    antwort.headers["X-Nachrichten-Gesamt"] = str(gesamt)

    # The server already knows whether this chat has a run going — a window
    # opening the chat cold (a reload, a fresh tab) has no other way to find
    # out. A cold reattach always replays from the first event, so there is
    # no offset to hand over (see LaufendeGenerierung's own docstring).
    laufende = generierungen.fuer_chat(chat_id)
    laufend = (
        LaufendeGenerierung(generation_id=laufende.id, message_id=laufende.message_id)
        if laufende
        else None
    )
    # Held but not running yet: the request that claims this chat is still
    # folding its history and has no run to name (app/generationen.py,
    # `beansprucht`). A window that asks here — one whose own send broke in
    # that stretch — learns that something IS coming and waits, instead of
    # calling the send failed. With a run named, `laufend` already says it.
    gehalten = laufende is None and generierungen.beansprucht(chat_id)
    # The open ask_user question, delivered whether or not a run is still
    # going for this chat right now — the same reasoning `frage` gets its
    # own column for at all: a window that left or reloaded
    # gets it back either way.
    frage = OffeneFrage(**json.loads(chat.frage)) if chat.frage else None

    # Document messages carry only the id — the server builds the meta card
    # for the window from the documents row (4.1).
    def meta_fuer(dokument_id, nachricht):
        from app.api.v1.dokumente import meta_bauen

        dokument = repositories.documents.holen(dokument_id)
        if not dokument:
            return None
        # What the latest answer carried of it — written onto this very
        # message when that answer's request was built, so the card
        # follows a model change or a regenerate.
        stand = nachricht.stats.get("dokumente")
        getragen = stand.get(dokument.id) if isinstance(stand, dict) else None
        return meta_bauen(dokument, getragen=getragen).model_dump()

    def meta(nachricht):
        if not nachricht.dokument:
            return None
        return meta_fuer(nachricht.dokument, nachricht)

    def metas(nachricht):
        """The cards for the LIST of documents — several on one message."""
        ids = nachricht.dokument_ids()
        if len(ids) < 2:
            return None
        karten = [meta_fuer(dokument_id, nachricht) for dokument_id in ids]
        return [karte for karte in karten if karte] or None

    return NachrichtenSeite(
        nachrichten=[
            NachrichtAntwort.aus(nachricht, meta(nachricht), metas(nachricht))
            for nachricht in nachrichten
        ],
        laufend=laufend,
        gehalten=gehalten,
        frage=frage,
    )


@router.post(
    "/{chat_id}/messages",
    response_model=NachrichtAntwort,
    status_code=201,
    summary="Save a message",
)
async def nachricht_speichern(
    chat_id: str,
    daten: NachrichtAnlegen,
    repositories: Repositories = Depends(hole_repositories),
    user_id: str = Depends(hole_benutzer_id),
    sprache: str = Depends(hole_sprache),
) -> NachrichtAntwort:
    _chat_oder_404(repositories, chat_id, user_id, sprache)
    stats = daten.stats
    if stats and any(schluessel in stats for schluessel in DIENSTSCHLUESSEL):
        stats = {
            schluessel: wert
            for schluessel, wert in stats.items()
            if schluessel not in DIENSTSCHLUESSEL
        }
    nachricht = repositories.messages.speichern(
        chat_id=chat_id,
        role=daten.role,
        content=daten.content,
        reasoning=daten.reasoning,
        stats=stats,
    )
    repositories.chats.zeitstempel_auffrischen(chat_id)
    await bus.veroeffentlichen(
        Ereignisse.NACHRICHT_GESPEICHERT, chat_id=chat_id, message_id=nachricht.id
    )
    return NachrichtAntwort.aus(nachricht)


@router.delete(
    "/{chat_id}/messages/{message_id}/anhang",
    response_model=NachrichtAntwort,
    summary="Remove an attachment from a message",
)
def anhang_entfernen(
    chat_id: str,
    message_id: str,
    bild: str | None = Query(default=None),
    dokument: str | None = Query(default=None),
    repositories: Repositories = Depends(hole_repositories),
    user_id: str = Depends(hole_benutzer_id),
    sprache: str = Depends(hole_sprache),
    config: Config = Depends(hole_config),
) -> NachrichtAntwort:
    """The ✕ on a chat attachment: this one image or document leaves the
    message — and with it the model's context, which is rebuilt from the
    stored rows on every request.

    A removed document's row is deleted with it: its extracted text existed
    only to travel with this message. The image FILE stays on disk — it is
    the user's upload, and removal here is about the chat, not the disk. So
    does a document file in a folder the user shared. Only the copy the
    program itself wrote, in the chat's own folder, goes with the row: the
    path it carried is the only thing that could name it.
    """
    _chat_oder_404(repositories, chat_id, user_id, sprache)
    nachricht = repositories.messages.holen(message_id)
    if nachricht is None or nachricht.chat_id != chat_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=t("fehler.nachricht_nicht_gefunden", sprache),
        )
    if bild is None and dokument is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=t("fehler.anhang_fehlt", sprache),
        )
    if bild is not None and bild not in nachricht.anhang_bilder():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=t("fehler.anhang_fehlt", sprache),
        )
    if dokument is not None and dokument not in nachricht.dokument_ids():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=t("fehler.anhang_fehlt", sprache),
        )
    neu = repositories.messages.anhang_entfernen(
        message_id, bild=bild, dokument=dokument
    )
    if dokument is not None:
        repositories.documents.loeschen(
            dokument, datenverzeichnis=config.datenverzeichnis
        )
    return NachrichtAntwort.aus(neu)


@router.delete(
    "/{chat_id}/messages/{message_id}",
    status_code=204,
    response_class=Response,
    response_model=None,
    summary="Delete a message",
)
def nachricht_loeschen(
    chat_id: str,
    message_id: str,
    repositories: Repositories = Depends(hole_repositories),
    user_id: str = Depends(hole_benutzer_id),
    sprache: str = Depends(hole_sprache),
) -> None:
    _chat_oder_404(repositories, chat_id, user_id, sprache)
    nachricht = repositories.messages.holen(message_id)
    if nachricht is None or nachricht.chat_id != chat_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=t("fehler.nachricht_nicht_gefunden", sprache),
        )
    repositories.messages.loeschen(message_id)
