"""The calendar of the schedules: what was, and what will be, per day.

A calendar looks back at what happened and ahead at what is planned. So a day
is read from two sources, never one: the runs the history holds for the part
of the day that has gone by, and the schedule's own rule for the part still
to come. A past day shows only what really ran; a future day only the plan;
today both, split at this very moment. A switched-off schedule still shows
on the days its rule names, marked off, with nothing planned.

One row per schedule and day, however often it comes due: a schedule every
fifteen minutes is one row with a count, not ninety-six (``count``, ``ran``,
``planned``). ``state`` is the state of the latest run that day, empty while
nothing has run — a day's list shows in one dot whether it went well. A schedule that has been deleted still has its past days — its
runs are history — and appears there under the task its runs carried.

Everything is read on the clock the service fires schedules by — the
configured zone, or the machine's own by name, so a day next month is cut
where that day really begins, summer time or not.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from itertools import takewhile
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

from app import cronablauf, terminplan
from app.api.v1.meta import service_zone
from app.reminder import KIND_SCRIPT, kind_of
from app.wecker import als_aware, jetzt_in_zone

if TYPE_CHECKING:
    from app.config import Config
    from app.db import Repositories

def _moments(entry, now: datetime, start: datetime, end: datetime) -> list[datetime]:
    """The due moments of an entry in ``[start, end)`` by its rule.

    A one-off names one moment: its fixed day and time, or — without a day —
    the next occurrence of its time from now, the one the tick will fire.
    Any other rule is walked once, moment after moment, up to the end of the
    span: a schedule every minute has forty thousand moments in a month.
    Raises ``ValueError`` for a schedule that cannot be read.

    The moments come from the module the tick fires by, so a day in the
    calendar shows what the clock will do, clock changes included. They are
    compared on the absolute clock: two moments of one zone compare by their
    wall-clock fields, which loses the repeated hour."""
    first, finish = terminplan.absolute(start), terminplan.absolute(end)
    if entry.einmalig:
        moment = (
            cronablauf._termin_mit_datum(entry, now)
            if entry.datum
            else terminplan.naechster_termin(entry.zeitplan, now)
        )
        return [moment] if first <= terminplan.absolute(moment) < finish else []
    return list(
        takewhile(
            lambda moment: terminplan.absolute(moment) < finish,
            terminplan.upcoming(entry.zeitplan, start),
        )
    )


def days(
    config: "Config", repositories: "Repositories", first: date, last: date
) -> dict[str, list[dict[str, Any]]]:
    """Every day from ``first`` to ``last``, each with its rows, earliest
    moment first. A day with nothing on it is an empty list."""
    name = service_zone(config.app.timezone)
    now = jetzt_in_zone(config.app.timezone)
    zone = ZoneInfo(name) if name else now.tzinfo
    now = now.astimezone(zone)
    begin = datetime(first.year, first.month, first.day, tzinfo=zone)
    finish = datetime(last.year, last.month, last.day, tzinfo=zone) + timedelta(days=1)

    cells: dict[str, dict[str, dict[str, Any]]] = {}

    def cell(day: str, key: str, fields: dict[str, Any]) -> dict[str, Any]:
        per_day = cells.setdefault(day, {})
        if key not in per_day:
            per_day[key] = {
                **fields, "first": "", "count": 0, "ran": 0, "planned": 0, "state": "",
            }
        return per_day[key]

    def note(target: dict[str, Any], moment: datetime) -> None:
        clock = moment.strftime("%H:%M")
        if not target["first"] or clock < target["first"]:
            target["first"] = clock
        target["count"] += 1

    entries = {e.id: e for e in repositories.cronjobs.auflisten()}

    def fields_of(entry) -> dict[str, Any]:
        return {
            "cronjob_id": entry.id,
            "task": entry.task,
            "agent": entry.agent,
            "skript": entry.skript,
            "kind": kind_of(entry.agent, entry.skript),
            "aktiv": bool(entry.aktiv),
        }

    # What ran: the history, up to now.
    for cronjob_id, created_at, agent, task, state in repositories.auftraege.cron_runs_between(
        begin, min(finish, now)
    ):
        moment = als_aware(created_at).astimezone(zone)
        entry = entries.get(cronjob_id)
        if entry:
            fields = fields_of(entry)
        else:
            # Deleted: the run is all there is. A script's run carries the
            # script's name as its task.
            kind = kind_of(agent, None)
            fields = {
                "cronjob_id": None, "task": task, "agent": agent,
                "skript": task if kind == KIND_SCRIPT else None,
                "kind": kind, "aktiv": False,
            }
        target = cell(moment.date().isoformat(), cronjob_id, fields)
        target["ran"] += 1
        # The runs come in order of their start, so the last one wins.
        target["state"] = state
        note(target, moment)

    # What is planned: the rule, from now on. A switched-off entry keeps its
    # days, drawn as off and counted as nothing planned, so it can be found
    # and switched on again where it belongs — except a one-off that has
    # already fired: its day is behind it, in the history.
    start = max(begin, now)
    today = now.date().isoformat()
    show_today = begin <= now < finish
    if start < finish:
        for entry in entries.values():
            if not entry.aktiv and entry.einmalig and entry.zuletzt_ausgeloest:
                continue
            try:
                moments = _moments(entry, now, start, finish)
            except ValueError:
                # A schedule nobody can read has no day of its own. It stands
                # on today, with nothing counted, so it can still be opened,
                # switched off or removed — the tick skips it meanwhile.
                if show_today:
                    cell(today, entry.id, fields_of(entry))
                continue
            for moment in moments:
                target = cell(moment.date().isoformat(), entry.id, fields_of(entry))
                if entry.aktiv:
                    target["planned"] += 1
                note(target, moment)

    result: dict[str, list[dict[str, Any]]] = {}
    day = first
    while day <= last:
        key = day.isoformat()
        result[key] = sorted(cells.get(key, {}).values(), key=lambda c: c["first"])
        day += timedelta(days=1)
    return result
