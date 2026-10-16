"""Cron entries, seen and switched from the settings window.

Creating goes through the cronjob tool as well (app/tools/cronjob.py) — this
router hands it the mask's fields and nothing more. Not a second creation
path: every rule that guards an entry lives in that module, from the
invisible-character scrub on the task text to the folder a script may come
out of, and a route writing rows of its own would be a door beside all of
them. The mask counts as a chat here, and rightly: a person is looking at
the form while it is filled in.

Editing an existing entry stays where it was — this router shows what exists
and flips the on/off switch, the same split notizen.py draws between the pad
and its own storage.
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from itertools import islice

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field

from app import (
    agentenname,
    cronablauf,
    helper,
    no_agent,
    reminder,
    schedule_calendar,
    skriptlauf,
    sprachwahl,
    terminplan,
    wecker,
)
from app.agenten import agent_lookup, agenten_laden
from app.api.abhaengigkeiten import (
    Repositories,
    hole_benutzer_id,
    hole_repositories,
    hole_sprache,
)
from app.api.v1.auftraege import auftrag_anstossen
from app.api.v1.generierung import hole_discovery, hole_generierungen
from app.discovery import Discovery
from app.generationen import Generierungsverwaltung
from app.i18n import t
from app.speicherorte import ort
from app.tools import cronjob as cronjob_werkzeug
from app.db.models import Auftrag, Cronjob
from app.db.repositories.auftraege import CRONJOB_AUSGAENGE

log = logging.getLogger(__name__)

router = APIRouter(prefix="/cronjobs", tags=["cronjobs"])


def _agent_folders(request: Request):
    """The folders agent files are read from, shipped first, the user's last."""
    return request.app.state.config.agentenverzeichnisse


def _agent_state(
    entry: Cronjob, folders, directory=None
) -> tuple[bool, bool, int | None]:
    """Whether the agent this entry names stops it from starting: ``(missing,
    broken, line)`` — no file under that name, or a file that cannot be read,
    with the line of the file the reader names where it names one. The row
    says it in one short sentence; the reader's own message, three lines of
    it, is not for a row.

    Only an entry that is switched on has a live state (``CronjobAntwort.aus``),
    and only an agent entry names a file: a marker (script, reminder, no
    agent) and the helper name none. The name is looked up the way the tick
    looks an agent up — capitals do not count — and an entry alone reads only
    its own agent's file. ``directory`` is the agents a list has read once;
    an entry it holds needs no further look."""
    if not entry.aktiv:
        return False, False, None
    if reminder.kind_of(entry.agent, entry.skript) != reminder.KIND_AGENT:
        return False, False, None
    if helper.is_helper(entry.agent) or no_agent.is_no_agent(entry.agent):
        return False, False, None
    if directory is not None and entry.agent in directory:
        return False, False, None
    agent, broken = agent_lookup(entry.agent, *folders)
    if agent is not None:
        return False, False, None
    if broken is not None:
        return False, True, broken.line
    return True, False, None


def _jetzt(request: Request) -> datetime:
    """Now, on the clock the tick reads the cron table by (app/wecker.py).

    Taken once per request and handed down, so every row of one answer names
    its next due time against the same moment.
    """
    return wecker.jetzt_in_zone(request.app.state.config.app.timezone)


