"""Firing due entries from the cron table.

Independent, user-created schedules (app/db/repositories/cronjobs.py) —
several per agent are possible, as opposed to an agent's own single
``schedule:`` front-matter field, which stays app/wecker.py's job. Reuses
the alarm clock's own due-time and catch-up rules: only the most recent due
time counts, a still-running agent makes the schedule wait instead of
stacking, and every ending is decided once, kept column-side
(``zuletzt_ausgeloest``) so it survives a restart the same way the alarm
clock's database-backed check does for an agent's own schedule.

Called from ``Wecker.einmal_pruefen`` on the same 30-second tick — one clock,
not two.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime

from app import (
    agentenmodellwahl,
    agentenserver,
    auftragsende,
    cronmeldung,
    helper,
    i18n,
    modellvorlauf,
    no_agent,
    reminder,
    skriptlauf,
    sprachwahl,
    terminplan,
    zwischenstand,
)
from app.agenten import agenten_laden
from app.db.connection import jetzt_iso
from app.tools import cron_notiz, hintergrund, ziel_werkzeug
from app.wecker import als_aware, termin_ausloesen
from app.events import Ereignisse, bus


def _ausgeloest_merken(repositories, cronjob_id: str, termin_iso: str) -> None:
    """Writes down that an entry acted on a due time, and says so.

    Four places reach a due time and write it: a run started, a script run
    started, and the two where a run of that entry was still going so this
    one was skipped. All four change the row the schedules panel and its dot
    read, so all four are worth announcing — a skipped firing moves the
    entry's clock just as a real one does.
    """
    repositories.cronjobs.ausgeloest_setzen(cronjob_id, termin_iso)
    bus.veroeffentlichen_ohne_warten(Ereignisse.TERMIN_GEFEUERT, cronjob_id=cronjob_id)

log = logging.getLogger(__name__)

# What a goal adds to the task text on every firing. English, and
# fixed, for the same reason every other instruction the program hands a
# model is: it goes next to the system prompt, not into the interface.
#
# The last sentence is the one that carries the whole design. Without it a
# model that found nothing writes a paragraph saying so, the run ends, and
# nothing is announced — but the model has still spent a round explaining
# its silence. With it, "found nothing" and "stop" are the same instruction.
ZIEL_ZUSATZ = (
    "Goal: {ziel}. Call the {werkzeug} tool with a brief report ONLY when this goal has been "
    "achieved. Otherwise, finish without a notification."
)

# What the previous run wrote down, handed to this one. The
# timestamp is the program's own contribution and the reason this works at
# all: it says exactly when the note was current, so "new since then" is a
# fact rather than something the model has to reconstruct from its own text.
# It is the moment the note was WRITTEN — see ``auftragstext``.
NOTIZ_ZUSATZ = (
    "Your note from the previous run ({wann}): {notiz}\n"
    "Update it using the {werkzeug} tool when the state described in it changes. The call "
    "replaces the entire note."
)
# The same block for the one case where there is a note but no time to put
# on it. Note and time are written in one statement, so nothing new can get
# here — but a database that already carried a note when the time column was
# added does, and so would a hand-written row or a restored backup. An empty
# pair of brackets in the opening message of every run would be worse than
# saying nothing about the time.
NOTIZ_ZUSATZ_OHNE_ZEIT = (
    "Your note from the previous run: {notiz}\nUpdate it using the {werkzeug} tool when the "
    "state described in it changes. The call replaces the entire note."
)


# --- The one gate every notification passes -------------------------------


async def mitteilen(
    eintrag, text: str, *, erfolgreich: bool, sprache: str | None = None
) -> bool:
    """Plays the sound and shows the notification for ``eintrag``, unless the
    entry is on ``deliver = 'log'``. Returns whether anything went out.

    **``log`` means silent — every notification, not only the run's own
    closing one**. Five of them used to go out "no matter
    what ``deliver`` says": the ten-minute wait for a model
    (``_warten_vermerken``), a script that cannot start
    (``_skriptfehler_vermerken``), the failure limit (``_ausgang_buchen``),
    the one-off run that reported no goal and the "no goal report in N runs"
    notice (both ``ziel_verbuchen``). Each had its own good reason — a
    schedule that has stopped, or has not run for ten minutes, must not be
    something one only finds out about by looking — and together they meant
    the setting did not say what it says. A person who asked for a quiet
    schedule still got a system notification and a sound out of it.

    What was right about those reasons is kept, because none of them is
    about the notification: the log line and the entry's own lamp are
    written before this is ever called, and they are untouched. Silent is
    not invisible. It is only the macOS/Windows notification and the sound
    that the setting now really governs.

    ONE gate rather than the same condition copied into six places: the
    closing notification's own filter (``melde_wenn_faellig``) was the only
    one that ever existed, and a rule that lives in one branch of six is a
    rule that is already half broken. The sound goes with it, because
    ``cronmeldung.melden`` plays one — a "quiet" schedule that still made a
    noise would have kept exactly half the problem.

    An entry that is gone (``None``) says nothing either: there is no row
    left to speak for, and every caller here has already read it.

    Public, and named without the underscore, because the gate has a caller
    outside this module. The goal tool (``app/tools/ziel_werkzeug.py``) is
    the seventh notification the program makes and was the only one this gate
    never saw, so a schedule on ``log`` still rang and still made a sound the
    moment its run reported a goal. It reaches in from there rather than
    asking ``deliver`` a second time of its own — the rule stays in ONE
    place, which is the whole point of this function.
    """
    if eintrag is None or eintrag.deliver == "log":
        return False
    await asyncio.to_thread(
        cronmeldung.melden, text, erfolgreich=erfolgreich, sprache=sprache
    )
    return True


# --- Waiting for a model ---------------------------------------
#
# A due time with no model to run it on is NOT a failed run. Nothing was
# attempted and nothing is broken — the server simply is not up yet. Counting
# it as a failure would kill an entry two and a half minutes into a
# machine's boot, five ticks at thirty seconds apiece, for no fault of its
# own.
#
# So it is its own state, and it is visible in three ways: the mask shows it
# per entry (``GET /cronjobs``), the log takes every fruitless check as it
# always did, and after ten minutes of it ONE notification goes out — once
# per outage, not once per tick.
#
# Held in memory rather than in a column on purpose. It is a fact about right
# now, not about the entry: after a restart nothing is waiting until the next
# due tick finds out that something still is, and that tick is thirty seconds
# away. A column would carry a stale "waiting" across a restart that fixed it.
WARTEMELDUNG_SEKUNDEN = 600

# cronjob id -> (first tick that found nothing, whether it has been announced)
_wartend: dict[str, tuple[datetime, bool]] = {}


def wartet_auf_modell(cronjob_id: str) -> bool:
    """Whether this entry currently has a due time it cannot run."""
    return cronjob_id in _wartend


# Entries somebody started by hand while their model was still coming up. The
# tick starts each of them once, as soon as the model answers, and forgets it.
# Held in memory for the reason ``_wartend`` is: it is a fact about right now,
# and a restart that stopped the model's start has stopped the wish with it.
_hand_start_wanted: set[str] = set()


def want_hand_start(cronjob_id: str) -> None:
    """Notes that this entry is to run as soon as its model answers."""
    _hand_start_wanted.add(cronjob_id)


def start_verbuchen(repositories, eintrag, termin_iso: str) -> None:
    """Books a run this entry actually started: the wait is over, the due
    time is spent, and a one-off has done its one thing.

    Three callers reach this — the model run, the script run and the hand
    start (app/api/v1/cronjobs.py) — and what makes it one function rather
    than three copies is the one-off rule: an entry that fires and stays on
    fires again tomorrow. Only a start counts. A due time merely SKIPPED
    because a run was still going stamps the clock (``_ausgeloest_merken``)
    and nothing else; that is why the skip paths do not come through here.

    The hand start passes the moment it happened as its due time, which is
    what stops the next tick from firing the same past due time a second
    time (``einmal_pruefen`` only fires a due time newer than this stamp).
    A due time still in the future is untouched by it.

    A one-off is switched off only once its moment has come. A hand start
    before that is a trial run: the plan stays, and the entry still fires
    at its moment. Asked before the clock is stamped, because the stamp is
    what "not served yet" is read against.
    """
    reached = eintrag.einmalig and _moment_reached(
        eintrag, als_aware(termin_iso)
    )
    _warten_vergessen(eintrag.id)
    _hand_start_wanted.discard(eintrag.id)
    _uebersprungen_gesagt.pop(eintrag.id, None)
    _unreadable_reported.discard(eintrag.id)
    _ausgeloest_merken(repositories, eintrag.id, termin_iso)
    if reached:
        repositories.cronjobs.aktiv_setzen(eintrag.id, False)


def _moment_reached(eintrag, jetzt: datetime) -> bool:
    """Whether a one-off entry's moment has come by ``jetzt``: its most
    recent due moment lies at or before ``jetzt`` and has not been served
    yet. A fixed moment still ahead has not come; neither has a daily time
    whose last occurrence lies before the entry was made or last fired. A
    schedule that cannot be read counts as come, so such an entry is not
    kept alive by a start."""
    try:
        moment = _letzter_relevanter_termin(eintrag, jetzt)
    except ValueError:
        return True
    if moment > jetzt:
        return False
    letzter_bekannt = eintrag.zuletzt_ausgeloest or eintrag.created_at
    return als_aware(letzter_bekannt) < moment


# Which due time this entry was last SAID to be skipped for. Only so the
# line is written once per moment; the decision itself needs no memory.
_uebersprungen_gesagt: dict[str, datetime] = {}


def _holt_nach(eintrag) -> bool:
    """Does a due time skipped on this entry have to be CAUGHT UP?

    The question is not "is it dated" but "is there a next moment". Three
    spellings say there is none, and all three are the same entry to the
    user — the one that runs once:

      * ``einmalig`` with a ``datum`` (the dated one-off),
      * an instant schedule ``YYYY-MM-DDTHH:MM``, which is a single moment
        whatever else is set — the program calls it "once" itself
        (app/tools/cronjob.py, `_haeufigkeit`),
      * ``einmalig`` with a plain daily time and no date: it has a next
        occurrence tomorrow, but the user asked for ONE, and firing it a day
        late is not what "as soon as free" means.

    Asking only the first of the three left the most common form — the
    instant schedule — stamped and dead, which is the very defect this is
    the fix for: a missed run is meant to be caught up, not skipped.
    """
    if eintrag.einmalig:
        return True
    try:
        return terminplan.sorte(eintrag.zeitplan) == terminplan.SORTE_ZEITPUNKT
    except terminplan.TerminplanFehler:
        # An unreadable schedule is nobody's one-off. The tick that reads it
        # deals with that on its own; here it simply is not a catch-up case.
        return False


def _uebersprungen_merken(repositories, eintrag, termin: datetime) -> bool:
    """Books a due time that was SKIPPED because a run was still going.

    A recurring entry stamps it: this occurrence is spent, and the next one
    is a new moment. An entry that runs ONCE has no next one — stamping it
    made the entry "already fired" for good, and the run the user asked for
    never happened at all.

    So a one-off is NOT stamped. Its moment stays in the past and unstamped,
    and the next pass fires it the moment nothing is running any more —
    which is what catching up IS here. Same shape as the one the house
    already has for a held-back wake (app/hintergrundwecken.py, `_nachholen`):
    nothing is queued and nothing is remembered, because the condition that
    will fire it is already written down.

    Said once, not once per tick: without the stamp the entry reaches the
    skip branch on every pass, and a four-hour run would otherwise leave
    some five hundred identical lines in the log. Same rule the module
    keeps for a missing script and for a waiting model.
    """
    if not _holt_nach(eintrag):
        _ausgeloest_merken(repositories, eintrag.id, termin.isoformat())
        _uebersprungen_gesagt.pop(eintrag.id, None)
        return True
    gesagt = _uebersprungen_gesagt.get(eintrag.id) == termin
    _uebersprungen_gesagt[eintrag.id] = termin
    return not gesagt


def _warten_vergessen(cronjob_id: str) -> None:
    """A run started — the wait is over, and the next one starts fresh."""
    _wartend.pop(cronjob_id, None)


def _modell_bereit(app, agent, *, hat_ziel: bool = False) -> bool:
    """Whether the model an unattended run would go to is answering.

    Asked BEFORE the run is built rather than read out of the failure
    afterwards: ``auftrag_anstossen`` reports an unreachable model as a
    translated sentence, and branching on a sentence is how a message change
    turns into a silent behaviour change.

    The question is asked exactly the way the run resolves it
    (app/api/v1/auftraege.py) — and that resolution has two steps, so this
    has two: the one field's id when it has one, and otherwise the main
    model, and when that is not answering the next reachable LOCAL endpoint
    (`agentenmodellwahl.rueckfall`). Nothing here knows or cares
    which of the three kinds the field holds; that is the whole point of the
    field handing out one id.

    ``agent`` is what makes the second half answerable at all. An endpoint without ``tool_calls`` does not refuse a run — it
    runs it WITHOUT the tools, and an agent whose work is its tools then
    answers out of the model's own head and the job reads 'fertig'. So tool
    capability decides where a run goes, and this has to ask it with the
    same two readings the run uses, or it reports "ready" for a run that is
    then refused: that is how a due time ended up logged as
    ``termin_fehlgeschlagen`` instead of shown as "waiting for a model".
    """
    discovery = app.state.discovery
    # ``tools:`` left out entirely means every approved tool, an explicit []
    # means none. The fallback's own filter reads exactly this much.
    #
    # ``hat_ziel`` is the second reading the start makes: an entry with a goal
    # lends its run the goal tool, so a run for an agent with an explicit []
    # still calls one. Without it the two disagree exactly there — this one
    # reports "ready", the start then finds no endpoint that can call tools
    # and refuses, and the due time is left open with nothing booked and
    # nothing shown, to be tried again on every tick for ever.
    benutzt_werkzeuge = agent.werkzeuge != [] or hat_ziel
    # What the FIELD is measured against: whether this run would really be
    # given tools. Narrower on purpose, and narrower than the fallback's —
    # with tools off house-wide there is nothing to lose, so the field's
    # answer stands whatever the endpoint can do (app/api/v1/auftraege.py).
    werkzeuge_moeglich = bool(
        getattr(app.state, "werkzeuge", None) is not None
        and app.state.config.features.mcp
        and benutzt_werkzeuge
    )
    # The same question the start asks, asked of the same function: the hand
    # pick first (there is none here — a schedule fires with no window open),
    # then the field, then the main model, then the next reachable LOCAL one.
    # Both live in `agentenmodellwahl.lauf_kennung`, so this
    # pre-check can never answer "ready" for a schedule the start then
    # refuses, nor "not ready" for one the start would run: a pre-check that
    # disagrees either way leaves the due time open, books nothing, and
    # repeats its warning on every tick — exactly what the comment above
    # forbids.
    #
    # It used to be a loop over every reachable endpoint, and that loop is
    # gone from the start (app/api/v1/auftraege.py).
    kennung = agentenmodellwahl.lauf_kennung(
        app.state.repositories,
        discovery,
        slot_id=agentenserver.ENDPUNKT_ID,
        werkzeuge=werkzeuge_moeglich,
    )
    if kennung is None:
        # No model at all: nothing chosen, the main server down and no local
        # endpoint answering either. The start refuses such a run with 400,
        # so it is nothing this schedule can wait for.
        return False
    gefunden = discovery.aufloesen(kennung)
    # An id that resolves to nothing, or to something that is not answering,
    # is what waiting is FOR — the run refuses it too (404/503) rather than
    # quietly going somewhere else.
    return gefunden is not None and gefunden[0].erreichbar


MODEL_READY = "ready"
MODEL_STARTING = "starting"
MODEL_MISSING = "missing"


async def wake_model(app, agent, *, hat_ziel: bool = False) -> str:
    """The way to the model, for the tick and for the hand start alike: is
    the model answering — and if not, does the program bring its server up?

    ``MODEL_READY``: the run can start now. ``MODEL_STARTING``: nothing
    answered, the slot's server is up or has just been started, and the
    model is on its way — what a run can wait for. ``MODEL_MISSING``: nothing
    answers and the program has no server to start, which a run cannot wait
    for.

    The slot is woken even with the preload switch off
    (``agentenserver.slot_starten_wenn_gewollt``, ``faellig``): that switch
    only holds back the blind autostart at program launch, not the program
    answering a run that needs the slot right now.
    """
    if _modell_bereit(app, agent, hat_ziel=hat_ziel):
        return MODEL_READY
    if not await agentenserver.slot_starten_wenn_gewollt(app, faellig=True):
        return MODEL_MISSING
    if _modell_bereit(app, agent, hat_ziel=hat_ziel):
        return MODEL_READY
    return MODEL_STARTING


# The ending reason of a due time that found no model to run on. It is a key
# of the reasons block of the catalogue (``jobs.grund``), the one place every
# ending's words are kept (app/cronmeldung.py ``mit_grund``).
END_REASON_NO_MODEL = "kein_modell_verfuegbar"


async def _fail_without_model(app, eintrag, termin: datetime) -> None:
    """One due time of an entry without an agent that finds no model: the
    run is written down as failed at once, with the reason, and booked like
    any other failed run — the failure counter, the notification.

    An entry with an agent waits for its model (``_warten_vermerken``), for
    a file it names can be brought up. An entry without one goes to the main
    model, and when nothing answers and nothing can be started there is
    nothing a wait would change: it stood on "waiting for a model" for good,
    with no run and no reason anywhere. The due time is spent, so the
    schedule's next one is read like every other."""
    repositories = app.state.repositories
    sprache = sprachwahl.interface_language(repositories, app.state.config.app.language)

    from app.api.abhaengigkeiten import STANDARD_BENUTZER

    run = repositories.auftraege.erstellen(
        user_id=getattr(app.state, "standard_benutzer", STANDARD_BENUTZER),
        agent=eintrag.agent,
        auftrag=eintrag.task,
        cronjob_id=eintrag.id,
    )
    auftragsende.beenden(repositories, run.id, "gescheitert", ende_grund=END_REASON_NO_MODEL)
    start_verbuchen(repositories, eintrag, termin.isoformat())
    log.warning(
        "Cronjob: scheduled run of '%s' failed — no model reachable",
        eintrag.agent,
        extra={"ereignis": "cronjob_kein_modell", "cronjob": eintrag.id, "auftrag": run.id},
    )
    angehalten = await ausgang_verbuchen(
        repositories, eintrag.id, eintrag.task, erfolgreich=False,
        grund=END_REASON_NO_MODEL, sprache=sprache,
    )
    await melde_wenn_faellig(
        repositories, eintrag.id, eintrag.task, erfolgreich=False,
        grund=END_REASON_NO_MODEL, sprache=sprache, schon_gemeldet=angehalten,
    )


