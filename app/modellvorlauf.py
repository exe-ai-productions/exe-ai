"""How far ahead the local model server should start before a cron entry
fires — a load once measured is a load that need not surprise
the next one.

The measurement itself lives in its own scope of the settings table
(``messwerte``, ``app/db/repositories/einstellungen.py``) — a fact about a
run, not a setting. Deliberately outside the cascade ``kette()`` builds
(``global``/``modell:``/``chat:``), so it can never surface in a chat's or
an endpoint's own settings.

The second half of the module is the act the measurement is for.
The two belonged together from the start and were separated by accident: the
old preloader asked an agent's ``model:`` head field which file to bring up,
that field was retired, and the preloader went with it — which
left everything above write-only. Every load went on writing down its
seconds and nothing ever read one again.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from app import agentenmodellwahl, agentenserver, runnermodellwahl
from app.db.repositories.einstellungen import MESSWERTE
from app.modellrunner import RunnerFehler

log = logging.getLogger(__name__)

MINDEST_SEKUNDEN = 5 * 60
HOECHST_SEKUNDEN = 10 * 60
# On top of the measured load time — the model is still meant to be READY,
# not merely started, by the time the cron entry actually fires.
PUFFER_SEKUNDEN = 2 * 60

# How long the preload of one file stands down after a load of it came to
# nothing (see `_Ruhe`). One flat stretch, every time — it does not grow.
#
# It is longer than one full reach on purpose: inside a reach a retry could
# not even be told apart from the attempt that just failed, because the same
# due moment is still the one being loaded for.
RUHE_SEKUNDEN = 15 * 60


def messung_setzen(repositories, modell: str, sekunden: float) -> None:
    """Records how long ``modell`` took to load this time — overwrites the
    previous measurement, since only the most recent load reflects what the
    machine can actually do right now."""
    repositories.einstellungen.setzen(MESSWERTE, modell, sekunden)


def messung_holen(repositories, modell: str) -> float | None:
    wert = repositories.einstellungen.holen(MESSWERTE, modell)
    return float(wert) if isinstance(wert, (int, float)) else None


def vorlauf_sekunden(repositories, modell: str) -> float:
    """How long before a due time the local model should already be
    starting — the measured load time plus a buffer, clamped to five to
    ten minutes. Never measured yet, or a measurement so large the buffered
    value would exceed the ceiling: both fall back to the ceiling itself,
    the safer of the two guesses.

    Purely a calculation — logging the capped case lives with the caller,
    which knows whether a preload is actually about to happen. Called from
    a 30-second tick regardless of reach, this would otherwise log the same
    line for a due time hours away, over and over, for as long as the
    measurement stands."""
    gemessen = messung_holen(repositories, modell)
    if gemessen is None:
        return HOECHST_SEKUNDEN
    return min(HOECHST_SEKUNDEN, max(MINDEST_SEKUNDEN, gemessen + PUFFER_SEKUNDEN))


def gedeckelt(gemessen: float | None) -> bool:
    """Whether a measurement, once buffered, would exceed the ceiling — for
    a caller that only wants to mention the cap when it actually matters."""
    return gemessen is not None and gemessen + PUFFER_SEKUNDEN > HOECHST_SEKUNDEN


def abstand_sekunden(moment: datetime, jetzt: datetime) -> float:
    """Real seconds between two moments — not wall-clock ones.

    Both sides of every comparison here carry the SAME ``ZoneInfo`` object:
    the tick is handed its ``jetzt`` in the app's zone (app/wecker.py) and
    every due moment is built out of it, either by replacing fields on it or
    by ``croniter`` walking from it (app/terminplan.py). Subtracting two
    datetimes that share one ``tzinfo`` is documented to ignore the zone
    entirely — no offset is asked for on either side, so what comes out is
    the distance on the wall clock.

    Which is the true distance on all but two days a year. On the day the
    clocks go forward the wall clock skips an hour that never happens, and a
    plan of 03:05 seen at 01:58 then reads as sixty-seven minutes away when
    seven is the truth: outside the reach, so nothing preloads — and the next
    tick is already past 03:00 with the entry due, which is the one case this
    whole module exists to prevent. Every plan between 02:00 and roughly
    03:10 is affected, in all three schedule shapes.

    Going through UTC asks both sides for their offset. Naive datetimes are
    left to plain subtraction: they carry no offset to ask for, and mixing
    the two kinds raises in the subtraction either way.
    """
    if moment.tzinfo is None or jetzt.tzinfo is None:
        return (moment - jetzt).total_seconds()
    return (
        moment.astimezone(timezone.utc) - jetzt.astimezone(timezone.utc)
    ).total_seconds()


# --- Bringing the main model up before a due time --------------
#
# The loading table read "main model — nobody loads it
# automatically", and the reason given was not a decision but a
# consequence: the whole start choice — file, window, layers, port, modules
# — lived in the browser's localStorage, so at program start there was
# nothing to ask which file with which settings "the main model" even was.
# A tick that wanted to load it would have had to guess.
#
# A later change moved that choice into a setting the program can read with
# nobody watching (app/runnermodellwahl.py). The consequence is gone, and
# with it the sentence it produced.
#
# Why a stored file counts as permission to load it unattended
# ------------------------------------------------------------
# The slot has a switch, and the switched-on switch is the consent
# (app/agentenserver.py). This has no switch of its own. What it has is three
# acts of the user's, and all three have to coincide before a byte is read:
#
#   1. The one field is ON and set to the main model — the sentence
#      "everything that runs unattended here runs on my main model".
#   2. An entry in the cron table, made by hand, active, and coming due —
#      the sentence "run this, then".
#   3. A start choice naming a file: the file THEY last started this server
#      with, never one this code went looking for.
#
# Together those are not "a file is lying around somewhere", they are a
# standing order with a time on it. And the memory is spent either way: with
# the field on the main model that entry cannot run on anything else, so the
# choice is not between nineteen gigabytes and none — it is between
# nineteen gigabytes at 02:58 and the same nineteen at 03:00 with the entry
# waiting for them. This moves WHEN, not WHETHER.
#
# What follows from that, and is enforced below: it never picks a file (no
# choice stored, nothing happens), never touches a server that is already
# running (whatever that one holds is what the user is using), and never
# tries twice for the same due moment.

# cronjob id -> the due moment a start was already attempted for. In memory
# for the same reason the waiting state is (app/cronablauf.py): it is a fact
# about right now, and a restart that changed the situation must not inherit
# a "already tried" from the one before it.
_versucht: dict[str, datetime] = {}


def _versuche_vergessen(bekannte: set[str]) -> None:
    """Drops the memory of entries the table no longer offers — a deleted
    schedule must not leave a due moment behind for an id that gets reused."""
    for cronjob_id in list(_versucht):
        if cronjob_id not in bekannte:
            del _versucht[cronjob_id]


# --- Noticing that the server went away ----------
#
# "One attempt per due moment" covered two ways a start can come to nothing:
# refused outright (RunnerFehler), or a server that is already up. It did not
# cover the third, and at nineteen gigabytes the third is the likeliest of
# all: the process starts, and llama-server dies WHILE loading — memory that
# the picture server, the slot or a chat is already holding, a broken file, a
# failed mmap. The preload had logged "is being preloaded" and considered the
# case closed; nothing said the load had died, and every following due moment
# was a fresh nineteen-gigabyte attempt. On a ``*/1`` schedule that is once a
# minute, without end.
#
# There is no fourth state to ask the runner about: ``laeuft()`` is False for
# a server that never came up, for one that died mid-load and for one the
# user switched off by hand. Two things tell them apart, and neither one is
# a guess:
#
#   * The runner says whether the server it held was ENDED (``stoppen``) or
#     fell over — ``von_hand_gestoppt``, added for exactly this question.
#     Without it a stop pressed WHILE the nineteen gigabytes were still being
#     read looked precisely like a load that died: same cold server, same
#     measurement that never moved. Measured on the running program before it
#     existed: a stop twenty seconds into the load, then thirteen minutes of
#     ticks with a due moment every single minute — not one further attempt,
#     and a warning line saying the model had died, which it had not.
#   * Whether the load ever finished. Every finished load writes its seconds
#     down here (app/main.py's bereit_callback calls ``messung_setzen``), so
#     a measurement that has not moved since the start is a load that never
#     reported ready. That one hangs on a line of the engine's log
#     (``app/modellrunner.py``'s ``_BEREIT_MUSTER``), so it gets a second
#     witness that hangs on no text at all: the endpoint this preload
#     announced answering ``/v1/models`` under 500. A llama-server still
#     reading its file answers 503 there, so "was reachable once" cannot
#     mean anything but "the model was loaded".
#
# The two cases want opposite answers, which is why they are told apart:
#
#   * **Died while loading** — the file could not come up on this machine
#     just now. Trying again at the next due moment would cost another
#     nineteen gigabytes and, if nothing changed, end the same way. So the
#     preload stands down for that file — a quarter of an hour, every time,
#     never for good (see ``_Ruhe``). And the user is told, once — not
#     because a message replaces a fix, but because "your main model does
#     not load" is the finding itself.
#
#   * **Went away after it had served, or was ended by hand** — almost
#     always to free exactly the memory a preload would take straight back.
#     Standing down for good would be wrong here: with the field on the main
#     model, preloading is the ONLY thing that brings this server up, so a
#     permanent stand-down would silently retire every cron entry the user
#     has. What the stop cancels is the preload it was aimed at — every due
#     moment within one reach of it, refused through the same "already
#     attempted" memory that guarantees one attempt per due moment. The
#     moment after that preloads as usual.


@dataclass
class _Beobachtung:
    """The main server as the previous tick saw it.

    ``von_uns`` separates a server this preload brought up from one that was
    already there, ``messung`` is the measurement that stood the moment it
    was started, and ``bereit`` is latched the first tick the announced
    endpoint answers — the three together answer "did the load this preload
    started ever finish?" once the process is gone.
    """

    datei: str
    von_uns: bool
    messung: float | None
    bereit: bool = False


@dataclass
class _Ruhe:
    """A stand-down for one file, with an end on it.

    The bolt this replaces had no end: it was lifted only by something the
    user did — the server running again, another file chosen, the field
    switched away and back, a restart. But the likeliest cause of a load
    dying is memory somebody else is holding (the picture server, the slot, a
    chat), and *freeing* that memory is none of those four things. So a file
    could lie still while the reason had long gone, with nothing anywhere
    saying "press start". The slot, faced with the same question, simply
    tries again every tick.

    Hence: the stand-down holds for ``RUHE_SEKUNDEN`` and then lets one
    attempt through — the same fifteen minutes every time, for as long as the
    situation lasts. A transient cause is picked up inside a quarter of an
    hour; a file that genuinely cannot load on this machine costs four
    attempts an hour instead of one a minute. What it never becomes is "never
    again".

    It used to double — ten minutes, twenty, forty, up to a day — on the idea
    that the more often a load had failed, the less likely the next one was
    to work. That idea was a guess and nothing else: the program does not
    know WHY a load died (the runner keeps no exit code and no log tail past
    the process), so after the eighth failure it knows exactly what it knew
    after the first. A wait may only be as long as there is reason for it, so
    the reason it had — one failed attempt, nothing since — buys one flat
    stretch and no more.

    ``freigegeben`` is what lets that one attempt through: once the stretch
    has passed the stand-down is over, but the object stays until the next
    death replaces it, so the "already attempted" memory is cleared exactly
    once and not on every tick that follows. Anything the user does that says
    "the situation is different now" drops the whole thing.
    """

    datei: str
    bis: datetime
    freigegeben: bool = False


def _ruhetext() -> str:
    """The stretch as the log should say it."""
    return f"{int(RUHE_SEKUNDEN // 60)} Minuten"


def _von_hand_gestoppt(runner) -> bool:
    """Whether the runner says its last server was ended rather than lost.

    Asked through ``getattr`` for the stand-ins that answer only the handful
    of questions the older code asked; those get the answer this module used
    to assume for everything — "nobody stopped it".
    """
    frage = getattr(runner, "von_hand_gestoppt", None)
    return bool(frage()) if callable(frage) else False


def _endpunkt_erreichbar(app) -> bool:
    """Whether the endpoint the preload announced is answering right now.

    The second witness for "this server became ready", and the one that hangs
    on no log text: reachable means the provider got an answer under 500 from
    ``/v1/models`` (app/providers/openai_kompatibel.py), and a llama-server
    that is still reading its file answers 503 there.
    """
    from app.api.v1.runner import RUNNER_ID

    discovery = getattr(app.state, "discovery", None)
    zustand = getattr(discovery, "zustaende", {}).get(RUNNER_ID)
    return bool(zustand is not None and zustand.erreichbar)


def _bereit_geworden(app, repositories, beobachtung: "_Beobachtung") -> bool:
    """Whether the server this observation is about has finished loading.

    The two witnesses ``gestorben`` already reads, asked the other way round
    — there is no third one, and there must not be: the seconds a finished
    load writes down here (app/main.py's ``bereit_callback``), and the
    announced endpoint answering.

    What is deliberately NOT a witness is that the process is alive. A
    nineteen-gigabyte load takes minutes to read, so it is found running by
    at least one thirty-second tick before it dies — and a load that is still
    reading its file says nothing about whether the file loads. Reading it as
    "the load worked" used to lift the stand-down the moment a server of any
    kind appeared, so a hand start that then died mid-load left no stand-down
    at all and the preload was back at the very next due moment.

    The measurement is only asked about a server this preload started,
    because only there is there a "before" to compare against — for one the
    user brought up himself, an older measurement of the same file says
    nothing about this run.
    """
    if _endpunkt_erreichbar(app):
        return True
    return (
        beobachtung.von_uns
        and messung_holen(repositories, beobachtung.datei) != beobachtung.messung
    )


# Set while the main server is up, cleared the tick it is found gone.
_oben: _Beobachtung | None = None
# The file whose preload stands down after a load died on the way up.
_ruhe: _Ruhe | None = None
# When the main server was last found gone without having died mid-load.
_stopp: datetime | None = None


def _beobachtung_vergessen() -> None:
    """Forgets everything about the main server's comings and goings.

    Called whenever the one field is not pointing at the main model: nothing
    is being preloaded then, so a stop or a crash in that stretch is the
    user's own business with his own server and must not be held against the
    first preload after he points the field back here.
    """
    global _oben, _ruhe, _stopp
    _oben = None
    _ruhe = None
    _stopp = None


def _hauptserver_beobachten(app, repositories, runner, jetzt: datetime) -> None:
    """Compares the main server against what the previous tick saw of it.

    The whole relationship this module used to have with the running server
    was "it is up, so do nothing" — one line, no memory, no way to notice
    that anything had changed. This is the memory.
    """
    global _oben, _ruhe, _stopp
    if runner.laeuft():
        if _oben is None:
            # Up without this preload having started it — the ordinary case:
            # the user has his model running and works with it.
            lauf = runner.lauf()
            _oben = _Beobachtung(
                datei=(lauf.modell if lauf else None)
                or runnermodellwahl.modell(repositories)
                or "",
                von_uns=False,
                messung=None,
            )
        if not _oben.bereit and _bereit_geworden(app, repositories, _oben):
            # It answered, or it wrote its seconds down. Whatever the engine's
            # log did or did not say, this server finished loading — latched
            # here because the answer has to survive the process it is about
            # (a dead endpoint reads as unreachable a few seconds later).
            _oben.bereit = True
        if _oben.bereit:
            # A main server that BECAME READY is the all-clear for the
            # stand-down: whatever kept the last load from coming up is over,
            # and the wait has no reason left. This is what makes a start by
            # hand end the stretch — the user brought the file up himself, so
            # it plainly loads.
            #
            # A server that is merely up is not the all-clear: while it is up
            # it may be a load still reading its file. Lifting the stand-down
            # there and having that load die too would leave no stand-down at
            # all, and the preload would be back at the very next due moment.
            _ruhe = None
        # A stop that has been taken back is no longer a stop, and taking it
        # back is the start itself — it needs no load to finish.
        _stopp = None
        return

    if _oben is None:
        return
    gefallen, _oben = _oben, None

    gestorben = (
        gefallen.von_uns
        # Ended, not lost: the memory was wanted back, and that is a stop —
        # even when it comes mid-load, where nothing else can tell the two
        # apart.
        and not _von_hand_gestoppt(runner)
        # Never answered, by either witness.
        and not gefallen.bereit
        and messung_holen(repositories, gefallen.datei) == gefallen.messung
    )
    if gestorben:
        # It died on the way up. Stand down for this file — for the one flat
        # stretch, however many loads of it have died before.
        _ruhe = _Ruhe(
            datei=gefallen.datei,
            bis=jetzt + timedelta(seconds=RUHE_SEKUNDEN),
        )
        log.warning(
            "Main model '%s' died while loading — it is not preloaded again "
            "for %s, then tried once more",
            gefallen.datei,
            _ruhetext(),
            extra={
                "ereignis": "hauptmodell_laden_gestorben",
                "modell": gefallen.datei,
                "ruhe_sekunden": RUHE_SEKUNDEN,
            },
        )
        return

    _stopp = jetzt
    log.info(
        "Main model '%s' is no longer up — the scheduled runs in range "
        "do not load it again",
        gefallen.datei,
        extra={"ereignis": "hauptmodell_vorladen_ausgesetzt", "modell": gefallen.datei},
    )


async def hauptmodell_vorladen_wenn_faellig(
    app,
    jetzt: datetime,
    termine_holen: Callable[[], list[tuple[str, datetime]]],
) -> bool:
    """Starts the main model server ahead of a cron entry that is close to
    coming due, so the model is loading while there is still time instead of
    the entry waiting for it.

    ``termine_holen`` hands over pairs of "entry" and "the moment it needs a
    model by" — a moment already past for one that is overdue. It is a
    callable and not a list because it costs a walk of the cron table and a
    schedule computation per entry, and on almost every tick one of the cheap
    questions below answers "no" long before that work is worth doing.

    Returns whether a start was actually launched. ``False`` covers every
    other case alike — no field, no file, nothing due yet, a server already
    up, a start that was refused — because the caller does nothing different
    for any of them: the due time stays open and the entry waits visibly,
    exactly as it did before this existed. No run is created and nothing is
    counted against the entry.
    """
    global _oben, _ruhe
    runner = getattr(app.state, "modellrunner", None)
    if runner is None:  # pragma: no cover - always built in app/main.py
        return False
    repositories = app.state.repositories

    if not agentenmodellwahl.hauptmodell_ist_das_ziel(
        repositories, app.state.discovery, slot_id=agentenserver.ENDPUNKT_ID
    ):
        # Every answer that is not "the run lands on the main server" ends
        # here, and they all mean the same: this run does not wait for it, so
        # nothing is loaded ahead of it. A slot file loads itself
        # (app/agentenserver.py), a foreign id has nothing to load at all, and
        # while OUR AGENT SERVER answers the run goes to it. Comparing
        # against the run's own order is what keeps the
        # tool question in it: a main model that cannot call the tools this
        # run needs is not the server it lands on either. Loading the main
        # model for a run that will not land on it would take memory, and
        # could take a server out from under the chat.
        _beobachtung_vergessen()
        return False

    if not runnermodellwahl.vorladen_erlaubt(repositories):
        # Switched off by hand: the user would rather bring his own server up
        # than have the program do it. The entry waits visibly and runs the
        # moment a model is there — the program exactly as it was before this
        # existed.
        #
        # Forgotten rather than merely skipped, and read on every tick rather
        # than once: switching the toggle is the user saying the situation is
        # different now, so a stand-down or a stop from before it may not
        # still be standing when he switches it back on — and the switch has
        # to take effect on the tick he moves it, not on the next due moment.
        _beobachtung_vergessen()
        return False

    # Before anything is decided: is the main server still the one the last
    # tick saw? This is the only place that looks, and it has to look on
    # every tick — a load that dies takes a whole tick to show, and a stop
    # by hand shows in the same place.
    _hauptserver_beobachten(app, repositories, runner, jetzt)

    if runner.laeuft():
        # Never touch a running server, not even when it holds a different
        # file than the stored choice names. ``runner`` means "the main
        # server's currently loaded model" (app/agentenmodellwahl.py), so
        # whatever is up IS what the field points at; and swapping it would
        # take the model out from under whoever is chatting with it right
        # now. Preloading exists for the cold case and has no business in
        # the warm one.
        return False

    datei = runnermodellwahl.modell(repositories)
    if datei is None:
        # Nothing named. ``None`` (never chosen) and ``""`` (chosen: none)
        # are two different answers to "which file", and the same answer to
        # this question — neither one names something to load. The only
        # place they would part is guessing a file for the first, and
        # guessing is the very thing this may not do.
        return False

    if _ruhe is not None and _ruhe.datei == datei and not _ruhe.freigegeben:
        if abstand_sekunden(_ruhe.bis, jetzt) > 0:
            # A load of this file came to nothing, and the stretch it stands
            # down for is not over. Silent here on purpose: the line that
            # says so was written once, when it happened, and repeating it
            # every thirty seconds would be the same fault in the log that
            # the repeated load was in memory.
            return False
        # The stretch is over. One attempt is due again, and it gets a clean
        # slate: "already attempted" is what a due moment is refused with,
        # and the moment that was refused when the stand-down began is, for
        # an entry that is overdue, still the very same moment (see
        # app/cronablauf.py's `_bereitschaftstermine`). Left standing, the
        # daily entry whose preload died would never get its second attempt
        # at all, and the stand-down would end on paper only.
        _ruhe.freigegeben = True
        _versucht.clear()
        log.info(
            "Main model '%s' is preloaded again — the rest after the "
            "last load attempt is over",
            datei,
            extra={"ereignis": "hauptmodell_ruhe_vorbei", "modell": datei},
        )

    termine = termine_holen()
    _versuche_vergessen({cronjob_id for cronjob_id, _ in termine})
    reichweite = vorlauf_sekunden(repositories, datei)

    for cronjob_id, moment in termine:
        if abstand_sekunden(moment, jetzt) > reichweite:
            continue
        if _stopp is not None and abstand_sekunden(moment, _stopp) <= reichweite:
            # Switched off by hand while this due moment was within one reach
            # of it — the memory was wanted back, and bringing the same
            # nineteen gigabytes straight up again is exactly what the stop
            # was for. Written into the same memory as a real attempt, so it
            # stays refused once the moment goes from coming to overdue. The
            # entry waits visibly, as it does whenever no model is there.
            _versucht[cronjob_id] = moment
            continue
        if _versucht.get(cronjob_id) == moment:
            # One attempt per due moment, never one per tick. A start that
            # was refused must not be retried thirty seconds later for the
            # same due time — that would be a load attempt every half minute
            # for as long as the entry stands. The entry waits visibly
            # instead, and the next due moment gets its own attempt.
            continue
        _versucht[cronjob_id] = moment

        # Worth a line only here, where a preload is actually about to
        # happen. Computed on every tick regardless of reach, this would
        # repeat for a due time hours away for as long as the measurement
        # stands.
        gemessen = messung_holen(repositories, datei)
        if gedeckelt(gemessen):
            log.info(
                "Lead time for '%s' capped at %d minutes (measured load time: %.0fs)",
                datei, HOECHST_SEKUNDEN // 60, gemessen,
                extra={"ereignis": "vorlauf_gedeckelt", "modell": datei},
            )

        try:
            # Window, layers, port, the modules chosen for exactly this file
            # and the engine levers — all from the stored choice, the same
            # single answer the window's own start button reads
            # (app/api/v1/runner.py). Nothing about how this server comes up
            # is decided here, which is what keeps two start paths from
            # bringing the same server up differently.
            lauf = runner.starten(
                datei, **runnermodellwahl.startwerte(repositories, datei)
            )
        except RunnerFehler as fehler:
            # Not worth stopping anything for: the due time stays open, the
            # entry waits visibly and nothing is counted against it. The
            # file may be gone, the port may still be held by a server on
            # its way down, or there may be no llama-server on this machine
            # at all.
            #
            # The same stand-down as a load that died, and for the same
            # reason: without one, this refusal is written into "already
            # attempted" for a due moment that — while the entry stays
            # overdue — never changes again, so a port that was busy for
            # thirty seconds used to cost that entry every further attempt
            # there would ever be. Measured before this: one start in three
            # days. With it, the next attempt comes when the stretch is over.
            _ruhe = _Ruhe(datei=datei, bis=jetzt + timedelta(seconds=RUHE_SEKUNDEN))
            log.warning(
                "Main model '%s' not preloaded (%s) — the scheduled run waits, "
                "another attempt in %s",
                datei, fehler, _ruhetext(),
                extra={
                    "ereignis": "hauptmodell_vorladen_fehlgeschlagen",
                    "modell": datei,
                    "cronjob": cronjob_id,
                    "ruhe_sekunden": RUHE_SEKUNDEN,
                },
            )
            return False

        # A process exists from here on, and nineteen gigabytes are being
        # read into memory. What the next tick needs in order to tell a load
        # that died from one that finished: the file, that it was this
        # preload that started it, and the measurement that stood before the
        # start.
        _oben = _Beobachtung(datei=datei, von_uns=True, messung=gemessen)

        # The started server has to join the model list, or this would load a
        # model nobody can find: the run resolves the field's id through the
        # discovery, and an unannounced server answers no question. Same call
        # the window's start makes, and the endpoint is built by the one
        # function that defines it rather than by a second copy of it here —
        # provider, dialect and key variable have to match exactly.
        #
        # The port comes out of the start itself, not out of ``lauf()``
        # afterwards: that one answers None for a process that has already
        # died, and the fallback behind it is the runner's DEFAULT port —
        # which registers a wrong address whenever the start choice names
        # another one. ``starten`` hands back what it actually used.
        from app.api.v1.runner import _runner_endpunkt

        await app.state.discovery.anmelden(_runner_endpunkt(lauf.port))
        log.info(
            "Main model '%s' is being preloaded — scheduled run in %ds, port %s, context %s",
            datei,
            max(0, int(abstand_sekunden(moment, jetzt))),
            lauf.port,
            lauf.kontext,
            extra={
                "ereignis": "hauptmodell_vorgeladen",
                "modell": datei,
                "cronjob": cronjob_id,
            },
        )
        return True

    return False