class CronjobAntwort(BaseModel):
    id: str
    agent: str
    task: str
    zeitplan: str
    deliver: str
    aktiv: bool
    herkunft: str
    created_at: str
    updated_at: str
    zuletzt_ausgeloest: str | None = None
    letzter_ausgang: str | None = None
    # Failed runs in a row and the limit that stops the entry.
    # Both, not just the count: an entry standing at 2 says nothing on its
    # own — the mask can only tell "switched off by hand" from "gave up"
    # by holding the two numbers next to each other.
    fehlversuche: int = 0
    fehlergrenze: int = 5
    # The goal and its two answers. All three, for the same reason
    # the two failure numbers travel together: an entry that is off with a
    # goal reached is "finished", one that is off with a goal it never
    # reached was switched off by hand, and only holding the goal, the
    # stamp and the stop-on-reached flag next to each other tells them
    # apart.
    ziel: str | None = None
    ziel_stilllegen: bool = False
    ziel_erreicht_am: str | None = None
    # Runs in a row that ended without reporting the goal. The raw
    # count, travelling beside ``fehlergrenze`` for the same reason
    # ``fehlversuche`` does: the number alone says nothing, and the mask can
    # only say "quiet for a while" by holding the two next to each other.
    # Silence is not failure — nothing is switched off over this — but an
    # entry watching for something it has not mentioned in a dozen runs is
    # the one thing the list never said out loud.
    laeufe_ohne_ruf: int = 0
    # A due time this entry cannot run because no model is answering.
    # Not a failure and not a pause — nothing was attempted. Read from the
    # flow's own memory rather than from a column: it is a fact about this
    # minute, and a stored one would survive the restart that fixed it.
    #
    # Only ever set for an entry that is switched on — see ``aus`` below.
    wartet_auf_modell: bool = False
    # The script this entry runs instead of an agent, None for
    # every other entry. The mask shows the file name where it otherwise
    # shows agent and task — a script entry has neither, and the marker in
    # its ``agent`` column is bookkeeping, not something to put in front of
    # a person.
    skript: str | None = None
    # Why this entry's script cannot be started right now, None when nothing
    # is wrong. The sentence rather than a flag: "there is
    # no script 'sicherung.sh' in <folder>" and "'sicherung.sh' is not
    # executable" are two different things to go and do, and an entry that
    # only said "cannot start" would send the user looking for which. Read
    # from the flow's own memory for the same reason ``wartet_auf_modell``
    # is: it is a fact about this minute, and a stored one would survive the
    # restart — or the file put back — that fixed it.
    #
    # Only ever set for an entry that is switched on — see ``aus`` below.
    skript_nicht_startbar: str | None = None
    # Whether the agent file this entry names is gone — the agent entry's
    # version of a script that cannot be started. Read off the folder when
    # the row is built, so it shows the moment the file is deleted, not
    # only once a due time has come and gone.
    #
    # Only ever set for an entry that is switched on — see ``aus`` below.
    agent_missing: bool = False
    # The file is there and cannot be read. "Missing" would send the person
    # looking for a file that stands in the folder. The line is the one the
    # reader names, so the row can say where to look without the reader's
    # own message; ``None`` where it names none.
    agent_broken: bool = False
    agent_broken_line: int | None = None
    # When this entry comes due next, ``None`` for one that never does again
    # (``cronablauf.naechste_faelligkeit``). The list showed what an entry
    # runs, how it is doing and when it last fired, and the one question a
    # standing schedule is actually kept for — when is it next — had to be
    # worked out from the expression by hand.
    naechste_faelligkeit: str | None = None
    # Agent, script or reminder (app/schedule_calendar.py), so the mask
    # reads the kind rather than the marker in ``agent``. With the one-off
    # flag and its day, it is what the form opens a card with.
    kind: str = reminder.KIND_AGENT
    einmalig: bool = False
    datum: str | None = None

    @classmethod
    def aus(
        cls,
        eintrag: Cronjob,
        *,
        letzter_ausgang: str | None = None,
        jetzt: datetime,
        sprache: str | None = None,
        agent_folders=(),
        agenten=None,
    ) -> "CronjobAntwort":
        # Both live states belong to an entry that is switched ON, and to no
        # other. They answer "why is this entry not running right now", and
        # for a paused entry the answer is that somebody switched it off —
        # not that a model is missing or a file is gone.
        #
        # They are kept in the flow's own memory, and that memory is only
        # ever cleared by a run that starts. A paused entry never starts, so
        # whatever the last due tick before the pause wrote stays there for
        # good: an entry switched off weeks ago still showed a red "cannot
        # start" naming a file that had long since been put back. The tick
        # loop skips a paused entry, so nothing refreshes the sentence
        # either — it is not stale by a minute, it is stale for ever.
        #
        # Read here rather than cleared on pause: an entry goes quiet along
        # half a dozen roads (the mask's switch, the cronjob tool, a one-off
        # that fired, a goal reached, a chain that ended), and a rule hung on
        # each of them is six chances to forget one. The question "is this
        # entry on?" has exactly one answer, and it is in hand right here.
        laeuft = eintrag.aktiv
        faellig = cronablauf.naechste_faelligkeit(eintrag, jetzt)
        agent_missing, agent_broken, agent_broken_line = _agent_state(
            eintrag, agent_folders, agenten
        )
        return cls(
            id=eintrag.id,
            agent=eintrag.agent,
            task=eintrag.task,
            zeitplan=eintrag.zeitplan,
            deliver=eintrag.deliver,
            aktiv=eintrag.aktiv,
            herkunft=eintrag.herkunft,
            created_at=eintrag.created_at,
            updated_at=eintrag.updated_at,
            zuletzt_ausgeloest=eintrag.zuletzt_ausgeloest,
            letzter_ausgang=letzter_ausgang,
            fehlversuche=eintrag.fehlversuche,
            fehlergrenze=eintrag.fehlergrenze,
            ziel=eintrag.ziel,
            ziel_stilllegen=eintrag.ziel_stilllegen,
            ziel_erreicht_am=eintrag.ziel_erreicht_am,
            laeufe_ohne_ruf=eintrag.laeufe_ohne_ruf,
            wartet_auf_modell=laeuft and cronablauf.wartet_auf_modell(eintrag.id),
            skript=eintrag.skript,
            skript_nicht_startbar=(
                cronablauf.skript_nicht_startbar(eintrag.id, sprache) if laeuft else None
            ),
            agent_missing=agent_missing,
            agent_broken=agent_broken,
            agent_broken_line=agent_broken_line,
            naechste_faelligkeit=faellig.isoformat() if faellig else None,
            kind=reminder.kind_of(eintrag.agent, eintrag.skript),
            einmalig=eintrag.einmalig,
            datum=eintrag.datum,
        )