async def _warten_vermerken(eintrag, jetzt: datetime, sprache: str | None = None) -> None:
    """Books one tick that found no model, and announces a long wait once.

    The log line and the entry's own "waiting" state are written whatever
    ``deliver`` says — a schedule that has been unable to run for ten
    minutes has to be findable. The notification and the sound are not:
    ``log`` means silent (``mitteilen``). Announced once per outage either
    way, never once per tick.
    """
    seit, gemeldet = _wartend.get(eintrag.id, (jetzt, False))
    log.info(
        "Cronjob: scheduled run of '%s' waits for a model",
        eintrag.agent,
        extra={
            "ereignis": "cronjob_wartet_auf_modell",
            "cronjob": eintrag.id,
            "agent": eintrag.agent,
        },
    )
    if gemeldet or (jetzt - seit).total_seconds() < WARTEMELDUNG_SEKUNDEN:
        _wartend[eintrag.id] = (seit, gemeldet)
        return
    _wartend[eintrag.id] = (seit, True)
    log.warning(
        "Cronjob '%s' has been waiting for a model for %d minutes",
        eintrag.agent,
        WARTEMELDUNG_SEKUNDEN // 60,
        extra={
            "ereignis": "cronjob_wartemeldung",
            "cronjob": eintrag.id,
            "agent": eintrag.agent,
        },
    )
    await mitteilen(
        eintrag,
        i18n.t(
            "cronjobs.wartet_seit_minuten",
            sprache,
            aufgabe=eintrag.task,
            minuten=WARTEMELDUNG_SEKUNDEN // 60,
        ),
        erfolgreich=False,
        sprache=sprache,
    )


