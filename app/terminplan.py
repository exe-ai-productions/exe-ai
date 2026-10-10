"""Reading a schedule — one field, three formats.

Until now a schedule was always a daily ``HH:MM``. That is the one thing a
standing reminder can be least often: "look into the mailbox every fifteen
minutes" or "on the first of the month" had no way of being said at all.

This module is the single place that answers what a stored ``zeitplan``
string means. It recognises three shapes and nothing else:

    08:00              a daily time, the whole existing stock
    */15 * * * *       a five-field cron expression
    2026-09-01T10:30   an ISO instant — one fixed moment, never recurring

The shapes cannot be confused for one another: a daily time is the only one
with a colon and no other separator, an ISO instant is the only one with a
``T`` between date and time, and a cron expression is the only one made of
several whitespace-separated fields.

Two questions are asked of a schedule, and both are answered here:

* ``letzter_termin`` — the most recent due moment AT OR BEFORE now. This is
  what the catch-up rule reads (app/cronablauf.py): a due time that has
  passed without a run is one that still wants firing.
* ``naechster_termin`` — the next due moment AT OR AFTER now, the
  forward-looking mirror.

Both are inclusive of ``jetzt`` itself, which the daily form has always been
and ``croniter`` is not — hence the one-second nudge in the cron branch.

Everything is computed in the time zone of the ``jetzt`` handed in
(``app.timezone``, see app/wecker.py), so daylight saving is decided by the
zone database rather than by arithmetic here. On the spring-forward day a
02:00 plan resolves to the 03:00 that actually exists and is caught up
once. On the autumn day the repeated hour is two genuinely different
moments an hour apart, and a 02:00 plan therefore comes due twice —
measured, and exactly what the daily 'HH:MM' form has always done
(tests/test_terminplan.py). Whether that should be collapsed to one is a
question about firing, not about reading, and is left where it stands.

Only reading lives here. Whether a schedule may be stored at all, and what
else has to be true around it, is the tool's business (app/tools/cronjob.py).
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta

from croniter import CroniterBadDateError, croniter

SORTE_TAEGLICH = "taeglich"
SORTE_CRON = "cron"
SORTE_ZEITPUNKT = "zeitpunkt"

# A cron expression is accepted with exactly five fields. ``croniter`` would
# also take a sixth (seconds) and shorthands like ``@hourly``, and both are
# turned down on purpose: the check loop runs every 30 seconds
# (app/wecker.py), so anything finer than a minute could not be honoured,
# and a second spelling of "hourly" buys nothing but a second thing to
# explain.
FELDER_CRON = 5
# The check loop's tick is 30 seconds, so a minute is the hard floor. Five
# fields cannot express anything shorter — the guard below measures it
# anyway rather than trusting that property to stay true.
MINDESTABSTAND_SEKUNDEN = 60
# How many consecutive due times the minimum-gap guard looks at. Enough to
# catch a pattern whose short gap only shows up after the first step.
ABSTAND_PROBEN = 4

_TAEGLICH_MUSTER = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
_ZEITPUNKT_MUSTER = re.compile(r"^(\d{4}-\d{2}-\d{2})T([01]\d|2[0-3]):([0-5]\d)$")


class TerminplanFehler(ValueError):
    """The schedule string is not one this module can read."""


def _zeitpunkt_teile(zeitplan: str) -> datetime | None:
    """The instant this string names, or ``None`` if it does not name one.

    The pattern alone is not enough: it would wave through a thirteenth
    month, and a row stored like that would then throw at reading time,
    inside the check loop, rather than at the moment somebody tried to
    store it. So the date is actually built here."""
    treffer = _ZEITPUNKT_MUSTER.match(zeitplan)
    if treffer is None:
        return None
    try:
        tag = datetime.fromisoformat(treffer.group(1))
    except ValueError:
        return None
    return tag.replace(hour=int(treffer.group(2)), minute=int(treffer.group(3)))


def sorte(zeitplan: str) -> str:
    """Which of the three shapes this string is — or a refusal.

    The order matters only for readability: the three patterns are
    mutually exclusive, so no string can match two of them.
    """
    zeitplan = str(zeitplan or "").strip()
    if _TAEGLICH_MUSTER.match(zeitplan):
        return SORTE_TAEGLICH
    if _zeitpunkt_teile(zeitplan) is not None:
        return SORTE_ZEITPUNKT
    if len(zeitplan.split()) == FELDER_CRON and croniter.is_valid(zeitplan):
        return SORTE_CRON
    raise TerminplanFehler(
        "must be a daily 'HH:MM', a five-field cron expression, "
        "or an instant 'YYYY-MM-DDTHH:MM'"
    )


def abstand_pruefen(zeitplan: str) -> None:
    """Refuses a schedule that would come due more often than the check
    loop can notice. Measured, not assumed: the gaps between the next few
    due times are compared against the tick's floor.

    Silent for the two shapes that cannot be too frequent — a daily time
    recurs once a day, an instant does not recur at all.

    As the module stands, the gap comparison can refuse nothing, and it is
    kept on purpose. ``sorte`` lets a cron expression through with five
    fields only, and five fields have no column finer than a minute, so
    every gap they can produce is a whole number of minutes; measured
    across the valid five-field expressions the smallest one is exactly
    sixty seconds, which the comparison lets pass on purpose. The one
    caller (app/tools/cronjob.py) is the single door every stored schedule
    goes through, the mask included, and it hands over exactly what
    ``sorte`` accepts — so nothing that arrives here today can be too
    frequent.

    What holds that property up is a single number: ``FELDER_CRON``. Raise
    it to six to admit croniter's seconds column — the sixth field named in
    the comment beside it — and '*/10 * * * * *' becomes a storable
    schedule that the 30-second loop would fire once a tick, at a third of
    the rate it names, with nothing anywhere reporting an error. Nothing
    else in this module would object. This comparison is what turns that
    into a refusal at the moment the schedule is written, and it costs five
    croniter steps on a path that runs when an entry is created or changed,
    never when one comes due.

    The ``CroniterBadDateError`` branch below is a different matter and
    does refuse schedules today.
    """
    if sorte(zeitplan) != SORTE_CRON:
        return
    # A fixed, arbitrary reference point: the gaps of a cron expression do
    # not depend on when one starts looking, and a real "now" would make
    # the check's outcome depend on the day it ran.
    lauf = croniter(zeitplan, datetime(2000, 1, 1, 0, 0))
    try:
        vorheriger = lauf.get_next(datetime)
        for _ in range(ABSTAND_PROBEN):
            naechster = lauf.get_next(datetime)
            if (naechster - vorheriger).total_seconds() < MINDESTABSTAND_SEKUNDEN:
                raise TerminplanFehler(
                    "fires more often than once a minute, which the check loop "
                    "cannot notice"
                )
            vorheriger = naechster
    except CroniterBadDateError as fehler:
        # ``is_valid`` only checks the spelling of the five fields, so
        # '0 0 30 2 *' — the thirtieth of February — passes ``sorte`` and
        # then finds no date at all here. Turned into this module's own
        # refusal rather than left to escape as a raw croniter error: the
        # caller is asking whether a schedule may be stored, and "never
        # comes due" is an answer to that question, not a crash.
        raise TerminplanFehler(
            "names a day that never occurs, so it would never come due"
        ) from fehler


def _zeitpunkt(zeitplan: str, jetzt: datetime) -> datetime:
    moment = _zeitpunkt_teile(zeitplan.strip())
    if moment is None:  # pragma: no cover - sorte() has already vouched
        raise TerminplanFehler("not an instant")
    return moment.replace(tzinfo=jetzt.tzinfo)


def letzter_termin(zeitplan: str, jetzt: datetime) -> datetime:
    """The most recent due moment at or before ``jetzt``.

    For an instant this is the instant itself, which — unlike the other two
    shapes — can still lie in the future. Callers have to check for that
    themselves; the alternative would be an empty answer that every caller
    then has to unpack, for the one shape that has exactly one answer.
    """
    art = sorte(zeitplan)
    zeitplan = zeitplan.strip()
    if art == SORTE_ZEITPUNKT:
        return _zeitpunkt(zeitplan, jetzt)
    if art == SORTE_CRON:
        # ``get_prev`` is exclusive of its starting point; a due moment that
        # is exactly now is a due moment that has come.
        return croniter(zeitplan, jetzt + timedelta(seconds=1)).get_prev(datetime)
    stunde, minute = (int(teil) for teil in zeitplan.split(":"))
    termin = jetzt.replace(hour=stunde, minute=minute, second=0, microsecond=0)
    if termin > jetzt:
        termin -= timedelta(days=1)
    return termin


def naechster_termin(zeitplan: str, jetzt: datetime) -> datetime:
    """The next due moment at or after ``jetzt`` — the mirror of
    ``letzter_termin``, used to measure how much lead time a due moment
    still has (app/cronablauf.py).

    An instant has exactly one due moment, so both directions name it.
    """
    art = sorte(zeitplan)
    zeitplan = zeitplan.strip()
    if art == SORTE_ZEITPUNKT:
        return _zeitpunkt(zeitplan, jetzt)
    if art == SORTE_CRON:
        return croniter(zeitplan, jetzt - timedelta(seconds=1)).get_next(datetime)
    stunde, minute = (int(teil) for teil in zeitplan.split(":"))
    termin = jetzt.replace(hour=stunde, minute=minute, second=0, microsecond=0)
    if termin < jetzt:
        termin += timedelta(days=1)
    return termin
