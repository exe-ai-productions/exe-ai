"""The schedules' form and calendar: the third kind, the reminder, which runs
nothing; changing a schedule from the window by the tool's own ``update``;
the calendar, which reads what ran from the history and what is to come from
the rule; and the form's repetitions, stored in the three shapes of today
(app/reminder.py, app/cronablauf.py, app/api/v1/cronjobs.py,
app/schedule_calendar.py, frontend/src/lib/terminform.js).
"""

from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from app import cronablauf, reminder, schedule_calendar
from app.i18n import t
from app.providers import MockProvider, mock_endpunkt
from app.wecker import jetzt_in_zone
from tests.conftest import provider_setzen
from tests.test_auftraege_api import agent_schreiben

MORGEN_13 = datetime.now(timezone.utc).replace(
    hour=13, minute=0, second=0, microsecond=0
) + timedelta(days=1)


def _shown(monkeypatch) -> list[str]:
    shown: list[str] = []
    monkeypatch.setattr(
        cronablauf.cronmeldung, "melden", lambda text, *, erfolgreich, sprache=None: shown.append(text)
    )
    return shown


# --- The reminder: the system's notification, no model ----------------------


def test_a_due_reminder_shows_its_text_and_runs_no_model(config, client, monkeypatch, caplog):
    shown = _shown(monkeypatch)
    answer = client.post(
        "/api/v1/cronjobs",
        json={"zeitplan": "12:00", "task": "Hand in the tax return", "reminder": True},
    )
    assert answer.status_code == 201, answer.text
    assert answer.json()["kind"] == "reminder"

    asyncio.run(client.app.state.wecker.einmal_pruefen(jetzt=MORGEN_13))

    assert shown == ["Hand in the tax return"]
    runs = [a for a in client.get("/api/v1/jobs").json() if a["task"] == "Hand in the tax return"]
    # One row for the history, ended at once — nothing ran on a model.
    assert [(r["agent"], r["state"]) for r in runs] == [(reminder.REMINDER_AGENT, "fertig")]
    assert any("no model" in r.getMessage() for r in caplog.records)


def test_a_reminder_speaks_even_on_a_silent_delivery(config, client, monkeypatch):
    """``deliver = 'log'`` is every entry's default — a reminder that obeyed
    it would never say anything."""
    shown = _shown(monkeypatch)
    entry = client.app.state.repositories.cronjobs.erstellen(
        agent=reminder.REMINDER_AGENT, task="Call back", zeitplan="12:00", herkunft="chat"
    )
    assert entry.deliver == "log"

    asyncio.run(client.app.state.wecker.einmal_pruefen(jetzt=MORGEN_13))

    assert shown == ["Call back"]


def test_an_agent_schedule_still_runs_its_agent(config, client, monkeypatch):
    """Silence probe: an agent's schedule runs on the model as before, and
    on the silent default it shows nothing."""
    shown = _shown(monkeypatch)
    agent_schreiben(config)
    provider_setzen(client, MockProvider(mock_endpunkt("test")))
    client.app.state.repositories.cronjobs.erstellen(
        agent="recherche", task="Look it up", zeitplan="12:00", herkunft="chat"
    )

    asyncio.run(client.app.state.wecker.einmal_pruefen(jetzt=MORGEN_13))

    runs = [a for a in client.get("/api/v1/jobs").json() if a["task"] == "Look it up"]
    assert [r["agent"] for r in runs] == ["recherche"]
    assert shown == []


def test_a_reminder_started_by_hand_shows_at_once(client, monkeypatch):
    shown = _shown(monkeypatch)
    created = client.post(
        "/api/v1/cronjobs",
        json={"zeitplan": "12:00", "task": "Stretch", "reminder": True},
    ).json()

    answer = client.post(f"/api/v1/cronjobs/{created['id']}/run")

    assert answer.status_code == 200, answer.text
    assert shown == ["Stretch"]