def auftragstext(eintrag) -> str:
    """The task this firing hands the run — the entry's own text, plus its
    note and its goal where it has them.

    Built here rather than stored on the row: the goal and the task are two
    separate things a person edits separately, and gluing them together at
    firing time means an edited goal takes effect on the very next run
    without anything having to be rewritten. The note has a second reason on
    top of that — it changes on nearly every run, and a stored copy would be
    stale before it was ever read.

    An entry without a note costs nothing at all: no empty paragraph, no
    line about there being no note. The very first run of an entry must read
    exactly the way it did before this existed, or every schedule in the
    program pays for a feature only some of them use.

    Order is deliberate: the note is context and comes first, the goal is
    the instruction and comes last. Both after the task, which is what the
    run is actually about.

    The time on the note is ``notiz_am``, the moment it was WRITTEN, and not
    the previous firing's due time. The two look interchangeable and are
    not: a due time is stamped even when the firing was SKIPPED because a
    run was still going (``einmal_pruefen``), and that skip can land AFTER
    the note was written by the run that was still going at the time —

        10:00  due, run starts
        10:03  the model writes the note
        10:15  due, skipped — stamped anyway
        10:20  the run ends
        10:30  the next run is told "your note from 10:15"

    Everything between 10:03 and 10:15 then counts as already seen, and is
    never reported by anyone. The moment of the write cannot say that: it is
    what the note actually describes.

    The note and the goal go through ``ohne_ablagebloecke`` on the way in.
    Both are text a MODEL wrote, and what is glued on here lands right behind
    the task — which is where the entry carries what the previous run still
    owes the agent dock (``app/zwischenstand.py``). Without this, a note that
    reproduced that block would speak as the program: the run would open
    owing a file nobody recorded, fail for it, and go on failing until
    ``fehlergrenze`` switched the entry off.
    """
    bloecke = [eintrag.task]
    if eintrag.notiz:
        vorlage = NOTIZ_ZUSATZ if eintrag.notiz_am else NOTIZ_ZUSATZ_OHNE_ZEIT
        bloecke.append(
            vorlage.format(
                wann=eintrag.notiz_am,
                notiz=zwischenstand.ohne_ablagebloecke(eintrag.notiz),
                werkzeug=cron_notiz.WERKZEUG_NAME,
            )
        )
    if eintrag.ziel:
        bloecke.append(
            ZIEL_ZUSATZ.format(
                ziel=zwischenstand.ohne_ablagebloecke(eintrag.ziel),
                werkzeug=ziel_werkzeug.WERKZEUG_NAME,
            )
        )
    return "\n\n".join(bloecke)


def _termin_mit_datum(eintrag, jetzt: datetime) -> datetime:
    """The one fixed due moment a dated one-off entry has — unlike a daily
    'HH:MM', this never recurs and never shifts with ``jetzt``.

    The ``datum`` column and the schedule field are two spellings of the
    same thing: a day plus a time. Joining them into the instant form the
    schedule field itself can carry means there is one piece of
    code that turns a day and a time into a moment, not two."""
    return terminplan.letzter_termin(f"{eintrag.datum}T{eintrag.zeitplan}", jetzt)


def _datiert_einmalig(eintrag) -> bool:
    """Whether ``datum`` actually applies — only ever meaningful together
    with ``einmalig``. An update can turn ``einmalig`` back off
    without this module's say-so, and a stale ``datum`` left over from that
    must not keep pinning a now-daily entry to a single day that already
    passed."""
    return bool(eintrag.datum) and eintrag.einmalig


def _letzter_relevanter_termin(eintrag, jetzt: datetime) -> datetime:
    """``terminplan.letzter_termin``, aware of a dated one-off entry:
   its fixed moment stands in for "the most recent due time"
    instead of the schedule field's own recurrence, and — unlike a daily
    time or a cron expression — can still lie in the future, which callers
    must check for themselves."""
    if _datiert_einmalig(eintrag):
        return _termin_mit_datum(eintrag, jetzt)
    return terminplan.letzter_termin(eintrag.zeitplan, jetzt)


def _naechster_relevanter_termin(eintrag, jetzt: datetime) -> datetime:
    """The forward-looking mirror of the above — what a preload measures its
    lead time against. A dated one-off entry has one fixed moment
    and both directions name it."""
    if _datiert_einmalig(eintrag):
        return _termin_mit_datum(eintrag, jetzt)
    return terminplan.naechster_termin(eintrag.zeitplan, jetzt)


def naechste_faelligkeit(eintrag, jetzt: datetime) -> datetime | None:
    """When this entry runs next, or ``None`` if it never does again.

    What the list shows beside a schedule (app/api/v1/cronjobs.py). Computed
    from the schedule rather than stored: the schedule IS the answer, and a
    column beside it would be a second one to keep in step.

    The same two readings the preload makes (``_bereitschaftstermine``), and
    for the same reason — they are what the firing loop above actually does:

    * **Overdue** — a due time in the past this entry never served. It is
      the answer even though it has gone by: the next tick fires it, and an
      entry whose script was missing at 08:00 runs the moment the file is
      back, not tomorrow morning.
    * **Still to come** — the next due moment otherwise.

    Three entries have no answer at all and say so rather than naming a
    moment that will not happen:

    * one that is switched off — a paused entry is not due at any point,
      and the same rule the two live states follow (``CronjobAntwort.aus``);
    * a one-off whose fixed moment has passed and was served;
    * one whose stored schedule or timestamp cannot be read at all. The
      tool is the only door a schedule is stored through and it takes
      nothing else, so nothing can arrive here today — and the tick skips
      such a row (``_unreadable``), but a list that went down with it would
      hide the very entry somebody has to go and fix.
    """
    if not eintrag.aktiv:
        return None
    try:
        frueher = _letzter_relevanter_termin(eintrag, jetzt)
        letzter_bekannt = eintrag.zuletzt_ausgeloest or eintrag.created_at
        # Compared on the absolute clock: two moments of one zone compare
        # by their wall-clock fields, which loses the repeated hour.
        if (
            terminplan.absolute(frueher) <= terminplan.absolute(jetzt)
            and als_aware(letzter_bekannt) < frueher
        ):
            return frueher
        termin = _naechster_relevanter_termin(eintrag, jetzt)
    except ValueError:
        # Both ``TerminplanFehler`` and croniter's own refusals are one.
        return None
    return termin if terminplan.absolute(termin) >= terminplan.absolute(jetzt) else None


# The entries whose unreadable schedule was already reported, so the log
# says it once per entry rather than on every tick.
_unreadable_reported: set[str] = set()


