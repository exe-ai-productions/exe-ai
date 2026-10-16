"""``/cron``: the scheduled tasks — listed, created field by field the way
the window's mask asks them, run by hand, paused and resumed, changed,
shown with their last runs, and removed.

The service owns the schedules and every rule about them; what is written
here is the walk through the fields and the way the answers are shaped
into what the service takes: a daily time, a cron expression, or one fixed
day with a time. A schedule that none of the first shapes fits reads as a
custom one with its expression.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any

from cli.client import ServiceError
from cli.interfaces import Context, Entry
from cli.render import local_time

# The words behind ``/cron``.
ADD = "add"
RUN = "run"
PAUSE = "pause"
RESUME = "resume"
REMOVE = "remove"
_ONE_OF_THE_NUMBERED = (RUN, PAUSE, RESUME, REMOVE)

# How a schedule is repeated; the five the walk offers.
ONCE = "once"
DAILY = "daily"
WEEKLY = "weekly"
MONTHLY = "monthly"
CUSTOM = "custom"
REPEATS = (ONCE, DAILY, WEEKLY, MONTHLY, CUSTOM)

# The short names of the weekdays, Monday first. They stand in the
# catalogue, so that they follow the language of the client and not the one
# of the computer.
_WEEKDAYS = (
    "cli.weekday_mon",
    "cli.weekday_tue",
    "cli.weekday_wed",
    "cli.weekday_thu",
    "cli.weekday_fri",
    "cli.weekday_sat",
    "cli.weekday_sun",
)

# The kinds an entry has, as the service names them.
AGENT = "agent"
SCRIPT = "script"
REMINDER = "reminder"
KINDS = (AGENT, SCRIPT, REMINDER)

# The marker the service keeps in the agent column where no agent file runs.
_NO_AGENT = "(none)"

_DAILY = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")
_MOMENT = re.compile(r"^(\d{4})-(\d{2})-(\d{2})T([01]\d|2[0-3]):([0-5]\d)$")
_WEEKLY = re.compile(r"^(\d{1,2}) (\d{1,2}) \* \* ([0-6](?:,[0-6])*)$")
_MONTHLY = re.compile(r"^(\d{1,2}) (\d{1,2}) ([1-9]|[12]\d|3[01]) \* \*$")


def run_command(ctx: Context, argument: str) -> None:
    word, _, rest = argument.strip().partition(" ")
    word, rest = word.casefold(), rest.strip()
    if not word:
        _choose(ctx)
    elif word == ADD:
        _add(ctx)
    elif word in _ONE_OF_THE_NUMBERED:
        _numbered(ctx, word, rest, argument.strip())
    else:
        ctx.renderer.error(ctx.texts.t("cli.unknown_choice", name=argument.strip()))


# --- A schedule as a form reads it ------------------------------------------------------


def _pad(number: int) -> str:
    return f"{number:02d}"


def form_from_entry(entry: dict[str, Any], today: str) -> dict[str, Any]:
    """The form's fields for a stored schedule, ``today`` standing in where
    the schedule names no day. What matches none of the three shapes opens
    as a custom one, with the expression as it stands."""
    schedule = str(entry.get("zeitplan") or "").strip()
    form: dict[str, Any] = {
        "repeat": CUSTOM, "time": "", "day": today, "month_day": int(today[8:10]), "cron": schedule,
        # Monday is 0; the day the form opens on stands in until days are picked.
        "weekdays": [date.fromisoformat(today).weekday()],
    }
    if entry.get("einmalig"):
        moment = _MOMENT.match(schedule)
        if moment:
            return {**form, "repeat": ONCE, "time": f"{moment[4]}:{moment[5]}",
                    "day": f"{moment[1]}-{moment[2]}-{moment[3]}", "cron": ""}
        if _DAILY.match(schedule):
            return {**form, "repeat": ONCE, "time": schedule, "day": entry.get("datum") or today, "cron": ""}
    if _DAILY.match(schedule):
        return {**form, "repeat": DAILY, "time": schedule, "cron": ""}
    weekly = _WEEKLY.match(schedule)
    if weekly and int(weekly[1]) < 60 and int(weekly[2]) < 24:
        # Cron counts Sunday as 0, the form counts Monday as 0.
        days = sorted({(int(day) + 6) % 7 for day in weekly[3].split(",")})
        return {**form, "repeat": WEEKLY, "time": f"{_pad(int(weekly[2]))}:{_pad(int(weekly[1]))}",
                "weekdays": days, "cron": ""}
    monthly = _MONTHLY.match(schedule)
    if monthly and int(monthly[1]) < 60 and int(monthly[2]) < 24:
        return {**form, "repeat": MONTHLY, "time": f"{_pad(int(monthly[2]))}:{_pad(int(monthly[1]))}",
                "month_day": int(monthly[3]), "cron": ""}
    return form


def stored_from_form(form: dict[str, Any]) -> dict[str, Any]:
    """What the form stores: the schedule field, the one-off flag and its day."""
    hour, _, minute = str(form.get("time") or "").partition(":")
    if form["repeat"] == ONCE:
        return {"zeitplan": form["time"], "einmalig": True, "datum": form["day"]}
    if form["repeat"] == DAILY:
        return {"zeitplan": form["time"], "einmalig": False, "datum": None}
    if form["repeat"] == WEEKLY:
        days = ",".join(str(day) for day in sorted((chip + 1) % 7 for chip in form["weekdays"]))
        return {"zeitplan": f"{int(minute or 0)} {int(hour or 0)} * * {days}", "einmalig": False, "datum": None}
    if form["repeat"] == MONTHLY:
        schedule = f"{int(minute or 0)} {int(hour or 0)} {form['month_day']} * *"
        return {"zeitplan": schedule, "einmalig": False, "datum": None}
    return {"zeitplan": str(form.get("cron") or "").strip(), "einmalig": False, "datum": None}


def changed_schedule(entry: dict[str, Any], form: dict[str, Any], today: str) -> dict[str, Any]:
    """The schedule fields a change has to send: only what differs from what
    the form opened with. A one-off's time and day travel together."""
    before = stored_from_form(form_from_entry(entry, today))
    after = stored_from_form(form)
    fields: dict[str, Any] = {}
    if after["einmalig"] != before["einmalig"]:
        fields["einmalig"] = after["einmalig"]
    if after["einmalig"] and (
        after["zeitplan"] != before["zeitplan"] or after["datum"] != before["datum"]
    ):
        fields["zeitplan"] = after["zeitplan"]
        fields["datum"] = after["datum"]
    elif after["zeitplan"] != before["zeitplan"]:
        fields["zeitplan"] = after["zeitplan"]
    return fields