@pytest.mark.parametrize(
    "extra",
    [{"agent": "recherche"}, {"skript": "backup.sh"}, {"ziel": "a mail from Mia"}],
)
def test_a_reminder_takes_nothing_that_would_run(config, client, extra):
    agent_schreiben(config)
    answer = client.post(
        "/api/v1/cronjobs",
        json={"zeitplan": "12:00", "task": "Stretch", "reminder": True, **extra},
        headers={"Accept-Language": "en"},
    )
    assert answer.status_code == 400
    assert answer.json()["detail"] == t("cronjob_refusal.reminder_alone", "en")


# --- Changing a schedule from the window -------------------------------------


def test_a_change_touches_only_the_fields_sent(config, client):
    agent_schreiben(config)
    first = client.post("/api/v1/cronjobs", json={"zeitplan": "08:00", "task": "One"}).json()
    other = client.post("/api/v1/cronjobs", json={"zeitplan": "08:00", "task": "Two"}).json()

    answer = client.patch(f"/api/v1/cronjobs/{first['id']}", json={"zeitplan": "09:30"})

    assert answer.status_code == 200, answer.text
    changed = answer.json()
    assert (changed["zeitplan"], changed["task"], changed["agent"]) == ("09:30", "One", first["agent"])
    rows = {row["id"]: row for row in client.get("/api/v1/cronjobs").json()}
    # Silence probe: the other schedule is exactly as it was.
    assert rows[other["id"]]["zeitplan"] == "08:00"
    assert rows[other["id"]]["updated_at"] == other["updated_at"]


def test_a_change_is_the_tools_update(client, monkeypatch):
    """The window changes a schedule the way a chat does: through the
    tool's own ``update``, with only the fields it sent."""
    from app.tools import cronjob

    calls: list[dict] = []
    real = cronjob.ausfuehren

    async def watch(argumente, *args, **kwargs):
        calls.append(dict(argumente))
        return await real(argumente, *args, **kwargs)

    monkeypatch.setattr(cronjob, "ausfuehren", watch)
    created = client.post(
        "/api/v1/cronjobs", json={"zeitplan": "08:00", "task": "Water", "reminder": True}
    ).json()
    calls.clear()

    client.patch(f"/api/v1/cronjobs/{created['id']}", json={"task": "Water the plants"})

    assert calls == [{"action": "update", "id": created["id"], "task": "Water the plants"}]


def test_a_change_keeps_the_kind(config, client):
    agent_schreiben(config)
    created = client.post(
        "/api/v1/cronjobs", json={"zeitplan": "08:00", "task": "Water", "reminder": True}
    ).json()

    answer = client.patch(
        f"/api/v1/cronjobs/{created['id']}",
        json={"agent": "recherche"},
        headers={"Accept-Language": "de"},
    )

    assert answer.status_code == 400
    assert answer.json()["detail"] == t("cronjob_refusal.reminder_alone", "de")


def test_a_change_to_an_unknown_schedule_is_not_found(client):
    answer = client.patch("/api/v1/cronjobs/phantom", json={"zeitplan": "09:00"})
    assert answer.status_code == 404


def test_turning_a_one_off_into_a_daily_one_drops_its_day(client):
    created = client.post(
        "/api/v1/cronjobs",
        json={"zeitplan": "08:00", "task": "Water", "reminder": True, "einmalig": True, "datum": "2099-01-01"},
    ).json()

    changed = client.patch(f"/api/v1/cronjobs/{created['id']}", json={"einmalig": False}).json()

    assert (changed["einmalig"], changed["datum"], changed["zeitplan"]) == (False, None, "08:00")


# --- The calendar -------------------------------------------------------------


def _at(config, day: date, hour: int, minute: int = 0) -> datetime:
    zone = jetzt_in_zone(config.app.timezone).tzinfo
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=zone)


def _ran(
    repositories, entry_id: str, moment: datetime, task: str = "Look", zustand: str = "fertig"
) -> None:
    run = repositories.auftraege.erstellen(
        user_id="standard", agent="recherche", auftrag=task, zustand=zustand, cronjob_id=entry_id
    )
    repositories.auftraege.verbindung.execute(
        "UPDATE auftraege SET created_at = ? WHERE id = ?",
        (moment.astimezone(timezone.utc).isoformat(timespec="microseconds"), run.id),
    )