def _unreadable(eintrag) -> None:
    """One log line for an entry whose schedule cannot be read. The entry
    is skipped and the pass goes on: one broken row must not keep every
    entry after it from firing. It stays in the list, where somebody can
    see and fix it (``naechste_faelligkeit`` answers ``None`` for it)."""
    if eintrag.id in _unreadable_reported:
        return
    _unreadable_reported.add(eintrag.id)
    log.warning(
        "Cronjob: schedule of entry %s cannot be read (%r) — skipped, the others run",
        eintrag.id,
        eintrag.zeitplan,
        extra={"ereignis": "cronjob_unlesbar", "cronjob": eintrag.id},
    )


def _bereitschaftstermine(repositories, agenten: dict, jetzt: datetime) -> list[tuple[str, datetime]]:
    """Per active entry, the moment it needs a model by.

    Handed to the preload (app/modellvorlauf.py), which compares each moment
    against the measured load time of the file it would bring up. Two
    readings, the same two the firing loop above already makes:

    * **Overdue** — a due time in the past that has not been served. Its own
      past moment is what goes out, not ``jetzt``: the moment has to stay
      the same across ticks or "one attempt per due moment" would be one
      attempt per tick with extra steps.
    * **Still to come** — the next due moment. A fixed one (an instant, or a
      dated one-off) that has already been served answers this with a moment
      in the PAST while not being overdue, and such an entry is dropped: it
      will never come due again, and its negative lead time would otherwise
      read as "due right now" forever.

    Three kinds of entry never appear here at all: a script entry and a
    reminder, which both run without a model, and one whose agent file is
    missing, which cannot run at all — loading a model for any of them would
    be memory spent on a run that is not going to happen.
    """
    termine: list[tuple[str, datetime]] = []
    for eintrag in repositories.cronjobs.aktive():
        if eintrag.skript or reminder.is_reminder(eintrag) or (
            agenten.get(eintrag.agent) is None
            and not helper.is_helper(eintrag.agent)
            and not no_agent.is_no_agent(eintrag.agent)
        ):
            continue
        try:
            frueher = _letzter_relevanter_termin(eintrag, jetzt)
            letzter_bekannt = eintrag.zuletzt_ausgeloest or eintrag.created_at
            if (
                terminplan.absolute(frueher) <= terminplan.absolute(jetzt)
                and als_aware(letzter_bekannt) < frueher
            ):
                termine.append((eintrag.id, frueher))
                continue
            naechster = _naechster_relevanter_termin(eintrag, jetzt)
        except ValueError:
            # Both ``TerminplanFehler`` and croniter's own refusals are one.
            _unreadable(eintrag)
            continue
        if terminplan.absolute(naechster) >= terminplan.absolute(jetzt):
            termine.append((eintrag.id, naechster))
    return termine


# --- Script entries --------------------------------------------
#
# A script that cannot be started is the script entry's version of "waiting
# for a model", and until now it was the one state a script entry had no way
# of showing. Moving the scripts folder from the interface writes the new
# location and moves nothing, so every entry in the table goes quiet at once:
# the path check fails, the due time stays open — rightly, nothing is broken
# about the entry and its failure budget must not pay for a folder someone
# moved — and the only trace was one log line every thirty seconds. The
# schedule simply stopped happening, and nobody was told.
#
# So the same three ways out the model wait has: the entry can say so
# (skript_nicht_startbar below), the log takes every fruitless check, and
# after ten minutes ONE notification goes out — once per outage, not once per
# tick. Held in memory for the same reason: it is a fact about right now, and
# a column would carry a stale "cannot start" across a restart that fixed it.

# cronjob id -> (first tick that could not start it, whether it was announced,
# the refusal as catalogue KEY and values).
#
# The key and its values rather than a finished sentence: the tick writes it
# once and the panel reads it in whatever language the browser asks in,
# minutes later and possibly in the other one. A sentence stored here would
# be the language of the machine that happened to be running at the time.
#
# And the pair rather than the exception it came from. A caught exception
# still carries its traceback, so a module-level dict holding one would pin
# the frames it was raised through — with the app, the repositories and the
# entry in them — for as long as the outage lasts.
_skript_fehlt: dict[str, tuple[datetime, bool, tuple[str, dict]]] = {}


def skript_nicht_startbar(cronjob_id: str, sprache: str | None = None) -> str | None:
    """Why this entry's script cannot be started right now, or ``None``.

    The sentence, not a flag: "there is no script 'sicherung.sh' in <folder>"
    and "'sicherung.sh' is not executable" are two different things to go and
    do, and an entry that only said "cannot start" would send the user
    looking for which.

    Rendered here, in the reader's language. The German panel used to wrap an
    English middle: "Kann nicht starten — There is no script 'x' in ...".
    """
    eintrag = _skript_fehlt.get(cronjob_id)
    if eintrag is None:
        return None
    schluessel, werte = eintrag[2]
    return i18n.t(schluessel, sprache, **werte)


def _skriptfehler_vergessen(cronjob_id: str) -> None:
    """The script started — the outage is over, and the next one starts
    counting from zero."""
    _skript_fehlt.pop(cronjob_id, None)


async def _skriptfehler_vermerken(
    eintrag, fehler: skriptlauf.SkriptVerboten, jetzt: datetime, sprache: str | None = None
) -> None:
    """Books one tick whose script could not be started, and announces a long
    outage once.

    Log line and lamp whatever ``deliver`` says, notification and sound only
    where the entry asks for them — the same rule the model wait follows
    (``mitteilen``). The notification is read by a person, so it comes in
    the interface's language (``sprachwahl.interface_language``), both its
    frame and the reason — the reason through the key the refusal carries,
    as the panel shows it.
    """
    grund = (fehler.schluessel, fehler.werte)
    seit, gemeldet, _ = _skript_fehlt.get(eintrag.id, (jetzt, False, grund))
    log.warning(
        "Cronjob: script '%s' cannot start — %s",
        eintrag.skript,
        fehler,
        extra={
            "ereignis": "cronjob_skript_abgewiesen",
            "cronjob": eintrag.id,
            "skript": eintrag.skript,
        },
    )
    if gemeldet or (jetzt - seit).total_seconds() < WARTEMELDUNG_SEKUNDEN:
        _skript_fehlt[eintrag.id] = (seit, gemeldet, grund)
        return
    _skript_fehlt[eintrag.id] = (seit, True, grund)
    log.warning(
        "Cronjob '%s' has not been able to start for %d minutes",
        eintrag.skript,
        WARTEMELDUNG_SEKUNDEN // 60,
        extra={
            "ereignis": "cronjob_skript_meldung",
            "cronjob": eintrag.id,
            "skript": eintrag.skript,
        },
    )
    await mitteilen(
        eintrag,
        i18n.t(
            "cronjobs.script_cannot_start",
            sprache,
            script=eintrag.skript,
            minutes=WARTEMELDUNG_SEKUNDEN // 60,
            reason=i18n.t(fehler.schluessel, sprache, **fehler.werte),
        ),
        erfolgreich=False,
        sprache=sprache,
    )


async def _skript_termin(app, eintrag, termin: datetime, jetzt: datetime) -> None:
    """One due time of a script entry: check, start, stamp.

    The tick's half of the work. What the file check does when it fails is
    the whole difference to a hand start, and it is why this wrapper exists:
    a due time nobody asked for stays open and quiet-but-noted, while a
    person who pressed a button is told what is wrong with their script.
    """
    repositories = app.state.repositories

    if repositories.auftraege.laeuft_fuer_cronjob(eintrag.id):
        # The same rule an agent entry follows, asked per entry rather than
        # per name: a script that is still going makes its own schedule wait
        # instead of stacking a second copy on top of it.
        if _uebersprungen_merken(repositories, eintrag, termin):
            log.info(
                "Cronjob: scheduled script run '%s' skipped — a run is still active",
                eintrag.skript,
                extra={"ereignis": "cronjob_uebersprungen", "cronjob": eintrag.id},
            )
        return

    try:
        await skript_starten(app, eintrag, termin)
    except skriptlauf.SkriptVerboten as fehler:
        # Left unhandled, exactly like a missing agent file above: the due
        # time stays open, no run is created and nothing is counted against
        # the entry. Putting the script back picks the schedule right up
        # again, and a folder moved by mistake does not cost the entry its
        # failure budget on the way.
        #
        # But not silently. Unhandled used to mean invisible as well, and an
        # entry that quietly stops happening is worse than one that fails
        # loudly — see the block above this function.
        await _skriptfehler_vermerken(
            eintrag, fehler, jetzt,
            sprachwahl.interface_language(
                app.state.repositories, app.state.config.app.language
            ),
        )