class HandStartResponse(CronjobAntwort):
    """The answer to a start by hand: the entry, and what to tell the person
    pressing the button where the run does not begin this second."""

    # The sentence, in the language of the request, where the model was still
    # coming up and the run follows by itself; ``None`` where the run started.
    notice: str | None = None


class CronjobLaufAntwort(BaseModel):
    # The run's own id. A history row is a row of a list like any other in
    # the house, and a list that cannot be cleared is one that only grows —
    # so the row has to be able to name what it deletes. It is the job's id,
    # and it is deleted through the job route: a scheduled run IS a job, and
    # a second way to delete one would be a second set of rules about
    # stopping a run that is still going.
    id: str = ""
    wann: str
    status: str
    task: str
    grund: str | None = None
    # Which schedule fired it, and what that schedule was called. Both travel
    # with the run so the history can stand on its own — a run whose entry has
    # since been deleted still says when it ran and what it did, and only the
    # name is missing. Empty for a listing that already knows its entry.
    cronjob_id: str | None = None
    agent: str | None = None
    skript: str | None = None
    # Agent, script or reminder, so a reminder's run is not shown by the
    # marker its agent column carries.
    kind: str = reminder.KIND_AGENT
    # How many ended runs this run's schedule has altogether — the answer
    # carries at most five of them per schedule, and the page's counter
    # reads "shown/total" off this number.
    total: int = 0

    @classmethod
    def aus(cls, lauf: Auftrag, eintrag=None, total: int = 0) -> "CronjobLaufAntwort":
        status = CRONJOB_AUSGAENGE[lauf.zustand]
        return cls(
            id=lauf.id,
            total=total,
            wann=lauf.created_at,
            status=status,
            task=lauf.auftrag,
            grund=lauf.ende_grund if status == "gescheitert" else None,
            cronjob_id=lauf.cronjob_id,
            agent=(eintrag.agent if eintrag else None) or lauf.agent,
            skript=eintrag.skript if eintrag else None,
            kind=reminder.kind_of(lauf.agent, eintrag.skript if eintrag else None),
        )


class CronjobAnlegen(BaseModel):
    """What the mask can say. Everything else the tool decides for itself."""

    # 'HH:MM', a cron expression, or an exact moment — the tool knows all
    # three and says which it read back in its answer, so the mask needs no
    # second opinion about time.
    zeitplan: str = Field(min_length=1)
    task: str = ""
    agent: str | None = None
    skript: str | None = None
    einmalig: bool = False
    datum: str | None = None
    notify: bool = False
    ziel: str | None = None
    # The third kind (app/reminder.py): ``task`` is the notification's text,
    # and nothing runs.
    reminder: bool = False