def test_a_day_shows_what_ran_and_what_is_planned(config, client, monkeypatch):
    """Today at noon: the three runs of the morning come from the history,
    the rest of the day from the rule — one row with a count, not fifty."""
    repositories = client.app.state.repositories
    day = date(2026, 9, 28)
    noon = _at(config, day, 12)
    monkeypatch.setattr(schedule_calendar, "jetzt_in_zone", lambda zone: noon)
    often = repositories.cronjobs.erstellen(
        agent="recherche", task="Look", zeitplan="*/15 * * * *", herkunft="chat"
    )
    for clock in (10, 10.25, 10.5):
        _ran(repositories, often.id, _at(config, day, int(clock), int(clock % 1 * 60)))

    rows = schedule_calendar.days(config, repositories, day, day)[day.isoformat()]

    assert len(rows) == 1
    row = rows[0]
    # 12:00 to midnight every fifteen minutes is 48, and 3 already ran.
    assert (row["cronjob_id"], row["ran"], row["planned"], row["count"]) == (often.id, 3, 48, 51)
    assert row["first"] == "10:00"


def test_a_row_carries_the_state_of_its_latest_run(config, client, monkeypatch):
    """The day's list shows one dot per schedule: the latest run decides it,
    and a schedule that has not run yet has no state at all."""
    repositories = client.app.state.repositories
    day = date(2026, 9, 28)
    monkeypatch.setattr(schedule_calendar, "jetzt_in_zone", lambda zone: _at(config, day, 12))
    often = repositories.cronjobs.erstellen(
        agent="recherche", task="Look", zeitplan="*/30 * * * *", herkunft="chat"
    )
    later = repositories.cronjobs.erstellen(
        agent="recherche", task="Evening", zeitplan="18:00", herkunft="chat"
    )
    _ran(repositories, often.id, _at(config, day, 9), zustand="fertig")
    _ran(repositories, often.id, _at(config, day, 10), zustand="gescheitert")

    rows = {
        row["cronjob_id"]: row
        for row in schedule_calendar.days(config, repositories, day, day)[day.isoformat()]
    }
    assert rows[often.id]["state"] == "gescheitert"
    assert rows[later.id]["state"] == ""

    # And the route hands it on rather than dropping it on the way out.
    answer = client.get("/api/v1/cronjobs/calendar", params={"first": day, "last": day}).json()
    served = {row["cronjob_id"]: row for row in answer[day.isoformat()]}
    assert served[often.id]["state"] == "gescheitert"


def test_a_past_day_shows_only_what_ran_and_a_coming_day_only_the_plan(config, client, monkeypatch):
    repositories = client.app.state.repositories
    day = date(2026, 9, 28)
    monkeypatch.setattr(schedule_calendar, "jetzt_in_zone", lambda zone: _at(config, day, 12))
    daily = repositories.cronjobs.erstellen(
        agent="recherche", task="Morning", zeitplan="08:00", herkunft="chat"
    )
    yesterday, tomorrow = day - timedelta(days=1), day + timedelta(days=1)

    calendar = schedule_calendar.days(config, repositories, yesterday, tomorrow)

    # Nothing ran yesterday, so yesterday is empty — a plan is no history.
    assert calendar[yesterday.isoformat()] == []
    # Today's 08:00 is behind noon and did not run: not planned any more.
    assert calendar[day.isoformat()] == []
    (row,) = calendar[tomorrow.isoformat()]
    assert (row["cronjob_id"], row["first"], row["count"], row["planned"], row["ran"]) == (
        daily.id, "08:00", 1, 1, 0,
    )