async def reminder_show(app, entry, moment: datetime):
    """Shows a reminder (app/reminder.py): the system's notification with its
    text and the sound, once — no model, no answer. The body the tick and a
    hand start (app/api/v1/cronjobs.py) both run.

    Shown whatever ``deliver`` says: the notification IS the reminder, and a
    silent one would be no reminder at all.

    It still leaves a row in ``auftraege``, ended at once, so the history,
    the calendar and the lamp see it the way they see every other run — a
    reminder that fired is a day in the past that did happen.
    """
    repositories = app.state.repositories
    from app.api.abhaengigkeiten import STANDARD_BENUTZER

    run = repositories.auftraege.erstellen(
        user_id=getattr(app.state, "standard_benutzer", STANDARD_BENUTZER),
        agent=reminder.REMINDER_AGENT,
        auftrag=entry.task,
        zustand="fertig",
        cronjob_id=entry.id,
    )
    await asyncio.to_thread(cronmeldung.melden, entry.task, erfolgreich=True)
    start_verbuchen(repositories, entry, moment.isoformat())
    bus.veroeffentlichen_ohne_warten(
        Ereignisse.AUFTRAG_BEENDET, auftrag_id=run.id, cronjob_id=entry.id
    )
    log.info(
        "Cronjob: reminder %s shown, no model: %s",
        entry.id,
        entry.task,
        extra={"ereignis": "cronjob_reminder", "cronjob": entry.id},
    )
    return run


async def skript_starten(app, eintrag, termin: datetime):
    """Starts this entry's script and returns the job row it created.

    The body both the tick and the hand start (app/api/v1/cronjobs.py) run.
    Everything a model run needs and this does not is simply absent — no
    agent file, no model readiness, no goal, no note. What it does keep is
    the bookkeeping every other run has: a row in ``auftraege``, so the run
    list, the history, the lamp, the failure counter and the announcement go
    on working with no second set of books behind them.

    Raises ``skriptlauf.SkriptVerboten`` when the file is not where it has
    to be. The caller decides what that means: the tick notes it and leaves
    the due time open, a person gets told.
    """
    repositories = app.state.repositories
    sprache = sprachwahl.interface_language(repositories, app.state.config.app.language)
    wurzel = skriptlauf.ordner(app.state.config)
    # Checked again here, not only when the entry was written: the folder can
    # be moved from the interface, the file can be swapped for a link pointing
    # out of it, and the execute bit can be taken away. A guard that only ran
    # at creation would be a statement about a file that no longer exists.
    pfad = skriptlauf.geprueft(wurzel, eintrag.skript)

    from app.api.abhaengigkeiten import STANDARD_BENUTZER

    grenze = eintrag.zeitgrenze or skriptlauf.ZEITGRENZE_VORGABE
    auftrag = repositories.auftraege.erstellen(
        user_id=getattr(app.state, "standard_benutzer", STANDARD_BENUTZER),
        agent=skriptlauf.SKRIPT_AGENT,
        # What the run is about, in the one field the history shows: the
        # script's name. A script entry has no task text, and inventing a
        # sentence for it would be the program speaking in the user's place.
        auftrag=eintrag.skript,
        cronjob_id=eintrag.id,
    )
    bus.veroeffentlichen_ohne_warten(
        Ereignisse.AUFTRAG_BEGONNEN,
        auftrag_id=auftrag.id,
        agent=auftrag.agent,
        cronjob_id=eintrag.id,
    )
    # The record the service's kill switch walks on the way down
    # (app/tools/hintergrund.py). Filed under the job's id, which is exactly
    # what a command inside a model job is filed under, so this adds no new
    # kind of entry to that list — it adds the one process that was missing
    # from it. Dropped again the moment the run ends (``vergessen`` below),
    # because a schedule firing every minute would otherwise leave 1440
    # records a day behind it.
    befehlslauf = hintergrund.laeufe.anlegen(auftrag.id, pfad.name)
    _skriptfehler_vergessen(eintrag.id)
    lauf = app.state.generierungen.starten(
        chat_id=auftrag.id,
        # No endpoint, and that is the whole point of this step: nothing is
        # resolved, nothing is loaded, no model process is started. The run
        # management only carries the id around.
        endpoint_id="",
        arbeit=_skriptarbeit(
            repositories=repositories,
            sprache=sprache,
            generierungen=app.state.generierungen,
            auftrag_id=auftrag.id,
            cronjob_id=eintrag.id,
            pfad=pfad,
            wurzel=wurzel,
            grenze=grenze,
            befehlslauf=befehlslauf,
        ),
        an_verbindung_gebunden=False,
    )
    repositories.auftraege.generation_verknuepfen(auftrag.id, lauf.id)

    start_verbuchen(repositories, eintrag, termin.isoformat())
    log.info(
        "Cronjob: script '%s' started — job %s (%s, limit %ds)",
        eintrag.skript,
        auftrag.id,
        pfad,
        grenze,
        extra={
            "ereignis": "cronjob_skript_gestartet",
            "cronjob": eintrag.id,
            "skript": eintrag.skript,
            "pfad": str(pfad),
            "auftrag": auftrag.id,
        },
    )
    return auftrag


def _skriptarbeit(
    *,
    repositories,
    sprache: str | None = None,
    generierungen,
    auftrag_id: str,
    cronjob_id: str,
    pfad,
    wurzel,
    grenze: int,
    befehlslauf=None,
):
    """The background half: run the script, write the ending, book it.

    Built as a closure for the same reason the model run is: the loop that
    finds a due time must not wait for the work it starts. A backup running
    for an hour would otherwise hold up the thirty-second tick, and with it
    every other schedule in the table.
    """

    async def arbeit(lauf) -> None:
        repositories.auftraege.schritt_anlegen(
            auftrag_id, "status", i18n.t("cronjobs.skript_gestartet", sprache, name=pfad.name)
        )
        try:
            # ``lauf.signal`` is the stop button, and this is the line that
            # makes it mean anything here: cancelling is cooperative in this
            # program, and a script run used to be the one run that never
            # looked. Both routes that stop a run set exactly this signal
            # (app/api/v1/auftraege.py) — the cancel button and the deletion
            # of the job, whose comment promises "gone means gone, not keeps
            # running headless".
            ergebnis = await skriptlauf.starten(
                pfad, wurzel, grenze, abbruch=lauf.signal, lauf=befehlslauf, sprache=sprache
            )
            if ergebnis.abgebrochen:
                # The user's own doing a second ago, not a fault of the entry:
                # its own state, no reason of failure, and — below — no
                # booking against the failure count and no announcement. That
                # is what the model path does, and a hand stop that quietly
                # ate a schedule's failure budget was the difference.
                zustand, grund = "abgebrochen", "benutzer_abbruch"
            else:
                # Exit code 0 and nothing else. There is no model here to read
                # an answer, so the process's own verdict is the whole verdict
                # — and a run stopped at the time limit is one of the
                # failures, never a quiet success.
                zustand = "fertig" if ergebnis.erfolgreich else "gescheitert"
                grund = None
                if ergebnis.abgelaufen:
                    grund = "zeitgrenze"
                elif not ergebnis.erfolgreich:
                    grund = skriptlauf.GRUND_FEHLGESCHLAGEN
            if befehlslauf is not None:
                hintergrund.laeufe.beenden(
                    befehlslauf,
                    ergebnis.code,
                    zustand=hintergrund.ABGEBROCHEN if ergebnis.abgebrochen else None,
                )
            log.info(
                "Cronjob: script '%s' ended — %s",
                pfad.name,
                zustand,
                extra={
                    "ereignis": "cronjob_skript_beendet",
                    "cronjob": cronjob_id,
                    "skript": pfad.name,
                    "auftrag": auftrag_id,
                    "zustand": zustand,
                    "grund": grund,
                    "code": ergebnis.code,
                },
            )
            # The job may be gone: DELETE stops the run first and then deletes
            # it, so by now there can be nothing left to write the ending to
            # and a step without a job would be a foreign key violation. Asked
            # exactly the way the model run asks it.
            if repositories.auftraege.holen(auftrag_id) is None:
                return
            repositories.auftraege.schritt_anlegen(
                auftrag_id, "ergebnis", ergebnis.ausgabe
            )
            auftragsende.beenden(
                repositories, auftrag_id, zustand,
                ende_grund=grund, ergebnis=ergebnis.ausgabe,
            )
            repositories.auftraege.generation_verknuepfen(auftrag_id, None)
            if ergebnis.abgebrochen:
                return
            # And then exactly the two bookings a model run gets, in the same
            # order and through the same functions (app/api/v1/auftraege.py).
            # The failure counter of a cron entry therefore applies to a script
            # entry unchanged — a backup that fails night after night stops
            # trying and says so — while goal, note and restart chains do not
            # apply at all: there is nothing here that could report or
            # remember.
            #
            # Two texts, because the two sentences are about different things.
            # The counter's is "<this schedule> stopped after N failed runs",
            # and the schedule is the script. The announcement is the run's
            # own result, and what a script that reports anything reports is
            # its last line — a script entry has no task text to put
            # there.
            #
            # The reason goes to both. On the run that reaches the limit the
            # counter's sentence is the only one that goes out
            # (``schon_gemeldet`` below), so it has to say why this last run
            # failed as well.
            angehalten = await ausgang_verbuchen(
                repositories, cronjob_id, pfad.name, erfolgreich=ergebnis.erfolgreich,
                grund=grund, sprache=sprache,
            )
            letzte = ergebnis.letzte_zeile
            await melde_wenn_faellig(
                repositories,
                cronjob_id,
                f"{pfad.name} - {letzte}" if letzte else pfad.name,
                erfolgreich=ergebnis.erfolgreich,
                sprache=sprache,
                # Why it ended, the same as the model run's own end path
                # does. Left out, a script stopped at its time limit
                # announced "Failed — sicherung.sh — <its last line>", and
                # the one thing the last line of a killed script never says
                # is that it was killed. The reports row had the reason; the
                # notification, the half of this that reaches somebody who
                # is not looking at the screen, did not.
                grund=grund,
                # And not twice at the failure limit: ``ausgang_verbuchen``
                # right above announces "stopped after N failed runs" on the
                # run that reaches it. Same rule the model run follows.
                schon_gemeldet=angehalten,
            )
        finally:
            # Unsubscribed whatever happened, and that is not tidiness. The
            # run object stayed in the manager's live list for the rest of the
            # program's life — a schedule at minute intervals left 1440 of
            # them a day behind — and, worse, the finished job kept pointing
            # at a "live" run: cancelling a script run that had ended hours
            # ago found it, answered "cancelling", and changed nothing.
            generierungen.abmelden(lauf.id)
            if befehlslauf is not None:
                hintergrund.laeufe.vergessen(auftrag_id)

    return arbeit