# --- The list -------------------------------------------------------------------------------


def _today() -> str:
    return date.today().isoformat()


def _agent_word(ctx: Context, entry: dict[str, Any]) -> str:
    texts = ctx.texts
    kind = entry.get("kind")
    agent = str(entry.get("agent") or "")
    if kind == SCRIPT:
        return texts.t("cronjobs.kind_script")
    if kind == REMINDER:
        return texts.t("cronjobs.kind_reminder")
    if not agent or agent == _NO_AGENT:
        return texts.t("cronjobs.ohne_agent")
    return agent


def _dot(entry: dict[str, Any]) -> str:
    """The colour of a row's state: red after a failed run or where the
    entry cannot start, yellow while it waits for a model, otherwise blue
    when on and quiet when off."""
    if (
        entry.get("letzter_ausgang") == "gescheitert"
        or entry.get("agent_missing")
        or entry.get("agent_broken")
        or entry.get("skript_nicht_startbar")
    ):
        return "red"
    if entry.get("wartet_auf_modell"):
        return "yellow"
    return "blue" if entry.get("aktiv") else "muted"


def _time_of_day(entry: dict[str, Any], form: dict[str, Any]) -> str:
    schedule = str(entry.get("zeitplan") or "").strip()
    return form["time"] or schedule


def _rhythm(ctx: Context, entry: dict[str, Any], form: dict[str, Any]) -> str:
    texts = ctx.texts
    if form["repeat"] == ONCE:
        if entry.get("datum") or "T" in str(entry.get("zeitplan") or ""):
            return texts.t("cronjobs.einmal_am", datum=form["day"])
        return texts.t("cronjobs.once")
    if form["repeat"] == DAILY:
        return texts.t("cronjobs.taeglich")
    if form["repeat"] == WEEKLY:
        return ", ".join(texts.t(_WEEKDAYS[chip]) for chip in form["weekdays"])
    if form["repeat"] == MONTHLY:
        return texts.t("cronjobs.monthly_on", tag=form["month_day"])
    return texts.t("cronjobs.repeat_custom")