def test_a_deleted_schedule_keeps_its_days(config, client, monkeypatch):
    repositories = client.app.state.repositories
    day = date(2026, 9, 28)
    monkeypatch.setattr(schedule_calendar, "jetzt_in_zone", lambda zone: _at(config, day, 12))
    gone = repositories.cronjobs.erstellen(
        agent="recherche", task="Old", zeitplan="09:00", herkunft="chat"
    )
    _ran(repositories, gone.id, _at(config, day, 9), task="Old")
    repositories.cronjobs.loeschen(gone.id)

    (row,) = schedule_calendar.days(config, repositories, day, day)[day.isoformat()]

    assert (row["cronjob_id"], row["task"], row["ran"], row["aktiv"]) == (None, "Old", 1, False)


def test_a_switched_off_schedule_keeps_its_days_with_nothing_planned(config, client, monkeypatch):
    repositories = client.app.state.repositories
    day = date(2026, 9, 28)
    monkeypatch.setattr(schedule_calendar, "jetzt_in_zone", lambda zone: _at(config, day, 12))
    paused = repositories.cronjobs.erstellen(
        agent="recherche", task="Paused", zeitplan="18:00", herkunft="chat"
    )
    repositories.cronjobs.aktiv_setzen(paused.id, False)

    (row,) = schedule_calendar.days(config, repositories, day, day)[day.isoformat()]

    assert (row["aktiv"], row["planned"], row["count"]) == (False, 0, 1)


def test_a_one_off_falls_on_its_day_only(config, client, monkeypatch):
    repositories = client.app.state.repositories
    day = date(2026, 9, 28)
    monkeypatch.setattr(schedule_calendar, "jetzt_in_zone", lambda zone: _at(config, day, 12))
    dated = repositories.cronjobs.erstellen(
        agent=reminder.REMINDER_AGENT, task="Tax", zeitplan="09:00", herkunft="chat",
        einmalig=True, datum="2026-09-30",
    )

    calendar = schedule_calendar.days(config, repositories, day, date(2026, 10, 31))

    days_with_it = [key for key, rows in calendar.items() if rows]
    assert days_with_it == ["2026-09-30"]
    assert calendar["2026-09-30"][0]["kind"] == "reminder"
    assert calendar["2026-09-30"][0]["cronjob_id"] == dated.id


def test_an_unreadable_schedule_stands_on_today(config, client, monkeypatch):
    """The tick skips it; the calendar must not lose it, or nobody could
    open, switch off or remove it any more."""
    repositories = client.app.state.repositories
    day = date(2026, 9, 28)
    monkeypatch.setattr(schedule_calendar, "jetzt_in_zone", lambda zone: _at(config, day, 12))
    broken = repositories.cronjobs.erstellen(
        agent="recherche", task="Broken", zeitplan="12:00", herkunft="chat"
    )
    repositories.cronjobs.verbindung.execute(
        "UPDATE cronjobs SET zeitplan = '0 25 * * *' WHERE id = ?", (broken.id,)
    )

    calendar = schedule_calendar.days(config, repositories, day, day + timedelta(days=1))

    (row,) = calendar[day.isoformat()]
    assert (row["cronjob_id"], row["count"], row["planned"]) == (broken.id, 0, 0)
    assert calendar[(day + timedelta(days=1)).isoformat()] == []


def test_a_deleted_scripts_days_name_the_script(config, client, monkeypatch):
    from app import skriptlauf

    repositories = client.app.state.repositories
    day = date(2026, 9, 28)
    monkeypatch.setattr(schedule_calendar, "jetzt_in_zone", lambda zone: _at(config, day, 12))
    run = repositories.auftraege.erstellen(
        user_id="standard", agent=skriptlauf.SKRIPT_AGENT, auftrag="backup.sh",
        zustand="fertig", cronjob_id="gone-for-good",
    )
    repositories.auftraege.verbindung.execute(
        "UPDATE auftraege SET created_at = ? WHERE id = ?",
        (_at(config, day, 3).astimezone(timezone.utc).isoformat(timespec="microseconds"), run.id),
    )

    (row,) = schedule_calendar.days(config, repositories, day, day)[day.isoformat()]

    assert (row["kind"], row["skript"], row["cronjob_id"]) == ("script", "backup.sh", None)