def entry_running(repositories, eintrag) -> bool:
    """Whether a run of this entry's work is still going — asked per agent
    name, the way two runs of one agent queue behind each other. Except for
    a helper's continuation and an entry with no agent: every helper, and
    every entry without one, carries the same name (app/helper.py,
    app/no_agent.py), and the name would make one piece of work wait for
    every other one under it, so its own work is the question — its runs
    and the continuations of them, which run under entries of their own."""
    if helper.is_helper(eintrag.agent) or no_agent.is_no_agent(eintrag.agent):
        return repositories.auftraege.laeuft_fuer_cronjob(eintrag.id)
    return repositories.auftraege.laeuft_gerade(agent=eintrag.agent)


async def einmal_pruefen(app, jetzt: datetime) -> None:
    """One pass over all active cron entries."""
    config = app.state.config
    repositories = app.state.repositories

    # Both layers, the user's winning — a cron entry may point at a shipped
    # agent just as well as at one the user wrote.
    agenten = agenten_laden(*config.agentenverzeichnisse)

    aktive = repositories.cronjobs.aktive()
    # An entry switched off or deleted while its wish was pending has no wish
    # any more: switching it on again is a different act.
    _hand_start_wanted.intersection_update(eintrag.id for eintrag in aktive)

    for eintrag in aktive:
        hand_start = eintrag.id in _hand_start_wanted
        if hand_start:
            # Started by hand while the model was coming up: due now, once.
            # The stamp it books is this moment, like the hand start's own.
            termin = jetzt
        else:
            try:
                termin = _letzter_relevanter_termin(eintrag, jetzt)
                letzter_bekannt = als_aware(eintrag.zuletzt_ausgeloest or eintrag.created_at)
            except ValueError:
                # Both ``TerminplanFehler`` and croniter's own refusals are
                # one, and so is a stamp that cannot be read.
                _unreadable(eintrag)
                continue
            if terminplan.absolute(termin) > terminplan.absolute(jetzt):
                # A dated one-off entry whose day has not arrived
                # yet — unlike a recurring schedule, its due moment can lie in
                # the future, and it must wait rather than fire early.
                continue
            # A freshly created entry has no ``zuletzt_ausgeloest`` yet, and a
            # recurring schedule always points at a moment in the past —
            # without a baseline that past due time would fire the instant it
            # is set, even for one still hours away. ``created_at`` stands in
            # until the entry has actually fired once: only a due time
            # strictly after creation counts as new.
            if letzter_bekannt >= termin:
                continue

        if reminder.is_reminder(eintrag):
            # A reminder runs nothing: its notification is the whole of it,
            # so it needs no agent file, no model and no "still running".
            await reminder_show(app, eintrag, termin)
            continue

        if eintrag.skript:
            # A script entry never reaches any of what follows: no
            # agent file to look up, no model to wait for, no task text to
            # dress with a goal or a note. It is its own short path, and it
            # is deliberately BEFORE the agent-name block below — every
            # script entry carries the same marker in ``agent``, so the
            # name-based "is one still running" would make them queue behind
            # each other.
            await _skript_termin(app, eintrag, termin, jetzt)
            continue

        if entry_running(repositories, eintrag):
            if hand_start:
                # A run of this entry is going: what the hand start asked
                # for is there, and a second one would only queue behind it.
                _hand_start_wanted.discard(eintrag.id)
                continue
            if _uebersprungen_merken(repositories, eintrag, termin):
                log.info(
                    "Cronjob: scheduled run of '%s' skipped — a run is still active",
                    eintrag.agent,
                    extra={"ereignis": "cronjob_uebersprungen", "cronjob": eintrag.id},
                )
            continue

        agent = helper.agent_named(
            eintrag.agent, agenten, repositories, getattr(app.state, "werkzeuge", None)
        )
        if agent is None:
            # The agent file behind this entry is gone — nothing to run as.
            # The due time stays open: a restored file picks the schedule
            # right back up, the same way a restored due time would. The
            # settings row says so (``agent_missing``, app/api/v1/cronjobs.py).
            log.warning(
                "Cronjob: agent '%s' not found — the scheduled run stays open",
                eintrag.agent,
                extra={"ereignis": "cronjob_agent_fehlt", "cronjob": eintrag.id},
            )
            continue

        # Nothing to run on: the due time stays open, no run is created and
        # nothing is counted against the entry. Asked here rather
        # than after a failed start, so the entry can say what it is waiting
        # for instead of only that it did not fire.
        # The slot is the one kind the program can fix by itself — it tries
        # again on every tick until the model is up, which is what makes an
        # autostart that lost a race harmless (``wake_model``).
        model = await wake_model(app, agent, hat_ziel=bool(eintrag.ziel))
        if model == MODEL_MISSING and no_agent.is_no_agent(eintrag.agent):
            # Nothing answers and the program has no server to bring up: a
            # run without an agent has nothing to wait for. It fails, and
            # says why, and the schedule's next due time starts normally.
            await _fail_without_model(app, eintrag, termin)
            continue
        if model != MODEL_READY:
            await _warten_vermerken(
                eintrag,
                jetzt,
                sprachwahl.interface_language(
                    app.state.repositories, app.state.config.app.language
                ),
            )
            continue

        auftrag = await termin_ausloesen(
            app, agent, auftragstext(eintrag), cronjob_id=eintrag.id
        )
        if auftrag is None:
            # Something else refused the start — an unknown tool, a broken
            # agent. That is not the waiting state, and it must not be
            # dressed up as one.
            continue

        start_verbuchen(repositories, eintrag, termin.isoformat())
        log.info(
            "Cronjob: '%s' started — job %s",
            eintrag.agent,
            auftrag.id,
            extra={
                "ereignis": "cronjob_gestartet",
                "cronjob": eintrag.id,
                "agent": eintrag.agent,
                "auftrag": auftrag.id,
            },
        )

    # Looking ahead, after the firing: whatever could run on what
    # is already up has run by now, so what is left is what has to be loaded
    # for. The due times are computed only if the preload gets that far — it
    # asks four cheap questions first and almost always stops at one of them.
    await modellvorlauf.hauptmodell_vorladen_wenn_faellig(
        app, jetzt, lambda: _bereitschaftstermine(repositories, agenten, jetzt)
    )