def _row(ctx: Context, entry: dict[str, Any]) -> list[tuple[str, str]]:
    form = form_from_entry(entry, _today())
    title = str(entry.get("skript") or entry.get("task") or "")
    state = "cronjobs.aktiv" if entry.get("aktiv") else "cronjobs.inaktiv"
    return [
        ("muted", _rhythm(ctx, entry, form)),
        ("text", _time_of_day(entry, form)),
        ("text", _agent_word(ctx, entry)),
        ("text", " ".join(title.split())),
        (_dot(entry), ctx.texts.t(state)),
    ]


def _line(ctx: Context, entry: dict[str, Any]) -> str:
    return "  ".join(text for _, text in _row(ctx, entry) if text)


def _listed(ctx: Context) -> list[dict[str, Any]]:
    found = ctx.client.get("/cronjobs")
    return [entry for entry in found if isinstance(entry, dict)] if isinstance(found, list) else []


def _choose(ctx: Context) -> None:
    jobs = _listed(ctx)
    entries = [Entry(cells=[("text", ctx.texts.t("cronjobs.neuer_cronjob"))])]
    entries += [Entry(cells=_row(ctx, entry)) for entry in jobs]
    picked = ctx.asker.choose(entries)
    if picked is None:
        return
    if picked == 0:
        _add(ctx)
    else:
        _entry_menu(ctx, jobs[picked - 1])


# --- A line with a number -----------------------------------------------------------------


def _numbered(ctx: Context, word: str, number: str, argument: str) -> None:
    if not number:
        _choose(ctx)
        return
    jobs = _listed(ctx)
    # Entry 1 of the selection is the new cronjob; the entries count on from 2.
    if not (number.isdecimal() and 2 <= int(number) <= len(jobs) + 1):
        ctx.renderer.error(ctx.texts.t("cli.unknown_choice", name=argument))
        return
    entry = jobs[int(number) - 2]
    if word == RUN:
        _run(ctx, entry)
    elif word == PAUSE:
        _switch(ctx, entry, "pause")
    elif word == RESUME:
        _switch(ctx, entry, "resume")
    else:
        _remove(ctx, entry)


# --- What may be done with one entry --------------------------------------------------------


def _entry_menu(ctx: Context, entry: dict[str, Any]) -> None:
    texts = ctx.texts
    actions: list[tuple[str, str]] = []
    if entry.get("aktiv"):
        actions.append((RUN, texts.t("cronjobs.jetzt_starten")))
    actions.append((PAUSE if entry.get("aktiv") else RESUME,
                    texts.t("cli.cron_pause" if entry.get("aktiv") else "cli.cron_resume")))
    actions += [
        ("change", texts.t("cronjobs.form_change")),
        ("runs", texts.t("cronjobs.letzte_laeufe")),
        (REMOVE, texts.t("cronjobs.entfernen")),
    ]
    picked = ctx.asker.choose([Entry(cells=[("text", label)]) for _, label in actions])
    if picked is None:
        return
    what = actions[picked][0]
    if what == RUN:
        _run(ctx, entry)
    elif what in (PAUSE, RESUME):
        _switch(ctx, entry, what)
    elif what == "change":
        _change(ctx, entry)
    elif what == "runs":
        _runs(ctx, entry)
    else:
        _remove(ctx, entry)


def _run(ctx: Context, entry: dict[str, Any]) -> None:
    try:
        started = ctx.client.post(f"/cronjobs/{entry['id']}/run")
    except ServiceError as error:
        ctx.renderer.error(error.detail)
        return
    said = started.get("notice") if isinstance(started, dict) else None
    ctx.renderer.notice(said or ctx.texts.t("cronjobs.gestartet"))


def _switch(ctx: Context, entry: dict[str, Any], way: str) -> None:
    try:
        answer = ctx.client.post(f"/cronjobs/{entry['id']}/{way}")
    except ServiceError as error:
        ctx.renderer.error(error.detail)
        return
    if isinstance(answer, dict):
        ctx.renderer.notice(_line(ctx, answer))


