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
and ``croniter`` is not — hence the one-second nudge in the cron branch
(``_nudged``).

Everything is computed in the time zone of the ``jetzt`` handed in
(``app.timezone``, see app/wecker.py), so daylight saving is decided by the
zone database rather than by arithmetic here.

A daily time and a cron expression are both read the same way: the cron
expression names WALL-CLOCK times, one after the other, and each wall time is
then turned into the moments it stands for in the zone (``_instants``).
Three cases, all decided by the zone database:

* an ordinary wall time is one moment;
* on the autumn day a wall time of the repeated hour is two moments an hour
  apart, and the schedule comes due twice — a schedule running every quarter
  of an hour runs eight times in that hour, never more than fifteen minutes
  apart;
* on the spring day a wall time of the missing hour is one moment, an hour
  later at the same minute: 02:30 comes due at 03:30. Wall times that land
  on a moment another wall time already names (02:00 and 03:00, or every
  quarter of the missing hour) come due once, not twice.

Moments are compared on the absolute clock. Two datetimes that carry the
same zone object compare by their wall-clock fields and ignore the offset,
which is wrong on exactly the two days this module is about; ``absolute``
is what a caller compares through.

Only reading lives here. Whether a schedule may be stored at all, and what
else has to be true around it, is the tool's business (app/tools/cronjob.py).
"""

from __future__ import annotations

import heapq
import re
from datetime import datetime, timedelta, timezone
from typing import Iterator

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
        "Specify a daily time in 'HH:MM' format, a five-field cron expression, or a timestamp "
        "in 'YYYY-MM-DDTHH:MM' format."
    )


def check_ever_due(zeitplan: str) -> None:
    """Refuses a cron expression that never comes due.

    ``sorte`` only checks the spelling of the five fields, so '0 0 30 2 *' —
    the thirtieth of February — passes it and then finds no date at all when
    looked for. Turned into this module's own refusal rather than left to
    escape as a raw croniter error: the caller is asking whether a schedule
    may be stored, and "never comes due" is an answer to that question, not
    a crash.

    How often a schedule comes due is not asked: five fields have no column
    finer than a minute, so nothing a stored schedule can say is more
    frequent than the check loop's thirty seconds can notice.

    Silent for the two shapes that always come due — a daily time recurs
    every day, an instant is one moment.
    """
    if sorte(zeitplan) != SORTE_CRON:
        return
    # A fixed, arbitrary reference point: whether a date exists does not
    # depend on when one starts looking, and a real "now" would make the
    # outcome depend on the day it ran.
    try:
        croniter(zeitplan, datetime(2000, 1, 1, 0, 0)).get_next(datetime)
    except CroniterBadDateError as fehler:
        raise TerminplanFehler(
            "The specified day never occurs, so the schedule would never run."
        ) from fehler


def absolute(moment: datetime) -> datetime:
    """``moment`` on the absolute clock, for comparing and subtracting.

    Two aware datetimes of one zone compare by their wall-clock fields. That
    answers "which is later" wrongly across the repeated hour of the autumn
    day (02:30 +02:00 and 02:30 +01:00 compare equal) and across the missing
    hour of the spring day. A naive datetime has no offset to ask for and is
    returned as it is."""
    if moment.tzinfo is None:
        return moment
    return moment.astimezone(timezone.utc)


# How far apart two wall times can be and still change places on the absolute
# clock: the shift of a clock change is an hour in most zones and two at the
# most, so three leaves room. A moment is handed out once no wall time that
# is still to come can name an earlier one.
_REORDER_WINDOW = timedelta(hours=3)

_EPOCH_UTC = datetime(1970, 1, 1, tzinfo=timezone.utc)
_EPOCH_NAIVE = datetime(1970, 1, 1)


def _seconds(moment: datetime) -> float:
    """A sortable number for a moment — absolute where it has a zone."""
    if moment.tzinfo is None:
        return (moment - _EPOCH_NAIVE).total_seconds()
    return (moment - _EPOCH_UTC).total_seconds()


def _cron_text(zeitplan: str) -> str:
    """The cron expression behind a daily time or a cron expression: one way
    of walking wall times for both."""
    if sorte(zeitplan) == SORTE_CRON:
        return zeitplan.strip()
    stunde, minute = (int(teil) for teil in zeitplan.strip().split(":"))
    return f"{minute} {stunde} * * *"


def _instants(wall: datetime, zone) -> list[datetime]:
    """The moments a wall time stands for in ``zone``, in UTC, earliest first.

    A wall time of the repeated hour is read once with ``fold=0`` and once
    with ``fold=1`` and gives two moments. A wall time of the missing hour is
    read with ``fold=0``, which takes the offset from before the jump, and
    gives the one moment an hour later at the same minute. Without a zone
    the wall time is the moment."""
    if zone is None:
        return [wall]
    first = wall.replace(tzinfo=zone, fold=0).astimezone(timezone.utc)
    second = wall.replace(tzinfo=zone, fold=1).astimezone(timezone.utc)
    # In the missing hour the later reading lands BEFORE the earlier one.
    return [first] if second <= first else [first, second]


def _wall_times(cron: str, start: datetime, *, forward: bool) -> Iterator[datetime]:
    """The wall times of a cron expression from ``start`` on, as ``croniter``
    walks them on a clock without a zone, until it has no further one."""
    walk = croniter(cron, start)
    step = walk.get_next if forward else walk.get_prev
    while True:
        try:
            yield step(datetime)
        except CroniterBadDateError:
            return


def _calm(wall: datetime, zone) -> bool:
    """Whether no clock change lies within the reorder window on either side
    of ``wall``. Where none does, the moments of the wall times around it
    stand in the order of the wall times, each wall time names one moment,
    and nothing has to be held back or looked for ahead of time."""
    if zone is None:
        return True
    here = zone.utcoffset(wall)
    return (
        zone.utcoffset(wall - _REORDER_WINDOW) == here
        and zone.utcoffset(wall + _REORDER_WINDOW) == here
    )


def _due_moments(zeitplan: str, jetzt: datetime, *, forward: bool) -> Iterator[datetime]:
    """Due moments of a daily time or a cron expression, each once, going
    away from ``jetzt`` on the absolute clock — later ones when ``forward``,
    earlier ones otherwise, starting with the first one at or beyond it.

    The wall times come from ``croniter`` on a clock without a zone, so no
    clock change can make it skip or repeat one; the zone database turns
    each into its moments (``_instants``). Near a clock change the walk
    starts a window before ``jetzt`` (after it, going back), because a wall
    time just before ``jetzt`` can still name a moment after it: the second
    pass of the repeated hour. There, moments are held back until no wall
    time still to come can name an earlier one, which is also what puts the
    two passes of the repeated hour in order. Away from a clock change none
    of that is needed, and a schedule every minute is not walked for three
    hours to name its next moment."""
    zone = jetzt.tzinfo
    reach = absolute(jetzt)
    wall = jetzt.replace(tzinfo=None, fold=0)
    lead = timedelta(0) if _calm(wall, zone) else _REORDER_WINDOW
    start = wall - lead if forward else wall + lead
    # ``croniter`` leaves out its own starting point.
    start += timedelta(seconds=-1 if forward else 1)
    pending: list[tuple[float, datetime, datetime]] = []
    previous: datetime | None = None

    def released(limit: datetime | None) -> Iterator[datetime]:
        """What may go out: all of it once the walk is over (``limit`` is
        ``None``), else what no later wall time can still come before."""
        nonlocal previous
        while pending:
            held_wall, moment = pending[0][1], pending[0][2]
            if limit is not None and (held_wall > limit if forward else held_wall < limit):
                return
            heapq.heappop(pending)
            if moment != previous:
                previous = moment
                yield moment if zone is None else moment.astimezone(zone)

    for wall_time in _wall_times(_cron_text(zeitplan), start, forward=forward):
        moments = [
            moment
            for moment in _instants(wall_time, zone)
            if ((moment >= reach) if forward else (moment <= reach))
        ]
        if not pending and _calm(wall_time, zone):
            # Nothing held back and no clock change ahead: this wall time's
            # moment goes out as it is.
            for moment in moments:
                if moment != previous:
                    previous = moment
                    yield moment if zone is None else moment.astimezone(zone)
            continue
        for moment in moments:
            key = _seconds(moment)
            heapq.heappush(pending, (key if forward else -key, wall_time, moment))
        yield from released(
            wall_time - _REORDER_WINDOW if forward else wall_time + _REORDER_WINDOW
        )
    yield from released(None)


def upcoming(zeitplan: str, jetzt: datetime) -> Iterator[datetime]:
    """Every due moment at or after ``jetzt``, earliest first, each once — in
    the zone of ``jetzt``. An instant has exactly one, even when it has gone
    by; the other two shapes never end."""
    art = sorte(zeitplan)
    if art == SORTE_ZEITPUNKT:
        yield _zeitpunkt(zeitplan.strip(), jetzt)
        return
    yield from _due_moments(zeitplan, jetzt, forward=True)


def _zeitpunkt(zeitplan: str, jetzt: datetime) -> datetime:
    moment = _zeitpunkt_teile(zeitplan.strip())
    if moment is None:  # pragma: no cover - sorte() has already vouched
        raise TerminplanFehler("Not a valid timestamp")
    zone = jetzt.tzinfo
    if zone is None:
        return moment
    # The same rule as every other wall time: one in the missing hour is the
    # moment an hour later, one in the repeated hour is its first pass.
    return _instants(moment, zone)[0].astimezone(zone)


def letzter_termin(zeitplan: str, jetzt: datetime) -> datetime:
    """The most recent due moment at or before ``jetzt``.

    For an instant this is the instant itself, which — unlike the other two
    shapes — can still lie in the future. Callers have to check for that
    themselves; the alternative would be an empty answer that every caller
    then has to unpack, for the one shape that has exactly one answer.
    """
    if sorte(zeitplan) == SORTE_ZEITPUNKT:
        return _zeitpunkt(zeitplan, jetzt)
    for moment in _due_moments(zeitplan, jetzt, forward=False):
        return moment
    raise TerminplanFehler("The schedule has no earlier due moment.")  # pragma: no cover


def naechster_termin(zeitplan: str, jetzt: datetime) -> datetime:
    """The next due moment at or after ``jetzt`` — the mirror of
    ``letzter_termin``, used to measure how much lead time a due moment
    still has (app/cronablauf.py).

    An instant has exactly one due moment, so both directions name it.
    """
    for moment in upcoming(zeitplan, jetzt):
        return moment
    raise TerminplanFehler("The schedule has no later due moment.")  # pragma: no cover