class CronjobChange(BaseModel):
    """What the mask changes on an existing entry — only the fields it
    sends; one left out stays as it is."""

    zeitplan: str | None = None
    task: str | None = None
    agent: str | None = None
    skript: str | None = None
    einmalig: bool | None = None
    datum: str | None = None


async def _through_tool(
    arguments: dict, request: Request, repositories: Repositories, language: str
) -> None:
    """Hands the mask's fields to the cronjob tool — the same door a chat
    goes through, with every rule that guards an entry in front of it — and
    answers a refusal in the reader's language."""
    config = request.app.state.config
    try:
        await cronjob_werkzeug.ausfuehren(
            arguments,
            repositories.cronjobs,
            config.agentenverzeichnisse,
            herkunft="chat",
            agent=None,
            zeitzone=config.app.timezone,
            skripte_ordner=lambda: ort(config, "scripts"),
        )
    except cronjob_werkzeug.CronjobVerboten as refusal:
        # Every refusal the mask can cause carries its catalogue key
        # (app/tools/cronjob.py). One without a key — none the mask can
        # reach — is passed through as the tool wrote it.
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            t(refusal.schluessel, language, **refusal.werte)
            if refusal.schluessel
            else str(refusal),
        ) from None


@router.post(
    "", response_model=CronjobAntwort, status_code=201, summary="Create a schedule"
)
async def anlegen(
    daten: CronjobAnlegen,
    request: Request,
    repositories: Repositories = Depends(hole_repositories),
    sprache: str = Depends(hole_sprache),
) -> CronjobAntwort:
    """One entry, through the tool's own door.

    ``herkunft="chat"`` because that is what this is: a person filling in a
    form and pressing the button. It is also what lets a script entry be made
    here at all — the rule the tool states is that a person has to have seen
    which file it is, and in a mask they have.
    """
    argumente: dict[str, object] = {
        "action": "create",
        "time": daten.zeitplan,
        "once": daten.einmalig,
        "notify": daten.notify,
    }
    # Left out rather than sent empty: the tool reads "not given" and "given
    # as nothing" as two different answers, and the mask has no third one.
    for schluessel, wert in (
        ("task", daten.task),
        ("agent", daten.agent),
        ("script", daten.skript),
        ("date", daten.datum),
        ("goal", daten.ziel),
    ):
        if wert:
            argumente[schluessel] = wert
    if daten.reminder:
        argumente["reminder"] = True

    await _through_tool(argumente, request, repositories, sprache)

    # The tool answers in prose; the mask wants the row. The newest entry is
    # the one just made — nothing else writes this table while the request is
    # in flight.
    neueste = max(repositories.cronjobs.auflisten(), key=lambda e: e.created_at)
    return CronjobAntwort.aus(
        neueste, jetzt=_jetzt(request), sprache=sprache, agent_folders=_agent_folders(request)
    )


@router.patch("/{cronjob_id}", response_model=CronjobAntwort, summary="Update a schedule")
async def change(
    cronjob_id: str,
    fields: CronjobChange,
    request: Request,
    repositories: Repositories = Depends(hole_repositories),
    language: str = Depends(hole_sprache),
) -> CronjobAntwort:
    """Changes an entry by the tool's own ``update`` — the way a chat changes
    one — with only the fields the mask sent."""
    if repositories.cronjobs.holen(cronjob_id) is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, t("fehler.cronjob_not_found", language)
        )
    arguments: dict[str, object] = {"action": "update", "id": cronjob_id}
    for key, value in (
        ("time", fields.zeitplan),
        ("task", fields.task),
        # The form sends "no agent" as an empty word; the tool takes the
        # marker, so nothing else can be mistaken for the wish.
        ("agent", no_agent.NAME if fields.agent == "" else fields.agent),
        ("script", fields.skript),
        ("once", fields.einmalig),
        ("date", fields.datum),
    ):
        if value is not None:
            arguments[key] = value
    await _through_tool(arguments, request, repositories, language)
    entry = repositories.cronjobs.holen(cronjob_id)
    if entry is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, t("fehler.cronjob_not_found", language)
        )
    outcomes = repositories.auftraege.letzte_auslaeufe()
    return CronjobAntwort.aus(
        entry,
        agent_folders=_agent_folders(request),
        letzter_ausgang=outcomes.get(cronjob_id),
        jetzt=_jetzt(request),
        sprache=language,
    )