def _remove(ctx: Context, entry: dict[str, Any]) -> None:
    texts = ctx.texts
    title = str(entry.get("skript") or entry.get("task") or "")
    sure = ctx.asker.choose(
        [Entry(cells=[("text", texts.t("app.ja"))]), Entry(cells=[("text", texts.t("app.nein"))])],
        head=texts.t("cronjobs.loeschen_frage", aufgabe=title),
    )
    if sure != 0:
        return
    try:
        ctx.client.delete(f"/cronjobs/{entry['id']}")
    except ServiceError as error:
        ctx.renderer.error(error.detail)
        return
    ctx.renderer.notice(texts.t("cronjobs.geloescht"))


def _runs(ctx: Context, entry: dict[str, Any]) -> None:
    """The last runs of one entry as lines of the history, newest first,
    with how many are shown of how many there are."""
    texts = ctx.texts
    listed = ctx.client.get("/cronjobs/runs/all")
    runs = [run for run in listed if isinstance(run, dict) and run.get("cronjob_id") == entry.get("id")] \
        if isinstance(listed, list) else []
    runs.sort(key=lambda run: str(run.get("wann") or ""), reverse=True)
    total = max([int(run.get("total") or 0) for run in runs] + [len(runs)])
    ctx.renderer.remark(f"{texts.t('cronjobs.letzte_laeufe')} {len(runs)}/{total}")
    for run in runs:
        status = str(run.get("status") or "")
        word = texts.t(f"jobs.zustand.{status}") if status in ("fertig", "gescheitert") else status
        parts = [local_time(run.get("wann")), word]
        if status == "gescheitert":
            reason = str(run.get("grund") or "")
            parts.append(texts.t(f"jobs.grund.{reason}") if reason else texts.t("jobs.grund.fehler_allgemein"))
        ctx.renderer.remark("  ".join(parts))


# --- The walk through the fields --------------------------------------------------------------


def _ask(ctx: Context, key: str, default: str | None = None) -> str | None:
    """One field: its label as the question, the value that stands there
    already; ``None`` where the question was closed. Nothing typed keeps the
    value that stood."""
    typed = ctx.asker.ask_text(ctx.texts.t(key), default=default)
    if typed is None:
        return None
    return typed.strip()


def _choice(ctx: Context, key: str, options: list[tuple[str, str]], current: str | None = None) -> str | None:
    entries = [
        Entry(cells=[("text", label)], in_use=value == current) for value, label in options
    ]
    picked = ctx.asker.choose(entries, head=ctx.texts.t(key))
    return None if picked is None else options[picked][0]


def _agent_options(ctx: Context) -> list[tuple[str, str]]:
    found = ctx.client.get("/agents")
    names = [str(a.get("name")) for a in found if isinstance(a, dict)] if isinstance(found, list) else []
    return [("", ctx.texts.t("cronjobs.ohne_agent")), *[(name, name) for name in names]]


def _schedule_fields(
    ctx: Context, form: dict[str, Any], *, keep_on_close: bool, had_days: bool = False
) -> dict[str, Any] | None:
    """Asks the fields that belong to the chosen repetition, each with the
    value of ``form`` standing in it. Where a question is closed the walk
    ends with ``None`` while a cronjob is made, and keeps the value that
    stood while one is changed. ``had_days`` says that the days of the form
    are the ones of a schedule that was weekly already: only then do they
    stand where no day was ticked."""
    form = dict(form)
    if form["repeat"] == WEEKLY:
        days = _weekdays(ctx, form["weekdays"])
        if not days and not (keep_on_close and had_days):
            # No day is no schedule: nothing is made, nothing is changed.
            return None
        if days:
            form["weekdays"] = days
    asked: list[tuple[str, str, str]] = []
    if form["repeat"] == ONCE:
        asked.append(("cronjobs.day", "day", form["day"]))
    elif form["repeat"] == MONTHLY:
        asked.append(("cronjobs.day_of_month", "month_day", str(form["month_day"])))
    if form["repeat"] == CUSTOM:
        asked.append(("cronjobs.cron_phrase", "cron", form["cron"]))
    else:
        asked.append(("cronjobs.field_time", "time", form["time"]))
    for key, name, current in asked:
        typed = _ask(ctx, key, current or None)
        if typed is None and not keep_on_close:
            return None
        if not typed:
            continue
        if name == "month_day":
            form[name] = int(typed) if typed.isdecimal() else form[name]
        else:
            form[name] = typed
    return form


