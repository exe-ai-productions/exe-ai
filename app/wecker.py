"""The tick — the heartbeat the cron table is checked on.

Modeled on the endpoint check (``discovery.py``): a background loop in the
same process, started and stopped by the lifecycle.

This used to be two schedulers. Beside the cron table an agent could carry
its own ``schedule:`` field in its front matter, and both were checked from
here on the same tick. Two ways to say when something runs is one too many —
every later change would have to be made in both, and whoever knew only one
of them would build a bug. **The cron table is the one way**: the
agent loop is gone, and with it the pause after three failures, whose job the
cron entry's own failure counter does. What is left here is the
tick itself and the two shared helpers the cron flow reads.

Times apply in ``app.timezone`` from ``config.yaml`` — if the entry is
missing, in the server's time zone.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import tzlocal

from app import sprachwahl
from app.agenten import Agent

log = logging.getLogger(__name__)

PRUEF_ABSTAND_SEKUNDEN = 30


def letzter_termin(zeitplan: str, jetzt: datetime) -> datetime:
    """The most recent past due time of a daily ``HH:MM`` — today, or
    yesterday if today's time has not been reached yet.

    The firing loop reads its schedules through ``app/terminplan.py`` now,
    which knows all three shapes and answers this same question for the daily
    one identically. This plain form stays as the reference the daily case is
    measured against."""
    stunde, minute = (int(teil) for teil in zeitplan.split(":"))
    termin = jetzt.replace(hour=stunde, minute=minute, second=0, microsecond=0)
    if termin > jetzt:
        termin -= timedelta(days=1)
    return termin


def naechster_termin(zeitplan: str, jetzt: datetime) -> datetime:
    """The next due time from now on — today's, or tomorrow's if today's
    has already passed. The mirror of ``letzter_termin``: that one looks
    back for what should already have fired, this one looks ahead for what
    is about to: how much lead time a due time still has."""
    stunde, minute = (int(teil) for teil in zeitplan.split(":"))
    termin = jetzt.replace(hour=stunde, minute=minute, second=0, microsecond=0)
    if termin < jetzt:
        termin += timedelta(days=1)
    return termin


def als_aware(iso: str) -> datetime:
    """Make timestamps from the database (``jetzt_iso``, UTC) comparable."""
    wert = datetime.fromisoformat(iso)
    return wert if wert.tzinfo else wert.replace(tzinfo=timezone.utc)


async def termin_ausloesen(app, agent: Agent, task: str, *, cronjob_id: str | None = None):
    """Turns one due time into a job for the cron flow
    (app/cronablauf.py). Returns the started ``Auftrag``, or ``None`` if no
    reachable model took it (the caller then leaves the due time unhandled —
    the next pass tries again).

    ``cronjob_id`` is passed through untouched: the entry the due time came
    from. It stays optional because a caller may have no entry to name."""
    from fastapi import HTTPException

    from app.api.abhaengigkeiten import STANDARD_BENUTZER
    from app.api.v1.auftraege import auftrag_anstossen

    config = app.state.config
    try:
        return auftrag_anstossen(
            config=config,
            repositories=app.state.repositories,
            discovery=app.state.discovery,
            generierungen=app.state.generierungen,
            registry=getattr(app.state, "werkzeuge", None),
            agent=agent,
            task=task,
            endpoint_id=None,
            user_id=getattr(app.state, "standard_benutzer", STANDARD_BENUTZER),
            # Nobody's request to read a language from: the one chosen for
            # the interface, as the cron flow's own error notes take it
            # (app/cronablauf.py), so a run and its note speak alike.
            sprache=(
                sprachwahl.interface_language(app.state.repositories, config.app.language)
                or config.app.language
            ),
            cronjob_id=cronjob_id,
        )
    except HTTPException as fehler:
        log.warning(
            "Scheduled run for '%s' not started: %s",
            agent.name,
            fehler.detail,
            extra={"ereignis": "termin_fehlgeschlagen", "agent": agent.name},
        )
        return None


def jetzt_in_zone(name: str | None) -> datetime:
    """Now, in the configured zone — the one clock the cron table is read by.

    The tick below uses it, and so does anything else that has to answer a
    question about due times outside the tick (app/api/v1/cronjobs.py). Two
    clocks would be two answers to "is this due", an hour apart.
    """
    if name:
        return datetime.now(ZoneInfo(name))
    return datetime.now().astimezone()


def zone_name(configured: str | None) -> str:
    """The zone's name as its database gives it — what travels with a
    reading, so that whoever reads it can compute with it.

    With none configured it is the machine's own, as tzlocal names it: on
    the Mac and Linux from ``TZ`` or ``/etc/localtime``, on Windows from the
    registry, translated to the zone database's name — one way for both
    systems, where the former reading of ``TZ`` and ``/etc/localtime`` left
    Windows with no zone at all. The abbreviation the clock itself reports
    (``CEST``) is deliberately NOT what this answers: it is a name that
    cannot be computed with, and every caller here needs a zone an hour from
    now can be worked out in. Where not even the machine names its zone, the
    answer is empty and the caller says so.

    Here rather than beside its callers because the same name is asked for
    three times — by the block in front of a user turn, by the clock tool and
    by the service's own clock in the interface — and three answers would be
    three zones.
    """
    if configured:
        return configured
    try:
        # Read afresh every time, as the former reading of TZ and
        # /etc/localtime was: tzlocal keeps the first name it found, and a
        # zone changed while the program runs — or a TZ set for one test —
        # would otherwise stay unseen until the next start.
        tzlocal.reload_localzone()
        name = tzlocal.get_localzone_name()
    except ZoneInfoNotFoundError:
        return ""
    try:
        ZoneInfo(name)
    except Exception:
        return ""
    return name


class Wecker:
    """The tick: every 30 seconds it asks the cron table what is due."""

    def __init__(self, app) -> None:
        # Only the app is held on to — configuration, repositories and
        # discovery are read fresh from ``app.state`` on every pass, just
        # like the agent files from disk.
        self.app = app
        self._aufgabe: asyncio.Task | None = None
        self._laeuft = False

    def _jetzt(self) -> datetime:
        return jetzt_in_zone(self.app.state.config.app.timezone)

    async def einmal_pruefen(self, jetzt: datetime | None = None) -> None:
        """One pass: everything the cron table has due at this moment.

        Nothing else is checked here. An agent's own ``schedule:`` field was
        the second caller and is retired — a file that still
        carries one is read and logged about, and fires nothing.
        """
        jetzt = jetzt or self._jetzt()

        # Imported here, not at the top — cronablauf in turn imports from
        # this module, and at the top that would be a cycle.
        from app import cronablauf

        await cronablauf.einmal_pruefen(self.app, jetzt)

    # --- Background loop -------------------------------------------------

    async def _schleife(self) -> None:
        while self._laeuft:
            try:
                await self.einmal_pruefen()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - the loop must never die
                log.exception("Tick pass failed")
            try:
                await asyncio.sleep(PRUEF_ABSTAND_SEKUNDEN)
            except asyncio.CancelledError:
                raise

    async def starten(self) -> None:
        if self._aufgabe is not None:
            return
        self._laeuft = True
        # A first pass right away — that is the catching-up after a restart
        # (app/cronablauf.py, rule 1). Guarded like every later pass in the
        # loop below: one broken entry must not take the whole service down
        # on the way up.
        try:
            await self.einmal_pruefen()
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - startup must never die from this
            log.exception("First tick pass failed")
        self._aufgabe = asyncio.create_task(self._schleife(), name="wecker")
        log.info("Tick started")

    async def stoppen(self) -> None:
        self._laeuft = False
        if self._aufgabe is None:
            return
        self._aufgabe.cancel()
        try:
            await self._aufgabe
        except asyncio.CancelledError:
            pass
        finally:
            self._aufgabe = None