class CalendarRow(BaseModel):
    cronjob_id: str | None = None
    task: str = ""
    agent: str = ""
    skript: str | None = None
    kind: str
    aktiv: bool = False
    first: str = ""
    count: int = 0
    ran: int = 0
    planned: int = 0
    # The state of the latest run that day; empty while nothing has run.
    state: str = ""


@router.get(
    "/calendar",
    response_model=dict[str, list[CalendarRow]],
    summary="Calendar: completed and scheduled runs by day",
)
def calendar(
    first: date,
    last: date,
    request: Request,
    repositories: Repositories = Depends(hole_repositories),
) -> dict[str, list[CalendarRow]]:
    """Per day from ``first`` to ``last``: the runs the history holds for
    what has gone by, the rule for what is still to come
    (app/schedule_calendar.py)."""
    if last < first:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "last < first")
    return {
        day: [CalendarRow(**row) for row in rows]
        for day, rows in schedule_calendar.days(
            request.app.state.config, repositories, first, last
        ).items()
    }


# How many coming runs the mask names under a typed cron expression: one, the
# next. The sentence above it says what the expression means.
PREVIEW_RUNS = 1


@router.get("/preview", response_model=list[str], summary="Upcoming runs for the entered "
                                                          "schedule")
def preview(
    zeitplan: str,
    request: Request,
    language: str = Depends(hole_sprache),
) -> list[str]:
    """The next due moment of a schedule not yet stored — the line under a
    typed cron expression, and the service's word on whether it can be read
    at all. Read by the same module the tick fires by (app/terminplan.py), on
    the same clock."""
    try:
        # Counted in moments, not on the wall clock: the repeated hour of
        # the autumn day names each of its times twice.
        moments = [
            moment.isoformat()
            for moment in islice(
                terminplan.upcoming(zeitplan, _jetzt(request)), PREVIEW_RUNS
            )
        ]
    except ValueError:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, t("cronjob_refusal.time_unreadable", language)
        ) from None
    return moments


@router.get("", response_model=list[CronjobAntwort], summary="All schedules")
def liste(
    request: Request,
    repositories: Repositories = Depends(hole_repositories),
    sprache: str = Depends(hole_sprache),
) -> list[CronjobAntwort]:
    auslaeufe = repositories.auftraege.letzte_auslaeufe()
    jetzt = _jetzt(request)
    # The whole directory is read here and nowhere else: one look for the
    # list, where an entry alone asks only for its own agent's file.
    folders = _agent_folders(request)
    agenten = agenten_laden(*folders)
    return [
        CronjobAntwort.aus(
            eintrag,
            letzter_ausgang=auslaeufe.get(eintrag.id),
            jetzt=jetzt,
            sprache=sprache,
            agent_folders=folders,
            agenten=agenten,
        )
        for eintrag in repositories.cronjobs.auflisten()
    ]


@router.get(
    "/runs/all",
    response_model=list[CronjobLaufAntwort],
    summary="All runs of all schedules",
)
def alle_laeufe(
    repositories: Repositories = Depends(hole_repositories),
) -> list[CronjobLaufAntwort]:
    """The recent history in ONE answer, entries gone or not: the newest runs
    of every schedule — five each — and at most 100 together, newest first.
    Each run says how many ended runs its schedule has altogether (``total``).

    The window used to ask per entry, which cost a request each and — worse —
    lost every run whose schedule had since been deleted. The runs are the
    history; the entry only lends them a name, and a missing name is not a
    reason to hide what ran.
    """
    eintraege = {termin.id: termin for termin in repositories.cronjobs.auflisten()}
    return [
        CronjobLaufAntwort.aus(lauf, eintraege.get(lauf.cronjob_id or ""), total)
        for lauf, total in repositories.auftraege.alle_cronlaeufe()
    ]