async def ausgang_verbuchen(
    repositories,
    cronjob_id: str | None,
    aufgabentext: str,
    *,
    erfolgreich: bool,
    grund: str | None = None,
    sprache: str | None = None,
) -> bool:
    """Books one ended run against its entry's failure count, and
    switches the entry off once the count reaches its limit. Returns whether
    an announcement went out over it — what the caller must not put a second
    one next to.

    ``grund`` is why this run ended, as the run's own end path knows it. It
    is read only on the run that reaches the limit, and only for the
    announcement: that sentence is the one notification the run gets, so
    the reason the run failed for travels in it (``_ausgang_buchen``).

    What counts as a failure is the run's technical outcome, and nothing
    else: the model was unreachable, a tool was refused, the run broke off.
    A run that went looking and found nothing to report ends properly and
    puts the count back to zero — checking the inbox every fifteen minutes
    and finding no new mail is a successful run, not a failed one, and an
    entry doing exactly what it was made for must never be switched off for
    it. An abort by hand never reaches here at all (app/api/v1/auftraege.py):
    it is the user's own doing a second ago, not a fault of the entry.

    The limit is announced ONCE, on the run that reaches it — never per
    failed run, which would be the notification flood this counter exists to
    avoid. On an entry set to ``log`` it is not announced at all
    (``mitteilen``): the schedule still switches itself off, still
    writes the line, still goes grey in the list. What ``log`` buys is
    quiet, and it buys it here too.

    One ending never gets here at all, and the caller is where that is
    decided (app/api/v1/auftraege.py): a context overflow
    that handed its work on to a scheduled continuation. That run did its
    work and wrote down where it stood — the same reasoning as the abort
    above, from the other end.

    **Booked on the entry the run belongs to AND on the entry that run's
    chain continues.** That second booking is the way out of an ending that
    would otherwise never be heard at all, and it is the same move the goal
    already makes (``_ziel_buchen``): a chain is a row that lives for a few
    minutes, an origin is the entry a person made and the only one that sees
    the same thing happen again tomorrow.

    Follow a permanently dead model server through without it. The origin's
    own run hands its work on, so it is not a failed run and is rightly not
    counted — but every one of its runs does that, so the origin never
    counts one again and its "stopped after N failed runs" never comes. The
    chain restarts every couple of minutes until the restart ceiling, where
    it is switched off before this function is ever reached, and the
    ``aktiv`` check below then blocks the announcement on that row too.
    Tomorrow the origin fires again, ``ist_kette`` is false, and it opens a
    brand new chain that dies exactly as quietly. The user is waiting for a
    mail and is never told anything again.

    With it, one dead day costs the origin exactly one failed run: the
    chain's last, the one that ran out of restarts with nothing behind it.
    After ``fehlergrenze`` such days the origin says so once and switches
    itself off — no daily repeat, and the same sentence the counter has
    always said. A single outage the provider comes back from costs nothing
    at all: the run that gets through counts as a success and puts the
    origin's count back to zero, from the chain just as much as from the
    origin's own next run.
    """
    if not cronjob_id:
        return False
    eintrag = repositories.cronjobs.holen(cronjob_id)
    if eintrag is None:
        return False

    ursprung = (
        repositories.cronjobs.holen(eintrag.ursprung_id)
        if eintrag.ursprung_id else None
    )
    # Only ONE of the two rows says it out loud, and it is the origin.
    # Both texts are the same sentence — the chain's
    # ``basisaufgabe`` is a copy of the origin's task — so with
    # ``fehlergrenze`` at 1 the same "stopped after 1 failed runs" went out
    # twice in the same moment.
    #
    # The origin is the one that speaks because the announcement is a
    # statement about a schedule having stopped, and the origin is the only
    # row for which that is true: it is the entry a person made, the one in
    # the mask, the one that would otherwise have run again tomorrow. A
    # chain is machinery that lives for a few minutes and is MEANT to end.
    # Worse than doubled, the chain's sentence can be simply false — a chain
    # at its limit next to an origin that is nowhere near its own would tell
    # the user a schedule stopped that runs again tomorrow.
    #
    # With no origin to speak for it the chain is the only row there is (a
    # job nobody scheduled names that run as its origin, and a run is no
    # entry — ``holen`` finds nothing), and then it says it itself.
    gemeldet = await _ausgang_buchen(
        repositories,
        cronjob_id,
        aufgabentext,
        erfolgreich=erfolgreich,
        melden=ursprung is None,
        grund=grund,
        sprache=sprache,
    )
    if ursprung is None:
        return gemeldet
    # Its own text, not the one handed in: the announcement speaks for the
    # origin, and the chain's ``basisaufgabe`` is a copy of that sentence as
    # it read when the chain was made. The reason is the run's, and the run
    # is the one that just ended — whichever row it was booked on first.
    ursprung_gemeldet = await _ausgang_buchen(
        repositories,
        ursprung.id,
        ursprung.basisaufgabe or ursprung.task,
        erfolgreich=erfolgreich,
        grund=grund,
        sprache=sprache,
    )
    # Either announcement is one the caller must not put a second one next
    # to (``schon_gemeldet``, ``ziel_verbuchen``).
    return gemeldet or ursprung_gemeldet


async def _ausgang_buchen(
    repositories,
    cronjob_id: str,
    aufgabentext: str,
    *,
    erfolgreich: bool,
    melden: bool = True,
    grund: str | None = None,
    sprache: str | None = None,
) -> bool:
    """The booking above, on one entry. Returns whether it announced.

    ``melden=False`` books and switches off in silence: the caller has a
    second row that says the same sentence better. Only the count and the
    switch belong to this row either way — the announcement does not.

    The announcement names the limit AND why the last run failed. The limit
    alone said that a schedule had stopped and not what had been wrong with
    it, and on the run that reaches the limit nothing else says it: the
    run's own closing notification, the one that carries the reason, is
    held back so one ending is announced once (``melde_wenn_faellig``). The
    reason stands behind the limit's sentence, put there by the same
    function that puts it behind a run's own text
    (``cronmeldung.mit_grund``) — so a run without a reason leaves the
    sentence exactly as it was, and a long error message can only ever
    push ITSELF out of a notification, never the fact that the schedule
    has stopped.
    """
    if erfolgreich:
        eintrag = repositories.cronjobs.holen(cronjob_id)
        # Only when there is something to clear — a healthy entry checking
        # in every minute has no business rewriting its own row for it.
        if eintrag is not None and eintrag.fehlversuche:
            repositories.cronjobs.fehlversuche_zuruecksetzen(cronjob_id)
        return False

    eintrag = repositories.cronjobs.fehlversuch_zaehlen(cronjob_id)
    if eintrag is None or eintrag.fehlversuche < eintrag.fehlergrenze:
        return False
    if not eintrag.aktiv:
        # Already off — a one-off that fired (which switches itself off at
        # firing time), a finished restart chain, or a switch somebody
        # flipped while this run was going. There is nothing left to stop,
        # and saying so a second time would be a message about nothing.
        return False

    repositories.cronjobs.aktiv_setzen(cronjob_id, False)
    log.warning(
        "Cronjob '%s' paused — %d failed runs in a row",
        eintrag.agent,
        eintrag.fehlversuche,
        extra={
            "ereignis": "cronjob_angehalten",
            "cronjob": eintrag.id,
            "agent": eintrag.agent,
            "fehlversuche": eintrag.fehlversuche,
        },
    )
    if not melden:
        # Switched off and written to the log all the same — silent means
        # only that the system notification belongs to the other row.
        return False
    # And on an entry set to ``log``, switched off and written to the log is
    # ALL of it: the row is off, the list shows it, the lamp
    # shows it, and nothing pops up. ``False`` is then the honest answer to
    # "did an announcement go out" — the caller reads it only to avoid
    # putting a second notification next to this one, and there is none.
    return await mitteilen(
        eintrag,
        cronmeldung.mit_grund(
            i18n.t(
                # One failed run is a singular in both languages; from two on
                # the count stands in the sentence.
                "cronjobs.nach_fehlversuchen_gestoppt_eins"
                if eintrag.fehlversuche == 1
                else "cronjobs.nach_fehlversuchen_gestoppt",
                sprache,
                aufgabe=aufgabentext,
                n=eintrag.fehlversuche,
            ),
            grund,
            sprache,
        ),
        erfolgreich=False,
        sprache=sprache,
    )


# The catalogue key of what a one-off entry with a goal says when its single
# run found nothing. A standing watch stays quiet because there is always a
# next pass; a `once` entry has none, so silence there means the order simply
# vanished.
ZIEL_NICHT_ERREICHT = "cronjobs.einmal_ohne_ziel"


def _ziel_buchen(repositories, eintrag, wann: str) -> None:
    """Books a reported goal onto one entry: the stamp, the quiet count back
    to zero (both in one statement), and the switch-off where the entry asks
    for it.

    One function because it happens twice for one report — on the entry
    whose run made it, and on the entry that run's chain continues. Nothing
    is announced here; the tool did that at the moment it was called
    (app/tools/ziel_werkzeug.py).
    """
    repositories.cronjobs.ziel_erreicht_setzen(eintrag.id, wann)
    if not (eintrag.ziel_stilllegen and eintrag.aktiv):
        return
    repositories.cronjobs.aktiv_setzen(eintrag.id, False)
    log.info(
        "Cronjob '%s' finished — goal reached",
        eintrag.agent,
        extra={
            "ereignis": "cronjob_abgeschlossen",
            "cronjob": eintrag.id,
            "agent": eintrag.agent,
        },
    )