def _weekdays(ctx: Context, current: list[int]) -> list[int] | None:
    """The days of a weekly schedule as a checklist, Monday first, with the
    days of ``current`` ticked. ``None`` where the list was closed, and
    where Enter came with no day ticked: nothing is taken then."""
    texts = ctx.texts
    entries = [Entry(cells=[("text", texts.t(key))]) for key in _WEEKDAYS]
    ticked = ctx.asker.check(entries, head=texts.t("cronjobs.repeat_weekly"), checked=current)
    return sorted(ticked) if ticked else None


def _repeat_options(ctx: Context) -> list[tuple[str, str]]:
    texts = ctx.texts
    return [
        (ONCE, texts.t("cronjobs.repeat_once")),
        (DAILY, texts.t("cronjobs.repeat_daily")),
        (WEEKLY, texts.t("cronjobs.repeat_weekly")),
        (MONTHLY, texts.t("cronjobs.repeat_monthly")),
        (CUSTOM, texts.t("cronjobs.repeat_custom")),
    ]


def _add(ctx: Context) -> None:
    texts = ctx.texts
    kind = _choice(
        ctx,
        "cronjobs.field_kind",
        [(AGENT, texts.t("cronjobs.kind_agent")), (SCRIPT, texts.t("cronjobs.kind_script")),
         (REMINDER, texts.t("cronjobs.kind_reminder"))],
    )
    if kind is None:
        return
    body: dict[str, Any] = {}
    if kind == AGENT:
        task = _ask(ctx, "cronjobs.aufgabe")
        if not task:
            return
        agent = _choice(ctx, "cronjobs.kind_agent", _agent_options(ctx))
        if agent is None:
            return
        body["task"] = task
        # No agent is left out, as the window does: the service then takes
        # the entry's own default.
        if agent:
            body["agent"] = agent
    elif kind == SCRIPT:
        script = _ask(ctx, "cronjobs.field_script")
        if not script:
            return
        body.update(skript=script)
    else:
        text = _ask(ctx, "cronjobs.field_text")
        if not text:
            return
        body.update(task=text, reminder=True)
    repeat = _choice(ctx, "cronjobs.field_repeat", _repeat_options(ctx))
    if repeat is None:
        return
    today = _today()
    form = {**form_from_entry({}, today), "repeat": repeat, "cron": ""}
    filled = _schedule_fields(ctx, form, keep_on_close=False)
    if filled is None:
        return
    body.update(stored_from_form(filled))
    try:
        ctx.client.post("/cronjobs", json=body)
    except ServiceError as error:
        ctx.renderer.error(error.detail)
        return
    ctx.renderer.notice(texts.t("cronjobs.angelegt"))


def _change(ctx: Context, entry: dict[str, Any]) -> None:
    """The fields of the mask with what stands there — the kind is not among
    them. Only what was changed goes to the service; nothing changed sends
    nothing."""
    today = _today()
    changes: dict[str, Any] = {}
    kind = entry.get("kind") or AGENT
    if entry.get("skript"):
        kind = SCRIPT
    if kind == AGENT:
        task = _ask(ctx, "cronjobs.aufgabe", str(entry.get("task") or "") or None)
        if task and task != entry.get("task"):
            changes["task"] = task
        options = _agent_options(ctx)
        current = str(entry.get("agent") or "")
        current = "" if current == _NO_AGENT else current
        agent = _choice(ctx, "cronjobs.kind_agent", options, current)
        if agent is not None and agent != current:
            changes["agent"] = agent
    elif kind == SCRIPT:
        script = _ask(ctx, "cronjobs.field_script", str(entry.get("skript") or "") or None)
        if script and script != entry.get("skript"):
            changes["skript"] = script
    else:
        text = _ask(ctx, "cronjobs.field_text", str(entry.get("task") or "") or None)
        if text and text != entry.get("task"):
            changes["task"] = text
    form = form_from_entry(entry, today)
    repeat = _choice(ctx, "cronjobs.field_repeat", _repeat_options(ctx), form["repeat"])
    if repeat is not None:
        form["repeat"] = repeat
    was_weekly = form_from_entry(entry, today)["repeat"] == WEEKLY
    filled = _schedule_fields(ctx, form, keep_on_close=True, had_days=was_weekly)
    if filled is not None:
        changes.update(changed_schedule(entry, filled, today))
    if not changes:
        return
    try:
        ctx.client.patch(f"/cronjobs/{entry['id']}", json=changes)
    except ServiceError as error:
        ctx.renderer.error(error.detail)
        return
    ctx.renderer.notice(ctx.texts.t("cronjobs.changed"))