@router.post("/{cronjob_id}/pause", response_model=CronjobAntwort, summary="Pause a schedule")
def pausieren(
    cronjob_id: str,
    request: Request,
    repositories: Repositories = Depends(hole_repositories),
    sprache: str = Depends(hole_sprache),
) -> CronjobAntwort:
    eintrag = repositories.cronjobs.aktiv_setzen(cronjob_id, False)
    if eintrag is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, t("fehler.cronjob_not_found", sprache))
    cronjob_werkzeug.announce_change(cronjob_id)
    return CronjobAntwort.aus(
        eintrag,
        agent_folders=_agent_folders(request),
        letzter_ausgang=repositories.auftraege.letzter_auslauf(eintrag.id),
        jetzt=_jetzt(request),
        sprache=sprache,
    )


@router.post("/{cronjob_id}/resume", response_model=CronjobAntwort, summary="Resume a schedule")
def fortsetzen(
    cronjob_id: str,
    request: Request,
    repositories: Repositories = Depends(hole_repositories),
    sprache: str = Depends(hole_sprache),
) -> CronjobAntwort:
    eintrag = repositories.cronjobs.aktiv_setzen(cronjob_id, True)
    if eintrag is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, t("fehler.cronjob_not_found", sprache))
    cronjob_werkzeug.announce_change(cronjob_id)
    return CronjobAntwort.aus(
        eintrag,
        agent_folders=_agent_folders(request),
        letzter_ausgang=repositories.auftraege.letzter_auslauf(eintrag.id),
        jetzt=_jetzt(request),
        sprache=sprache,
    )