def test_a_day_before_the_clock_change_keeps_its_hour(config, client, monkeypatch):
    """With no zone configured the machine's own is read by name. In
    November the offset is +01:00; a run that fired at 08:00 on a summer day
    (06:00 UTC) still stands at 08:00 on that day — not at 07:00, as a day
    cut with today's offset would put it."""
    repositories = client.app.state.repositories
    config.app.timezone = None
    monkeypatch.setenv("TZ", "Europe/Berlin")
    winter_now = datetime(2026, 11, 2, 12, 0, tzinfo=timezone(timedelta(hours=1)))
    monkeypatch.setattr(schedule_calendar, "jetzt_in_zone", lambda zone: winter_now)
    daily = repositories.cronjobs.erstellen(
        agent="recherche", task="Morning", zeitplan="08:00", herkunft="chat"
    )
    summer_day = date(2026, 9, 28)
    _ran(repositories, daily.id, datetime(2026, 9, 28, 6, 0, tzinfo=timezone.utc), task="Morning")

    (row,) = schedule_calendar.days(config, repositories, summer_day, summer_day)[summer_day.isoformat()]

    assert (row["first"], row["ran"]) == ("08:00", 1)


def test_a_reminders_runs_say_what_they_are(client, monkeypatch):
    _shown(monkeypatch)
    created = client.post(
        "/api/v1/cronjobs", json={"zeitplan": "12:00", "task": "Stretch", "reminder": True}
    ).json()
    client.post(f"/api/v1/cronjobs/{created['id']}/run")

    runs = [r for r in client.get("/api/v1/cronjobs/runs/all").json() if r["cronjob_id"] == created["id"]]

    assert [r["kind"] for r in runs] == ["reminder"]


def test_the_calendar_route_answers_per_day(client):
    answer = client.get("/api/v1/cronjobs/calendar", params={"first": "2026-09-01", "last": "2026-09-03"})
    assert answer.status_code == 200, answer.text
    assert list(answer.json()) == ["2026-09-01", "2026-09-02", "2026-09-03"]


def test_a_daily_time_reads_as_it_was(client):
    """Silence probe: a schedule stored as 'HH:MM' before the form existed
    lists unchanged, as an agent's schedule."""
    repositories = client.app.state.repositories
    old = repositories.cronjobs.erstellen(
        agent="recherche", task="Morning", zeitplan="07:45", herkunft="chat"
    )
    (row,) = [r for r in client.get("/api/v1/cronjobs").json() if r["id"] == old.id]
    assert (row["zeitplan"], row["kind"], row["einmalig"], row["datum"]) == ("07:45", "agent", False, None)


# --- The line under a typed cron expression ----------------------------------


def test_the_preview_names_the_next_runs(client):
    answer = client.get("/api/v1/cronjobs/preview", params={"zeitplan": "*/15 * * * *"})
    assert answer.status_code == 200, answer.text
    moments = [datetime.fromisoformat(m) for m in answer.json()]
    assert len(moments) == 3
    assert {b - a for a, b in zip(moments, moments[1:], strict=False)} == {timedelta(minutes=15)}


def test_the_preview_refuses_what_cannot_be_read(client):
    answer = client.get(
        "/api/v1/cronjobs/preview", params={"zeitplan": "whenever"}, headers={"Accept-Language": "en"}
    )
    assert answer.status_code == 400
    assert answer.json()["detail"] == t("cronjob_refusal.time_unreadable", "en")


# --- The form's repetitions, in the three shapes of today --------------------

FRONTEND = Path(__file__).resolve().parent.parent / "frontend"