async def ziel_verbuchen(
    repositories,
    cronjob_id: str | None,
    aufgabentext: str,
    *,
    bericht: str | None,
    erfolgreich: bool,
    fortsetzung_geplant: bool = False,
    schon_gemeldet: bool = False,
    sprache: str | None = None,
) -> None:
    """Books one ended run against its entry's goal.

    ``bericht`` is what the ``goal`` tool call carried in this run, or
    ``None`` if it was never called. That one piece of information is passed
    in rather than dug out of the step log afterwards, and deliberately so:
    the run already holds it — the tool loop reads it out of the call as it
    happens (app/api/v1/auftraege.py), exactly the way the chat's own path
    does (app/api/v1/generierung.py) — and reading it back out of the log
    would mean parsing JSON to learn something the run knew for certain a
    moment ago. It also keeps "was it called" one plain answer instead of a
    side effect scattered across the run, which is what a later checking
    build has to be able to replace with its own answer.

    **Nothing is announced here on the good path, and that is not an
    omission.** The tool announces at the moment it is called
    (app/tools/ziel_werkzeug.py) — with this very text, sound and all — so
    the user hears it while the run is still going instead of whenever it
    happens to wrap up. Announcing again here would be the same sentence
    twice. What is left for the end of the run is the bookkeeping the tool
    cannot do, because it does not know which entry it is speaking for: the
    stamp, the switch-off, and the quiet count.

    A run that ended badly is not counted as quiet either — it did not go
    and look, so it says nothing about whether the goal is being reported.
    That run is the failure counter's business (``ausgang_verbuchen``).

    ``fortsetzung_geplant`` is the one ending that looks bad and is not:
    a context overflow that handed its work on. Such a
    run DID go and look — it just ran out of room and put the rest on the
    clock — so it counts as quiet here, or an entry whose runs regularly
    overflow would never reach the quiet count at all and the insurance
    against a model that forgot the call would never fire on that path.

    ``schon_gemeldet`` says the failure counter already announced something
    about this very run (it hit its limit). Only the one-off case below
    reads it, and only so the user does not get two notifications about the
    same ending.
    """
    if not cronjob_id:
        return
    eintrag = repositories.cronjobs.holen(cronjob_id)
    if eintrag is None or not eintrag.ziel:
        return

    if bericht:
        wann = jetzt_iso()
        log.info(
            "Cronjob '%s': goal reported — %s",
            eintrag.agent,
            bericht,
            extra={
                "ereignis": "cronjob_ziel_erreicht",
                "cronjob": eintrag.id,
                "agent": eintrag.agent,
                "bericht": bericht,
            },
        )
        _ziel_buchen(repositories, eintrag, wann)
        # And on the entry this one is continuing the work of, if any. The
        # report belongs to that entry just as much: it is the one a person
        # made, the one still on the clock, and the one whose "stop when
        # reached" was the instruction in the first place. Left out, it goes
        # on firing after the thing has been found — and it reports the same
        # finding a second time the moment the goal is still recognisable on
        # its next pass, or, when it is not, eventually raises "no goal
        # report in N runs" about a goal that was reported long ago.
        ursprung = (
            repositories.cronjobs.holen(eintrag.ursprung_id)
            if eintrag.ursprung_id else None
        )
        if ursprung is not None:
            log.info(
                "Cronjob '%s': origin of the chain booked along",
                ursprung.agent,
                extra={
                    "ereignis": "cronjob_ursprung_gebucht",
                    "cronjob": ursprung.id,
                    "kette": eintrag.id,
                    "agent": ursprung.agent,
                },
            )
            # Its OWN ``ziel_stilllegen`` decides, not the chain's copy of
            # it: the two are the same until somebody edits the original,
            # and it is the original's own wish that has to win.
            _ziel_buchen(repositories, ursprung, wann)
        return

    # A one-off entry (`once`) has exactly one run, and this was it. Quiet
    # is the right answer for a standing watch — the next pass is fifteen
    # minutes away — but here there is no next pass, and an order that
    # vanishes without a word is the worst ending a goal entry can have: the
    # user never even learns that nothing was found. So it says so, once,
    # whether the run ended well or badly — but only where the entry
    # asked to be told at all (``mitteilen``). On ``log`` the
    # line in the log is the whole of it, the same as everywhere else.
    #
    # Not while a continuation is on the clock: the work is not over, and
    # the entry that carries it forward reports for it.
    if eintrag.einmalig and not fortsetzung_geplant:
        if not schon_gemeldet:
            log.info(
                "Cronjob '%s': one-off run without a goal report",
                eintrag.agent,
                extra={
                    "ereignis": "cronjob_ziel_nicht_erreicht",
                    "cronjob": eintrag.id,
                    "agent": eintrag.agent,
                },
            )
            await mitteilen(
                eintrag,
                f"{aufgabentext} - {i18n.t(ZIEL_NICHT_ERREICHT, sprache)}",
                erfolgreich=False,
                sprache=sprache,
            )
        return

    if not (erfolgreich or fortsetzung_geplant):
        return

    # A quiet run — the entry doing exactly what it is for. Counted, never
    # held against it: nothing is switched off here, and the entry keeps
    # running whatever this number reaches.
    eintrag = repositories.cronjobs.stillen_lauf_zaehlen(cronjob_id)
    if eintrag is None or eintrag.laeufe_ohne_ruf < eintrag.fehlergrenze:
        return
    log.info(
        "Cronjob '%s': no goal report for %d runs",
        eintrag.agent,
        eintrag.laeufe_ohne_ruf,
        extra={
            "ereignis": "cronjob_ohne_zielmeldung",
            "cronjob": eintrag.id,
            "agent": eintrag.agent,
            "laeufe": eintrag.laeufe_ohne_ruf,
        },
    )
    # Written to the log regardless of ``deliver`` — this is not the entry's
    # own report but the program saying it has heard nothing back, and a
    # model that quietly forgot the call would otherwise look exactly like a
    # goal that is simply not met yet. The notification follows the setting
    # (``mitteilen``).
    await mitteilen(
        eintrag,
        i18n.t(
            # One quiet run is a singular in both languages, like a single
            # failed run above.
            "cronjobs.ohne_zielmeldung_seit_eins"
            if eintrag.laeufe_ohne_ruf == 1
            else "cronjobs.ohne_zielmeldung_seit",
            sprache,
            aufgabe=aufgabentext,
            n=eintrag.laeufe_ohne_ruf,
        ),
        erfolgreich=False,
        sprache=sprache,
    )
    # Back to zero, entry untouched: the next stretch of quiet runs earns
    # its own notice instead of one after every single run from here on.
    repositories.cronjobs.stille_laeufe_zuruecksetzen(cronjob_id)


async def melde_wenn_faellig(
    repositories,
    cronjob_id: str | None,
    aufgabentext: str,
    *,
    erfolgreich: bool = True,
    fortsetzung_geplant: bool = False,
    grund: str | None = None,
    schon_gemeldet: bool = False,
    sprache: str | None = None,
) -> None:
    """Plays a sound and shows ``aufgabentext`` once a cron-fired run has
    ended, if the entry asks for it (``deliver = 'announce'``) — at the end,
    never at the start, so there is something to show by the time it fires.

    Called from the run's own end path (app/api/v1/auftraege.py): firing and
    finishing happen in different places — this loop only starts a run, the
    background task that runs it is the one that knows when it is done, and
    with which outcome.

    An entry with a goal is exempt: there, the goal decides what
    is announced and when, and announcing the task text after every run
    besides would put back the very flood the goal was set to stop.

    A run that handed its work on says nothing. Since a chain inherits
    ``deliver`` (app/zwischenstand.py),
    one piece of work carried over a restart used to announce twice: once
    from the run that ran out of room or lost its provider, once from the
    continuation that finishes it — and with a provider that stays dead, the
    chain restarts every couple of minutes, so ONE job could put ten
    notifications into the machine's notification centre in a day.

    ``announce`` means "tell me when this is through", and a run that hands
    its work on is not through. The rest of the program already reads it that
    way: the failure counter skips such a run entirely (``ausgang_verbuchen``
    is not even called for it), and the goal booking is told about it by
    name. This is the last place that still treated a handoff as an ending.

    What that gives up is nothing: the ending that really has nothing behind
    it — the chain that ran out of restarts, the overflow whose handoff came
    back empty, the outage the provider never came back from — sets no such
    flag and announces here as it always did. So the chain says it once, at
    its end, instead of once per link.

    ``schon_gemeldet`` says the failure counter already announced something
    about this very run — it reached its limit, and ``ausgang_verbuchen``
    said "… — stopped after N failed runs" on the way past. Then this one
    stays quiet, the same way ``ziel_verbuchen`` has read the same flag
    all along. Before, an entry on ``announce`` that broke on its last
    allowed run got two notifications a moment apart about one ending:
    "Failed — <task> — stopped after 1 failed runs" and "Failed — <task> —
    <reason>". One piece of work says its piece once, and the limit's
    sentence is the one that survives, because it carries the fact the other
    does not: this schedule has stopped and will not run again by itself.
    What the other one carried is not lost with it — the limit's sentence
    ends with the same reason (``_ausgang_buchen``).
    """
    if not cronjob_id or fortsetzung_geplant or schon_gemeldet:
        return
    eintrag = repositories.cronjobs.holen(cronjob_id)
    # The ``deliver == 'log'`` half of this condition moved into
    # ``mitteilen``, where all six notifications now ask it — this branch
    # was the only place that ever asked, and it answered for one of the six.
    # Nothing about THIS notification changes: the same row, the same
    # question, one line further down. What is left here is the goal
    # exemption, which is this function's own and nobody else's.
    if eintrag is None or eintrag.ziel:
        return
    # ``grund`` rides in this notification rather than in one of its own:
    # "Failed — <task>" told the user something had broken and left them with
    # no way to find out what, because the only place the reason was ever
    # written — the step log's `ende` line — leaves the screen in the same
    # breath the run ends. The text is built rather than a second argument
    # passed, exactly the way the failure limit adds its own half sentence
    # (``_ausgang_buchen``): one piece of work still says its piece once.
    await mitteilen(
        eintrag,
        cronmeldung.mit_grund(aufgabentext, grund, sprache),
        erfolgreich=erfolgreich,
        sprache=sprache,
    )