@router.post(
    "/{cronjob_id}/run", response_model=HandStartResponse, summary="Run a scheduled task now"
)
async def sofort_starten(
    cronjob_id: str,
    request: Request,
    repositories: Repositories = Depends(hole_repositories),
    discovery: Discovery = Depends(hole_discovery),
    generierungen: Generierungsverwaltung = Depends(hole_generierungen),
    user_id: str = Depends(hole_benutzer_id),
) -> HandStartResponse:
    """Runs this entry now, without waiting for its next due time.

    The same run the tick would start, down to the ``cronjob_id`` on the job
    row: it shows up in the entry's history, its ending counts against the
    failure limit, and a goal it reports is the entry's goal. A run that did
    not carry the entry's id would be a second kind of run of the same
    schedule, with its own books — and the panel would keep saying the
    entry has never run.

    Three answers instead of a run, and each of them is a thing to go and
    fix rather than something to try again:

    * an entry that is switched off (409). Somebody turned it off; turning
      it back on is a different act with a different meaning, and doing it
      silently here would also clear the failure count (``aktiv_setzen``).
    * a run of this entry that is still going (409). The tick skips such a
      due time; a hand start has no due time to skip, so it says so.
    * a script that is not where it has to be (400), a missing agent file
      (404), no model answering and no server the program could bring up
      (whatever the start refuses with). The tick leaves these open and
      tries again — a person pressing a button is told instead. That is why
      the start goes through ``auftrag_anstossen`` rather than
      ``termin_ausloesen``, which turns every refusal into a silent ``None``.

    A model that is not answering YET is no refusal: the program wakes the
    server the way the tick does (``cronablauf.wake_model``), the answer
    carries the sentence that says so, and the tick starts the run once the
    model answers — once, with no second press.
    """
    # The language the tick takes for the same entry (app/wecker.py): the one
    # chosen for the interface. The request's own language does not count, or
    # one entry would speak two languages, depending on who starts it.
    config = request.app.state.config
    sprache = sprachwahl.interface_language(repositories, config.app.language) or config.app.language
    eintrag = repositories.cronjobs.holen(cronjob_id)
    if eintrag is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, t("fehler.cronjob_not_found", sprache))
    if not eintrag.aktiv:
        raise HTTPException(status.HTTP_409_CONFLICT, t("fehler.cronjob_pausiert", sprache))

    jetzt = _jetzt(request)
    notice: str | None = None
    if reminder.is_reminder(eintrag):
        # Started by hand, a reminder shows itself now — it has nothing
        # else to start.
        await cronablauf.reminder_show(request.app, eintrag, jetzt)
    elif eintrag.skript:
        if repositories.auftraege.laeuft_fuer_cronjob(eintrag.id):
            raise HTTPException(
                status.HTTP_409_CONFLICT, t("fehler.cronjob_laeuft_schon", sprache)
            )
        try:
            await cronablauf.skript_starten(request.app, eintrag, jetzt)
        except skriptlauf.SkriptVerboten as fehler:
            # The checker's own sentence — it names which of the things that
            # can be wrong with a script file is wrong. In the reader's
            # language: this one goes to a person who pressed a button, not
            # to a model, and ``str(fehler)`` is always English.
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                t(fehler.schluessel, sprache, **fehler.werte),
            ) from None
    else:
        # Asked per agent name, the same question the tick asks: two runs of
        # one agent would queue behind each other anyway.
        if cronablauf.entry_running(repositories, eintrag):
            raise HTTPException(
                status.HTTP_409_CONFLICT, t("fehler.cronjob_laeuft_schon", sprache)
            )
        agenten = agenten_laden(*request.app.state.config.agentenverzeichnisse)
        agent = helper.agent_named(
            eintrag.agent, agenten, repositories,
            getattr(request.app.state, "werkzeuge", None),
        )
        if agent is None:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND,
                t(
                    "fehler.agent_nicht_gefunden_beim_start",
                    sprache,
                    name=eintrag.agent,
                    verfuegbar=agentenname.namen_satz(agenten),
                ),
            )
        # The way the tick goes to the model: asked of the same function, so
        # a hand start and a due time can never disagree about whether there
        # is a model to run on.
        model = await cronablauf.wake_model(
            request.app, agent, hat_ziel=bool(eintrag.ziel)
        )
        if model == cronablauf.MODEL_STARTING:
            cronablauf.want_hand_start(eintrag.id)
            notice = t("cronjobs.run_now_model_starting", sprache)
            log.info(
                "Cronjob: '%s' started by hand — the model is starting, the run follows",
                eintrag.agent,
                extra={
                    "ereignis": "cronjob_hand_start_waiting",
                    "cronjob": eintrag.id,
                    "agent": eintrag.agent,
                },
            )
        else:
            auftrag_anstossen(
                config=request.app.state.config,
                repositories=repositories,
                discovery=discovery,
                generierungen=generierungen,
                registry=getattr(request.app.state, "werkzeuge", None),
                agent=agent,
                task=cronablauf.auftragstext(eintrag),
                endpoint_id=None,
                user_id=user_id,
                sprache=sprache,
                cronjob_id=eintrag.id,
            )
            cronablauf.start_verbuchen(repositories, eintrag, jetzt.isoformat())
            # The same line the tick writes when it starts one, so the log
            # reads as one story: a start by hand is a start of this entry,
            # and a reader looking for why a run exists finds it where the
            # others are.
            log.info(
                "Cronjob: '%s' started by hand",
                eintrag.agent,
                extra={
                    "ereignis": "cronjob_handstart",
                    "cronjob": eintrag.id,
                    "agent": eintrag.agent,
                },
            )

    # Read back rather than reused: starting may have switched a one-off off
    # and has moved the clock, and the row this answers with is what the mask
    # puts straight onto the list.
    frisch = repositories.cronjobs.holen(cronjob_id) or eintrag
    antwort = HandStartResponse.aus(
        frisch,
        agent_folders=_agent_folders(request),
        letzter_ausgang=repositories.auftraege.letzter_auslauf(frisch.id),
        jetzt=jetzt,
        sprache=sprache,
    )
    antwort.notice = notice
    return antwort


@router.delete(
    "/{cronjob_id}", status_code=204, response_class=Response, summary="Delete a schedule"
)
def loeschen(
    cronjob_id: str,
    repositories: Repositories = Depends(hole_repositories),
    sprache: str = Depends(hole_sprache),
) -> Response:
    if not repositories.cronjobs.loeschen(cronjob_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, t("fehler.cronjob_not_found", sprache))
    cronjob_werkzeug.announce_change(cronjob_id)
    return Response(status_code=204)