DRIVER = """
const m = await import(%r)
const forms = [
  { repeat: 'once', time: '09:00', day: '2026-09-30' },
  { repeat: 'daily', time: '08:15' },
  { repeat: 'weekly', time: '07:30', weekdays: [0, 2, 6] },
  { repeat: 'monthly', time: '18:05', monthDay: 15 },
  { repeat: 'custom', cron: ' */15 * * * * ' },
]
const stored = forms.map((form) => m.storedFromForm(form))
const back = [
  { zeitplan: '08:15' },
  { zeitplan: '09:00', einmalig: true, datum: '2026-09-30' },
  { zeitplan: '2026-10-02T09:30', einmalig: true },
  { zeitplan: '30 7 * * 0,1,3' },
  { zeitplan: '5 18 15 * *' },
  { zeitplan: '0 8 * * 1-5' },
].map((entry) => m.formFromEntry(entry, '2026-09-27'))
const moment = { zeitplan: '2026-10-02T09:30', einmalig: true, datum: null }
const dated = { zeitplan: '09:00', einmalig: true, datum: '2026-09-30' }
const open = (entry) => m.formFromEntry(entry, '2026-09-27')
const changed = [
  m.changedSchedule(moment, { ...open(moment), time: '10:00' }, '2026-09-27'),
  m.changedSchedule(moment, { ...open(moment), day: '2026-10-03' }, '2026-09-27'),
  m.changedSchedule(dated, open(dated), '2026-09-27'),
  m.changedSchedule(dated, { ...open(dated), repeat: 'daily' }, '2026-09-27'),
  m.changedSchedule({ zeitplan: '08:00' }, { ...open({ zeitplan: '08:00' }), time: '08:30' }, '2026-09-27'),
]
console.log('---REPORT---' + JSON.stringify({ stored, back, changed }))
"""


@pytest.mark.skipif(shutil.which("node") is None, reason="no Node on this machine")
def test_every_repetition_is_stored_in_a_shape_of_today():
    driver = FRONTEND / "schedule-form.check.mjs"
    driver.write_text(DRIVER % (FRONTEND / "src/lib/terminform.js").as_uri(), encoding="utf-8")
    try:
        run = subprocess.run(["node", driver.name], cwd=FRONTEND, capture_output=True, text=True, timeout=60)
    finally:
        driver.unlink(missing_ok=True)
    assert run.returncode == 0, (run.stdout + run.stderr)[-3000:]
    report = json.loads(run.stdout.split("---REPORT---", 1)[1].strip())
    assert report["stored"] == [
        {"zeitplan": "09:00", "einmalig": True, "datum": "2026-09-30"},
        {"zeitplan": "08:15", "einmalig": False, "datum": None},
        # Monday, Wednesday and Sunday: cron counts Sunday as 0.
        {"zeitplan": "30 7 * * 0,1,3", "einmalig": False, "datum": None},
        {"zeitplan": "5 18 15 * *", "einmalig": False, "datum": None},
        {"zeitplan": "*/15 * * * *", "einmalig": False, "datum": None},
    ]
    shapes = [(f["repeat"], f["time"], f["day"], f["weekdays"], f["monthDay"], f["cron"]) for f in report["back"]]
    assert shapes == [
        # Silence probe: a daily time stored before the form reads as daily.
        ("daily", "08:15", "2026-09-27", [6], 27, ""),
        ("once", "09:00", "2026-09-30", [6], 27, ""),
        ("once", "09:30", "2026-10-02", [6], 27, ""),
        ("weekly", "07:30", "2026-09-27", [0, 2, 6], 27, ""),
        ("monthly", "18:05", "2026-09-27", [6], 15, ""),
        # What the form has no choice for opens as it stands.
        ("custom", "", "2026-09-27", [6], 27, "0 8 * * 1-5"),
    ]
    assert report["changed"] == [
        # A one-off stored as one fixed moment keeps its day when only the
        # time changes, and takes a new day when only the day changes.
        {"zeitplan": "10:00", "datum": "2026-10-02"},
        {"zeitplan": "09:30", "datum": "2026-10-03"},
        # Opened and saved untouched: nothing is sent.
        {},
        # One-off to daily: the flag goes, the day goes with it (the tool).
        {"einmalig": False},
        {"zeitplan": "08:30"},
    ]
