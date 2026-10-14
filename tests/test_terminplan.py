"""Reading a schedule in three shapes (app/terminplan.py).

Three layers, in this order:

1. The module on its own — which strings it accepts, and what the two
   questions ("most recent due moment", "next due moment") answer.
2. The tool that stores a schedule (app/tools/cronjob.py) — the three shapes
   go in, and the separate ``date`` field stays where it belongs.
3. The firing loop (app/cronablauf.py) — an entry in each shape actually
   starts a job, including the two daylight-saving days, which is the whole
   reason the reading is left to the zone database instead of to arithmetic.

The existing suites stay untouched: tests/test_cronablauf.py keeps proving
that the daily 'HH:MM' stock still fires, tests/test_cronjob_werkzeug.py
that the tool's older rules still hold.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from app import cronablauf, schedule_calendar, terminplan
from app.no_agent import NAME as NO_AGENT
from app.providers import MockProvider, mock_endpunkt
from app.terminplan import TerminplanFehler
from app.tools.cronjob import CronjobVerboten, ausfuehren
from tests.conftest import provider_setzen

BERLIN = ZoneInfo("Europe/Berlin")


# --- 1. The module ---------------------------------------------------------


@pytest.mark.parametrize(
    "zeitplan, erwartet",
    [
        ("08:00", terminplan.SORTE_TAEGLICH),
        ("23:59", terminplan.SORTE_TAEGLICH),
        ("* * * * *", terminplan.SORTE_CRON),
        ("*/15 * * * *", terminplan.SORTE_CRON),
        ("0 9 * * 1-5", terminplan.SORTE_CRON),
        ("0 3 1 * *", terminplan.SORTE_CRON),
        ("2026-09-04T09:00", terminplan.SORTE_ZEITPUNKT),
    ],
)
def test_die_drei_formen_werden_erkannt(zeitplan, erwartet):
    assert terminplan.sorte(zeitplan) == erwartet


@pytest.mark.parametrize(
    "zeitplan",
    [
        "",
        "   ",
        "25:00",
        "8:00",           # unpadded — never what the tool stored
        "irgendwas",
        "* * * *",        # four fields
        "@hourly",        # a shorthand, deliberately not a second spelling
        "2026-09-04 09:00",  # a space instead of the T
        "2026-13-04T09:00",
    ],
)
def test_was_keine_der_drei_formen_ist_wird_abgewiesen(zeitplan):
    with pytest.raises(TerminplanFehler):
        terminplan.sorte(zeitplan)


def test_sechs_felder_werden_abgewiesen():
    """A sixth field is croniter's seconds column — finer than the 30-second
    check loop can ever notice, so it never becomes a stored schedule."""
    with pytest.raises(TerminplanFehler):
        terminplan.sorte("* * * * * *")


def test_minutentakt_ist_erlaubt():
    """Every minute is the finest a five-field expression can say, and the
    check loop notices every minute: nothing is refused for being frequent."""
    terminplan.check_ever_due("* * * * *")


@pytest.mark.parametrize("zeitplan", ["08:00", "2026-09-04T09:00"])
def test_the_check_leaves_the_two_other_shapes_alone(zeitplan):
    terminplan.check_ever_due(zeitplan)


@pytest.mark.parametrize("zeitplan", ["0 0 30 2 *", "0 0 31 4 *"])
def test_ein_tag_den_es_nie_gibt_wird_als_terminplanfehler_abgewiesen(zeitplan):
    """The thirtieth of February, the thirty-first of April. All five fields
    are spelled correctly, so ``is_valid`` says yes and ``sorte`` calls this
    a cron expression; only looking for an actual date shows there is none.

    That has to come back as this module's own refusal. Left as croniter's
    raw error it escaped the tool's check unread and travelled all the way
    to the catch-all in app/api/v1/generierung.py — the model was handed a
    crash where an explanation was due."""
    with pytest.raises(TerminplanFehler, match="never occurs"):
        terminplan.check_ever_due(zeitplan)


def test_taegliche_zeit_liest_sich_wie_bisher():
    jetzt = datetime(2026, 5, 1, 14, 0, tzinfo=BERLIN)
    assert terminplan.letzter_termin("08:00", jetzt) == datetime(
        2026, 5, 1, 8, 0, tzinfo=BERLIN
    )
    assert terminplan.naechster_termin("08:00", jetzt) == datetime(
        2026, 5, 2, 8, 0, tzinfo=BERLIN
    )
    # Today's time not yet reached: the most recent one was yesterday's.
    frueh = datetime(2026, 5, 1, 6, 0, tzinfo=BERLIN)
    assert terminplan.letzter_termin("08:00", frueh) == datetime(
        2026, 4, 30, 8, 0, tzinfo=BERLIN
    )
    assert terminplan.naechster_termin("08:00", frueh) == datetime(
        2026, 5, 1, 8, 0, tzinfo=BERLIN
    )


def test_cron_liest_rueckwaerts_und_vorwaerts():
    jetzt = datetime(2026, 5, 1, 14, 7, tzinfo=BERLIN)
    assert terminplan.letzter_termin("*/15 * * * *", jetzt) == datetime(
        2026, 5, 1, 14, 0, tzinfo=BERLIN
    )
    assert terminplan.naechster_termin("*/15 * * * *", jetzt) == datetime(
        2026, 5, 1, 14, 15, tzinfo=BERLIN
    )


def test_ein_termin_genau_jetzt_gilt_als_gekommen():
    """Both readings include ``jetzt`` itself — the daily form always has,
    and croniter's own get_prev/get_next do not, which is what the
    one-second nudge in the module fixes. Without it a due moment landing
    exactly on a tick would read as an hour old and fire a second time."""
    jetzt = datetime(2026, 5, 1, 14, 0, tzinfo=BERLIN)
    assert terminplan.letzter_termin("0 * * * *", jetzt) == jetzt
    assert terminplan.naechster_termin("0 * * * *", jetzt) == jetzt


def test_zeitpunkt_nennt_in_beide_richtungen_denselben_moment():
    fest = datetime(2026, 9, 4, 9, 0, tzinfo=BERLIN)
    vorher = datetime(2026, 9, 1, 12, 0, tzinfo=BERLIN)
    nachher = datetime(2026, 9, 10, 12, 0, tzinfo=BERLIN)
    for jetzt in (vorher, nachher):
        assert terminplan.letzter_termin("2026-09-04T09:00", jetzt) == fest
        assert terminplan.naechster_termin("2026-09-04T09:00", jetzt) == fest


def test_zeitpunkt_nimmt_die_zone_des_jetzt():
    jetzt = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)
    assert terminplan.letzter_termin("2026-09-04T09:00", jetzt) == datetime(
        2026, 9, 4, 9, 0, tzinfo=timezone.utc
    )


# The repeated hour of 25 October 2026 in Europe/Berlin: 02:00 to 02:59 comes
# round at +02:00 (00:00 to 00:59 UTC) and again at +01:00 (01:00 to 01:59
# UTC). Moments are written in UTC and handed in as Berlin local time, the
# way the running service sees them.


def _berlin(day: int, hour: int, minute: int, second: int = 0) -> datetime:
    return datetime(2026, 10, day, hour, minute, second, tzinfo=timezone.utc).astimezone(BERLIN)


def _utc(day: int, hour: int, minute: int) -> datetime:
    return datetime(2026, 10, day, hour, minute, tzinfo=timezone.utc)


@pytest.mark.parametrize(
    "zeitplan, jetzt, last, upcoming",
    [
        # Inside the second pass: the due moments are the second pass's own.
        ("*/15 * * * *", _berlin(25, 1, 20), _utc(25, 1, 15), _utc(25, 1, 30)),
        # Exactly on a due moment of the second pass — both directions are
        # inclusive of now.
        ("*/15 * * * *", _berlin(25, 1, 0), _utc(25, 1, 0), _utc(25, 1, 0)),
        # The last minutes of the first pass: what comes next is 02:00 of
        # the second pass, not 03:00.
        ("*/15 * * * *", _berlin(25, 0, 50), _utc(25, 0, 45), _utc(25, 1, 0)),
        # 03:00 +01:00, the first moment after the hour: itself, not a
        # moment of the pass that has just ended.
        ("*/15 * * * *", _berlin(25, 2, 0), _utc(25, 2, 0), _utc(25, 2, 0)),
        # A daily time as a cron expression: served in the first pass, it
        # comes due again in the second and then tomorrow.
        ("30 2 * * *", _berlin(25, 0, 40), _utc(25, 0, 30), _utc(25, 1, 30)),
        ("30 2 * * *", _berlin(25, 1, 10), _utc(25, 0, 30), _utc(25, 1, 30)),
        ("30 2 * * *", _berlin(25, 1, 40), _utc(25, 1, 30), _utc(26, 1, 30)),
    ],
)
def test_cron_reads_the_repeated_hour_pass_by_pass(zeitplan, jetzt, last, upcoming):
    """The defect: inside the second pass both directions answered with the
    first pass's moments — an hour in the past, served already."""
    assert terminplan.letzter_termin(zeitplan, jetzt).astimezone(timezone.utc) == last
    assert terminplan.naechster_termin(zeitplan, jetzt).astimezone(timezone.utc) == upcoming


def test_the_last_second_before_the_clock_goes_back_is_still_the_first_pass():
    """02:59:59 +02:00. One second on, the local clock reads 02:00:00 again;
    counted on the local clock instead it read 03:00:00 and the answer was
    02:45 of the second pass — a moment 46 minutes in the future, which the
    loop then fired and stamped, losing the three before it."""
    jetzt = _berlin(25, 0, 59, 59)
    assert terminplan.letzter_termin("*/15 * * * *", jetzt).astimezone(timezone.utc) == _utc(25, 0, 45)
    assert terminplan.naechster_termin("*/15 * * * *", jetzt).astimezone(timezone.utc) == _utc(25, 1, 0)


@pytest.mark.parametrize(
    "zeitplan, upcoming",
    [
        ("*/15 * * * *", datetime(2026, 3, 29, 1, 0, tzinfo=timezone.utc)),
        ("0 3 * * *", datetime(2026, 3, 29, 1, 0, tzinfo=timezone.utc)),
        # A 02:00 plan has no 02:00 on this day; its moment is the 03:00
        # that exists.
        ("0 2 * * *", datetime(2026, 3, 29, 1, 0, tzinfo=timezone.utc)),
    ],
)
def test_the_first_second_after_the_spring_jump_is_due_now(zeitplan, upcoming):
    """29 March 2026, exactly 03:00:00 +02:00 — the first moment after the
    hour that does not exist. The forward reading is inclusive of now, so a
    moment due at 03:00 is the answer. One second back on the local clock
    is a 02:59:59 that never was, and for that one second the answer was a
    whole hour or a whole day further on. The reading the loop fires by
    (``letzter_termin``) answered right before and answers the same."""
    jetzt = datetime(2026, 3, 29, 1, 0, tzinfo=timezone.utc).astimezone(BERLIN)
    assert terminplan.naechster_termin(zeitplan, jetzt).astimezone(timezone.utc) == upcoming
    assert terminplan.letzter_termin(zeitplan, jetzt).astimezone(timezone.utc) == upcoming


@pytest.mark.parametrize("zeitplan", ["*/15 * * * *", "30 2 * * *", "0 9 * * 1-5", "* * * * *"])
def test_away_from_a_clock_change_cron_reads_as_before(zeitplan):
    """Silence probe: on a day without a change, the answer is the one the
    plain local-clock nudge gave — minute by minute over five hours around
    02:00, a week before the autumn day."""
    from croniter import croniter

    jetzt = datetime(2026, 10, 17, 22, 0, 13, tzinfo=timezone.utc)
    for _ in range(5 * 60):
        local = jetzt.astimezone(BERLIN)
        assert terminplan.letzter_termin(zeitplan, local) == croniter(
            zeitplan, local + timedelta(seconds=1)
        ).get_prev(datetime)
        assert terminplan.naechster_termin(zeitplan, local) == croniter(
            zeitplan, local - timedelta(seconds=1)
        ).get_next(datetime)
        jetzt += timedelta(minutes=1)


def test_a_moment_without_a_zone_is_read_as_before():
    """Silence probe: no zone, no clock change to cross — the answers stay
    plain local times without a zone."""
    jetzt = datetime(2026, 5, 1, 14, 7)
    assert terminplan.letzter_termin("*/15 * * * *", jetzt) == datetime(2026, 5, 1, 14, 0)
    assert terminplan.naechster_termin("*/15 * * * *", jetzt) == datetime(2026, 5, 1, 14, 15)
    genau = datetime(2026, 5, 1, 14, 15)
    assert terminplan.letzter_termin("*/15 * * * *", genau) == genau
    assert terminplan.naechster_termin("*/15 * * * *", genau) == genau


# --- 2. The tool -----------------------------------------------------------


async def test_alle_drei_formen_lassen_sich_anlegen(repos, tmp_path):
    for zeit in ("08:00", "*/15 * * * *", "2027-09-04T09:00"):
        await ausfuehren(
            {"action": "create", "time": zeit, "task": "Nachsehen"},
            repos.cronjobs, (tmp_path,), herkunft="chat", agent=None,
        )
    assert sorted(e.zeitplan for e in repos.cronjobs.auflisten()) == [
        "*/15 * * * *", "08:00", "2027-09-04T09:00",
    ]


async def test_ein_ausdruck_unter_einer_minute_wird_abgewiesen(repos, tmp_path):
    with pytest.raises(CronjobVerboten, match="'time'"):
        await ausfuehren(
            {"action": "create", "time": "* * * * * *", "task": "x"},
            repos.cronjobs, (tmp_path,), herkunft="chat", agent=None,
        )
    assert repos.cronjobs.auflisten() == []


async def test_ein_vergangener_zeitpunkt_wird_abgewiesen(repos, tmp_path):
    """The same hole ``date`` in the past closes: an entry whose one moment
    has gone by would sit there confirmed and never fire."""
    with pytest.raises(CronjobVerboten, match="in the past"):
        await ausfuehren(
            {"action": "create", "time": "2020-01-01T09:00", "task": "x"},
            repos.cronjobs, (tmp_path,), herkunft="chat", agent=None,
        )


@pytest.mark.parametrize("zeit", ["0 0 30 2 *", "0 0 31 4 *"])
async def test_ein_tag_den_es_nie_gibt_wird_erklaert_statt_zu_stuerzen(repos, tmp_path, zeit):
    """The tool answers, and it answers about 'time' — no exception type
    from a third-party library reaches the caller."""
    with pytest.raises(CronjobVerboten, match="'time'"):
        await ausfuehren(
            {"action": "create", "time": zeit, "task": "x"},
            repos.cronjobs, (tmp_path,), herkunft="chat", agent=None,
        )
    assert repos.cronjobs.auflisten() == []


@pytest.mark.parametrize("zeit", ["* * * * *", "*/15 * * * *", "08:00", "2099-01-01T08:00"])
async def test_every_shape_the_check_leaves_alone_is_stored(repos, tmp_path, zeit):
    """Silence probe for the one refusal that is left: a schedule that
    comes due, however often, goes through the tool and is stored as
    written."""
    await ausfuehren(
        {"action": "create", "time": zeit, "task": "x"},
        repos.cronjobs, (tmp_path,), herkunft="chat", agent=None,
    )
    assert [e.zeitplan for e in repos.cronjobs.auflisten()] == [zeit]


# Two zones a full day apart, neither of which ever changes its offset:
# Kiritimati is UTC+14, Honolulu UTC-10. One and the same wall clock is
# therefore long past in the one while it is still most of a day away in
# the other — which is what makes the two checks below measure the zone
# rather than the machine the suite happens to run on.
VORN = "Pacific/Kiritimati"
HINTEN = "Pacific/Honolulu"


async def test_ein_zeitpunkt_wird_in_der_app_zone_gemessen(repos, tmp_path):
    """'Already gone by' is a question about ``app.timezone`` — the zone
    the firing loop reads a schedule in — not about the server's clock.

    Measured against the server's, the check turned into its own opposite:
    on a UTC machine with app.timezone Europe/Berlin, an entry half an hour
    past in Berlin was accepted and then sat there confirmed and never
    firing, which is the one thing the check exists to prevent.
   """
    zeit = (datetime.now(ZoneInfo(VORN)) - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M")

    with pytest.raises(CronjobVerboten, match="in the past"):
        await ausfuehren(
            {"action": "create", "time": zeit, "task": "x"},
            repos.cronjobs, (tmp_path,), herkunft="chat", agent=None, zeitzone=VORN,
        )
    assert repos.cronjobs.auflisten() == []

    # The same string, the other zone: still most of a day ahead there.
    await ausfuehren(
        {"action": "create", "time": zeit, "task": "x"},
        repos.cronjobs, (tmp_path,), herkunft="chat", agent=None, zeitzone=HINTEN,
    )
    assert [e.zeitplan for e in repos.cronjobs.auflisten()] == [zeit]


async def test_ein_datum_wird_in_der_app_zone_gemessen(repos, tmp_path):
    """The 'date' field carried the same fault as the instant beside it —
    it is the same comparison against the same wrong clock."""
    moment = datetime.now(ZoneInfo(VORN)) - timedelta(hours=1)
    argumente = {
        "action": "create", "task": "x", "once": True,
        "time": moment.strftime("%H:%M"), "date": moment.date().isoformat(),
    }

    with pytest.raises(CronjobVerboten, match="in the past"):
        await ausfuehren(
            argumente, repos.cronjobs, (tmp_path,),
            herkunft="chat", agent=None, zeitzone=VORN,
        )
    assert repos.cronjobs.auflisten() == []

    await ausfuehren(
        argumente, repos.cronjobs, (tmp_path,),
        herkunft="chat", agent=None, zeitzone=HINTEN,
    )
    assert [e.datum for e in repos.cronjobs.auflisten()] == [argumente["date"]]


@pytest.mark.parametrize("zeit", ["*/15 * * * *", "2027-09-04T09:00"])
async def test_datum_neben_cron_oder_zeitpunkt_wird_abgewiesen(repos, tmp_path, zeit):
    morgen = (datetime.now() + timedelta(days=1)).date().isoformat()
    with pytest.raises(CronjobVerboten, match="daily 'HH:MM'"):
        await ausfuehren(
            {"action": "create", "time": zeit, "task": "x", "once": True, "date": morgen},
            repos.cronjobs, (tmp_path,), herkunft="chat", agent=None,
        )
    assert repos.cronjobs.auflisten() == []


async def test_update_auf_cron_bei_gesetztem_datum_wird_abgewiesen(repos, tmp_path):
    """A pinned day and a cron expression contradict each other — the entry
    keeps both or neither, never a day beside an expression that already
    names its own days."""
    morgen = (datetime.now() + timedelta(days=1)).date().isoformat()
    erstellt = repos.cronjobs.erstellen(
        agent=NO_AGENT, task="x", zeitplan="08:00", herkunft="chat",
        einmalig=True, datum=morgen,
    )
    with pytest.raises(CronjobVerboten, match="daily 'HH:MM'"):
        await ausfuehren(
            {"action": "update", "id": erstellt.id, "time": "*/15 * * * *"},
            repos.cronjobs, (tmp_path,), herkunft="chat", agent=None,
        )
    danach = repos.cronjobs.holen(erstellt.id)
    assert danach.zeitplan == "08:00"
    assert danach.datum == morgen


async def test_update_auf_cron_geht_wenn_das_datum_mit_faellt(repos, tmp_path):
    """Turning 'once' off clears the pinned day (existing behaviour), which
    is exactly what makes the switch to an expression legal in the same
    call."""
    morgen = (datetime.now() + timedelta(days=1)).date().isoformat()
    erstellt = repos.cronjobs.erstellen(
        agent=NO_AGENT, task="x", zeitplan="08:00", herkunft="chat",
        einmalig=True, datum=morgen,
    )
    await ausfuehren(
        {"action": "update", "id": erstellt.id, "time": "*/15 * * * *", "once": False},
        repos.cronjobs, (tmp_path,), herkunft="chat", agent=None,
    )
    danach = repos.cronjobs.holen(erstellt.id)
    assert danach.zeitplan == "*/15 * * * *"
    assert danach.datum is None


async def test_datum_auf_einem_cron_eintrag_wird_abgewiesen(repos, tmp_path):
    morgen = (datetime.now() + timedelta(days=1)).date().isoformat()
    erstellt = repos.cronjobs.erstellen(
        agent=NO_AGENT, task="x", zeitplan="*/15 * * * *", herkunft="chat",
        einmalig=True,
    )
    with pytest.raises(CronjobVerboten, match="daily 'HH:MM'"):
        await ausfuehren(
            {"action": "update", "id": erstellt.id, "date": morgen},
            repos.cronjobs, (tmp_path,), herkunft="chat", agent=None,
        )
    assert repos.cronjobs.holen(erstellt.id).datum is None


async def test_die_antwort_nennt_einen_cron_eintrag_nicht_taeglich(repos, tmp_path):
    antwort = await ausfuehren(
        {"action": "create", "time": "*/15 * * * *", "task": "x"},
        repos.cronjobs, (tmp_path,), herkunft="chat", agent=None,
    )
    assert "daily" not in antwort
    assert "recurring" in antwort


# --- 3. The firing loop ----------------------------------------------------


def agentdatei(ordner: Path, name: str = "recherche") -> None:
    ordner.mkdir(parents=True, exist_ok=True)
    (ordner / f"{name}.md").write_text(
        "---\nmodel: test\n---\n\nPrompt.\n", encoding="utf-8"
    )


def pruefen(client, jetzt: datetime) -> None:
    asyncio.run(client.app.state.wecker.einmal_pruefen(jetzt=jetzt))


def auftraege_von(client, agent: str = "recherche") -> list[dict]:
    return [a for a in client.get("/api/v1/jobs").json() if a["agent"] == agent]


def eintrag_anlegen(client, zeitplan: str, angelegt: datetime, **felder):
    """A cron entry whose ``created_at`` is the baseline the catch-up rule
    measures against — a fresh entry never fires for a due moment older than
    its own creation (app/cronablauf.py)."""
    repositories = client.app.state.repositories
    eintrag = repositories.cronjobs.erstellen(
        agent="recherche", task="Los", zeitplan=zeitplan, herkunft="chat", **felder
    )
    repositories.cronjobs.verbindung.execute(
        "UPDATE cronjobs SET created_at = ? WHERE id = ?",
        (angelegt.isoformat(), eintrag.id),
    )
    return repositories.cronjobs.holen(eintrag.id)


def takte(von: datetime, bis: datetime, sekunden: int = 60):
    """Wall-clock ticks between two absolute moments, expressed in Berlin
    local time — the way the running service sees them. Absolute arithmetic
    on purpose: adding a minute to a local time across a fold would skip or
    repeat the very hour these tests are about."""
    laufend = von
    while laufend <= bis:
        yield laufend.astimezone(BERLIN)
        laufend += timedelta(seconds=sekunden)


def feuerungen(client, eintrag_id: str, von: datetime, bis: datetime) -> list[tuple]:
    """Ticks the loop over the span and returns, for every firing, WHEN it
    happened and WHICH due moment it stood for.

    Counting alone would leave a gap: code that caught a
    02:00 plan up at 01:00 instead of at the 03:00 that actually exists
    would fire exactly once either way and stay green.

    Both moments come back in UTC. A local time inside the repeated hour is
    ambiguous, and an ambiguous time never compares equal to a time in
    another zone however well the two line up (PEP 495) — on the one day
    these tests are about, that would turn every assertion below into a
    riddle about spelling rather than about moments."""
    repo = client.app.state.repositories.cronjobs
    gesehen: list[tuple] = []
    letzter = repo.holen(eintrag_id).zuletzt_ausgeloest
    for jetzt in takte(von, bis):
        pruefen(client, jetzt)
        stempel = repo.holen(eintrag_id).zuletzt_ausgeloest
        if stempel != letzter:
            gesehen.append((
                jetzt.astimezone(timezone.utc),
                datetime.fromisoformat(stempel).astimezone(timezone.utc),
            ))
            letzter = stempel
    return gesehen


def test_minutentakt_feuert_zweimal_im_minutenabstand(config, client):
    """The headline case: '* * * * *' fires once per minute, not once per
    day. Two fires, one minute apart, each stamped with its own due minute."""
    agentdatei(Path(config.app.agenten_verzeichnis))
    provider_setzen(client, MockProvider(mock_endpunkt("test")))
    angelegt = datetime(2026, 5, 1, 12, 0, 30, tzinfo=BERLIN)
    eintrag = eintrag_anlegen(client, "* * * * *", angelegt)
    repositories = client.app.state.repositories

    pruefen(client, datetime(2026, 5, 1, 12, 1, 10, tzinfo=BERLIN))
    assert len(auftraege_von(client)) == 1
    assert repositories.cronjobs.holen(eintrag.id).zuletzt_ausgeloest == datetime(
        2026, 5, 1, 12, 1, tzinfo=BERLIN
    ).isoformat()

    # Same minute again: nothing new — the stamp already covers it.
    pruefen(client, datetime(2026, 5, 1, 12, 1, 40, tzinfo=BERLIN))
    assert len(auftraege_von(client)) == 1

    pruefen(client, datetime(2026, 5, 1, 12, 2, 10, tzinfo=BERLIN))
    assert len(auftraege_von(client)) == 2
    assert repositories.cronjobs.holen(eintrag.id).zuletzt_ausgeloest == datetime(
        2026, 5, 1, 12, 2, tzinfo=BERLIN
    ).isoformat()


def test_viertelstundentakt_feuert_zur_viertelstunde(config, client):
    agentdatei(Path(config.app.agenten_verzeichnis))
    provider_setzen(client, MockProvider(mock_endpunkt("test")))
    eintrag_anlegen(
        client, "*/15 * * * *", datetime(2026, 5, 1, 12, 1, tzinfo=BERLIN)
    )

    pruefen(client, datetime(2026, 5, 1, 12, 10, tzinfo=BERLIN))
    assert auftraege_von(client) == []

    pruefen(client, datetime(2026, 5, 1, 12, 15, 30, tzinfo=BERLIN))
    assert len(auftraege_von(client)) == 1

    pruefen(client, datetime(2026, 5, 1, 12, 25, tzinfo=BERLIN))
    assert len(auftraege_von(client)) == 1

    pruefen(client, datetime(2026, 5, 1, 12, 30, 30, tzinfo=BERLIN))
    assert len(auftraege_von(client)) == 2


def test_ein_zeitpunkt_feuert_genau_einmal(config, client):
    agentdatei(Path(config.app.agenten_verzeichnis))
    provider_setzen(client, MockProvider(mock_endpunkt("test")))
    eintrag_anlegen(
        client, "2026-05-01T12:00", datetime(2026, 4, 30, 9, 0, tzinfo=BERLIN)
    )

    pruefen(client, datetime(2026, 5, 1, 11, 59, tzinfo=BERLIN))
    assert auftraege_von(client) == []

    pruefen(client, datetime(2026, 5, 1, 12, 0, 30, tzinfo=BERLIN))
    assert len(auftraege_von(client)) == 1

    # Days later it is still the same one moment, already handled.
    pruefen(client, datetime(2026, 5, 4, 12, 0, 30, tzinfo=BERLIN))
    assert len(auftraege_von(client)) == 1


def test_ein_alter_hhmm_eintrag_feuert_weiter(config, client):
    """The whole existing stock: nothing about a daily time changed, and the
    module that now reads it has to keep saying the same thing."""
    agentdatei(Path(config.app.agenten_verzeichnis))
    provider_setzen(client, MockProvider(mock_endpunkt("test")))
    eintrag_anlegen(client, "08:00", datetime(2026, 4, 30, 9, 0, tzinfo=BERLIN))

    pruefen(client, datetime(2026, 4, 30, 23, 0, tzinfo=BERLIN))
    assert auftraege_von(client) == []

    pruefen(client, datetime(2026, 5, 1, 8, 0, 30, tzinfo=BERLIN))
    assert len(auftraege_von(client)) == 1

    pruefen(client, datetime(2026, 5, 2, 8, 0, 30, tzinfo=BERLIN))
    assert len(auftraege_von(client)) == 2


# --- The two daylight-saving days ------------------------------------------
#
# Europe/Berlin, a 02:00 plan — the one hour that is missing in spring and
# doubled in autumn. Ticked minute by minute across the whole transition, in
# absolute time, so the loop sees exactly the sequence of local times the
# running service would see.
#
# Both forms of a 02:00 plan are run through the same transition, and the
# point of the pairing is that they come out the same: a cron expression is
# not allowed to behave differently on these two days from the daily time
# the whole existing stock uses.


ZWEI_UHR_PLAENE = ["02:00", "0 2 * * *"]
HALF_PAST_TWO_PLANS = ["02:30", "30 2 * * *"]


@pytest.mark.parametrize("zeitplan", ZWEI_UHR_PLAENE)
def test_fruehjahrsumstellung_feuert_genau_einmal(config, client, zeitplan):
    """29 March 2026: 02:00 does not exist — the clock jumps from 01:59+01:00
    to 03:00+02:00. The 02:00 plan must not be lost; the first tick after the
    jump catches it up, and only once.

    WHEN it is caught up is asserted as well as how often: the one fire has
    to land on the 03:00 that exists, not on the 01:00 before the jump. A
    count alone reads the same either way."""
    agentdatei(Path(config.app.agenten_verzeichnis))
    provider_setzen(client, MockProvider(mock_endpunkt("test")))
    eintrag = eintrag_anlegen(client, zeitplan, datetime(2026, 3, 28, 12, 0, tzinfo=BERLIN))

    von = datetime(2026, 3, 29, 0, 0, tzinfo=timezone.utc)   # 01:00 +01:00
    bis = datetime(2026, 3, 29, 3, 0, tzinfo=timezone.utc)   # 05:00 +02:00
    gefeuert = feuerungen(client, eintrag.id, von, bis)

    assert len(auftraege_von(client)) == 1
    # 01:00 UTC is 03:00 +02:00 — the first local time on the far side of
    # the gap. Both the tick it fires on and the due moment it stands for
    # land there: the daily form spells that moment 02:00 +01:00 and the
    # cron form spells it 03:00 +02:00, which is the same instant twice.
    drei_uhr = datetime(2026, 3, 29, 1, 0, tzinfo=timezone.utc)
    assert gefeuert == [(drei_uhr, drei_uhr)]


@pytest.mark.parametrize("zeitplan", HALF_PAST_TWO_PLANS)
def test_spring_change_a_due_time_inside_the_missing_hour_fires_once_in_both_forms(
    config, client, zeitplan
):
    """29 March 2026, a 02:30 plan — a due time in the middle of the hour
    that does not exist. One run, an hour later at the same minute: 03:30
    +02:00, on its own tick, in both spellings. Neither form loses the run
    and neither fires it twice, and both stamp the time that exists —
    never 02:30 +01:00, which this day does not have."""
    agentdatei(Path(config.app.agenten_verzeichnis))
    provider_setzen(client, MockProvider(mock_endpunkt("test")))
    eintrag = eintrag_anlegen(client, zeitplan, datetime(2026, 3, 28, 12, 0, tzinfo=BERLIN))

    von = datetime(2026, 3, 29, 0, 0, tzinfo=timezone.utc)   # 01:00 +01:00
    bis = datetime(2026, 3, 29, 3, 0, tzinfo=timezone.utc)   # 05:00 +02:00
    gefeuert = feuerungen(client, eintrag.id, von, bis)

    assert len(auftraege_von(client)) == 1
    half_past_three = datetime(2026, 3, 29, 1, 30, tzinfo=timezone.utc)  # 03:30 +02:00
    assert gefeuert == [(half_past_three, half_past_three)]
    # As a clock time with its offset, not as a moment: 02:30 +01:00 is the
    # same moment, and a comparison of moments would not see the difference.
    stamp = client.app.state.repositories.cronjobs.holen(eintrag.id).zuletzt_ausgeloest
    assert stamp.endswith("T03:30:00+02:00")


@pytest.mark.parametrize("zeitplan", HALF_PAST_TWO_PLANS)
def test_spring_change_the_next_run_names_the_time_that_exists(zeitplan):
    """Before the jump the next run of a 02:30 plan is 03:30 +02:00 — in both
    forms, and never a clock time the day does not have."""
    jetzt = datetime(2026, 3, 29, 0, 50, tzinfo=timezone.utc).astimezone(BERLIN)  # 01:50 +01:00

    naechster = terminplan.naechster_termin(zeitplan, jetzt)

    assert naechster.isoformat() == "2026-03-29T03:30:00+02:00"


def test_spring_change_an_instant_inside_the_missing_hour_is_the_moment_an_hour_later():
    jetzt = datetime(2026, 3, 29, 0, 50, tzinfo=timezone.utc).astimezone(BERLIN)

    moment = terminplan.naechster_termin("2026-03-29T02:30", jetzt)

    assert moment.isoformat() == "2026-03-29T03:30:00+02:00"


def test_spring_change_every_quarter_hour_loses_no_run(config, client):
    """'*/15' across the missing hour. MEASURED: a run every fifteen minutes
    of absolute time, straight across the jump — 01:45 +01:00 is followed by
    03:00 +02:00, and no run names a local time between 02:00 and 02:59."""
    agentdatei(Path(config.app.agenten_verzeichnis))
    provider_setzen(client, MockProvider(mock_endpunkt("test")))
    eintrag = eintrag_anlegen(client, "*/15 * * * *", datetime(2026, 3, 28, 12, 0, tzinfo=BERLIN))

    von = datetime(2026, 3, 28, 23, 0, tzinfo=timezone.utc)  # 00:00 +01:00
    bis = datetime(2026, 3, 29, 3, 0, tzinfo=timezone.utc)   # 05:00 +02:00
    gefeuert = feuerungen(client, eintrag.id, von, bis)

    erwartet = [von + n * timedelta(minutes=15) for n in range(17)]
    assert gefeuert == [(moment, moment) for moment in erwartet]
    assert not [tick for tick, _ in gefeuert if tick.astimezone(BERLIN).hour == 2]


@pytest.mark.parametrize("zeitplan", ZWEI_UHR_PLAENE)
def test_herbstumstellung_feuert_wie_der_altbestand(config, client, zeitplan):
    """25 October 2026: 02:00 comes round twice — once at +02:00 and again an
    hour later at +01:00.

    MEASURED, and not what one might assume: both forms fire
    TWICE. The fired-at stamp cannot block the second one, because the two
    are not the same moment — they are an hour apart in absolute time, and
    the stamp of the first is genuinely older than the second. The daily
    'HH:MM' form has always done this; the cron form does the same. Making
    it one fire would be a change to WHEN an entry fires, which is
    deliberately left as it is.

    And both forms notice the second one the moment it comes round again,
    at 01:00 UTC. The cron form used to reach it an hour late, at 03:00
    +01:00: its one-second nudge was taken on the local clock, which drops
    which of the two passes a time belongs to, so the whole second pass
    was read as the first.
    """
    agentdatei(Path(config.app.agenten_verzeichnis))
    provider_setzen(client, MockProvider(mock_endpunkt("test")))
    eintrag = eintrag_anlegen(client, zeitplan, datetime(2026, 10, 24, 12, 0, tzinfo=BERLIN))

    von = datetime(2026, 10, 24, 23, 0, tzinfo=timezone.utc)  # 01:00 +02:00
    bis = datetime(2026, 10, 25, 3, 0, tzinfo=timezone.utc)   # 04:00 +01:00
    gefeuert = feuerungen(client, eintrag.id, von, bis)

    assert len(auftraege_von(client)) == 2
    erste = datetime(2026, 10, 25, 0, 0, tzinfo=timezone.utc)   # 02:00 +02:00
    zweite = datetime(2026, 10, 25, 1, 0, tzinfo=timezone.utc)  # 02:00 +01:00
    # Each fires on the tick of its own due moment, in either spelling.
    assert gefeuert == [(erste, erste), (zweite, zweite)]


@pytest.mark.parametrize("zeitplan", HALF_PAST_TWO_PLANS)
def test_autumn_change_both_forms_fire_at_the_same_moments(config, client, zeitplan):
    """A daily time inside the repeated hour, in both spellings: 02:30 at
    +02:00 and 02:30 at +01:00, each on its own tick. The parameter is the
    only difference between the two runs, so equal lists are equal moments."""
    agentdatei(Path(config.app.agenten_verzeichnis))
    provider_setzen(client, MockProvider(mock_endpunkt("test")))
    eintrag = eintrag_anlegen(client, zeitplan, datetime(2026, 10, 24, 12, 0, tzinfo=BERLIN))

    von = datetime(2026, 10, 24, 23, 0, tzinfo=timezone.utc)
    bis = datetime(2026, 10, 25, 3, 0, tzinfo=timezone.utc)
    gefeuert = feuerungen(client, eintrag.id, von, bis)

    erste = datetime(2026, 10, 25, 0, 30, tzinfo=timezone.utc)   # 02:30 +02:00
    zweite = datetime(2026, 10, 25, 1, 30, tzinfo=timezone.utc)  # 02:30 +01:00
    assert gefeuert == [(erste, erste), (zweite, zweite)]


QUARTER_HOUR = timedelta(minutes=15)


def test_autumn_change_every_quarter_hour_loses_no_run(config, client):
    """'*/15' across the repeated hour: eight runs in it, four per pass, and
    never more than fifteen minutes between two runs. Before, the four of
    the second pass were lost — nothing came due from 02:45 +02:00 until
    03:00 +01:00, 75 minutes."""
    agentdatei(Path(config.app.agenten_verzeichnis))
    provider_setzen(client, MockProvider(mock_endpunkt("test")))
    eintrag = eintrag_anlegen(client, "*/15 * * * *", datetime(2026, 10, 24, 12, 0, tzinfo=BERLIN))

    von = datetime(2026, 10, 24, 23, 0, tzinfo=timezone.utc)  # 01:00 +02:00
    bis = datetime(2026, 10, 25, 3, 0, tzinfo=timezone.utc)   # 04:00 +01:00
    gefeuert = feuerungen(client, eintrag.id, von, bis)

    # Every run on the tick of its own due moment, a quarter of an hour
    # after the one before — across both passes and both edges of the hour.
    erwartet = [von + n * QUARTER_HOUR for n in range(17)]
    assert gefeuert == [(moment, moment) for moment in erwartet]
    repeated_hour = [
        tick for tick, _ in gefeuert
        if tick.astimezone(BERLIN).hour == 2
    ]
    assert len(repeated_hour) == 8


def test_autumn_change_the_daily_form_names_the_second_pass_as_the_next_run():
    """25 October 2026, 02:40 +02:00 — the first pass of the repeated hour is
    over for 02:30, the second is still to come an hour later. The daily form
    used to skip to the next day; the cron form always named the second."""
    jetzt = datetime(2026, 10, 25, 0, 40, tzinfo=timezone.utc).astimezone(BERLIN)

    daily = terminplan.naechster_termin("02:30", jetzt)
    cron = terminplan.naechster_termin("30 2 * * *", jetzt)

    assert daily.isoformat() == cron.isoformat() == "2026-10-25T02:30:00+01:00"


def test_autumn_change_after_the_second_pass_the_next_run_is_tomorrow():
    """Silence probe for the one above: once the second pass is over, the
    next run is the next day's, as on any day."""
    jetzt = datetime(2026, 10, 25, 1, 31, tzinfo=timezone.utc).astimezone(BERLIN)  # 02:31 +01:00

    assert terminplan.naechster_termin("02:30", jetzt).isoformat() == "2026-10-26T02:30:00+01:00"
    assert terminplan.letzter_termin("02:30", jetzt).isoformat() == "2026-10-25T02:30:00+01:00"


@pytest.mark.parametrize("zeitplan", ["*/15 * * * *"])
def test_autumn_change_the_next_run_after_the_first_pass_is_the_second_pass(config, client, zeitplan):
    """02:46 +02:00 is past the last run of the first pass. Compared on the
    wall clock, 02:00 +01:00 looks like the past and the list named no next
    run at all — for fourteen minutes."""
    agentdatei(Path(config.app.agenten_verzeichnis))
    provider_setzen(client, MockProvider(mock_endpunkt("test")))
    eintrag = eintrag_anlegen(client, zeitplan, datetime(2026, 10, 24, 12, 0, tzinfo=BERLIN))
    von = datetime(2026, 10, 24, 23, 0, tzinfo=timezone.utc)
    bis = datetime(2026, 10, 25, 0, 46, tzinfo=timezone.utc)  # 02:46 +02:00
    feuerungen(client, eintrag.id, von, bis)
    jetzt = bis.astimezone(BERLIN)

    stand = client.app.state.repositories.cronjobs.holen(eintrag.id)
    naechster = cronablauf.naechste_faelligkeit(stand, jetzt)

    assert naechster is not None
    assert naechster.isoformat() == "2026-10-25T02:00:00+01:00"


def test_autumn_change_a_missed_moment_of_the_first_pass_is_caught_up(config, client):
    """The service was down from 02:25 +02:00 to 02:10 +01:00. The 02:30
    +02:00 run is an hour and forty minutes old — on the wall clock it read
    as still to come, and was never caught up."""
    agentdatei(Path(config.app.agenten_verzeichnis))
    provider_setzen(client, MockProvider(mock_endpunkt("test")))
    eintrag_anlegen(client, "02:30", datetime(2026, 10, 24, 12, 0, tzinfo=BERLIN))
    jetzt = datetime(2026, 10, 25, 1, 10, tzinfo=timezone.utc).astimezone(BERLIN)  # 02:10 +01:00

    pruefen(client, jetzt)

    assert len(auftraege_von(client)) == 1


def test_autumn_change_the_preview_counts_both_passes(client, monkeypatch):
    """The line under a typed cron expression: at 02:50 +02:00 the next runs
    of a quarter-hour schedule are the second pass of the hour, in order."""
    from app.api.v1 import cronjobs

    jetzt = datetime(2026, 10, 25, 0, 50, tzinfo=timezone.utc).astimezone(BERLIN)
    monkeypatch.setattr(cronjobs, "_jetzt", lambda request: jetzt)

    quarter = client.get("/api/v1/cronjobs/preview", params={"zeitplan": "*/15 * * * *"})
    daily = client.get("/api/v1/cronjobs/preview", params={"zeitplan": "30 2 * * *"})

    assert quarter.json() == [
        "2026-10-25T02:00:00+01:00", "2026-10-25T02:15:00+01:00", "2026-10-25T02:30:00+01:00",
    ]
    assert daily.json() == [
        "2026-10-25T02:30:00+01:00", "2026-10-26T02:30:00+01:00", "2026-10-27T02:30:00+01:00",
    ]


def test_the_calendar_names_both_passes_of_the_repeated_hour():
    """A day in the calendar shows what the clock will do: both passes."""
    from types import SimpleNamespace

    entry = SimpleNamespace(einmalig=False, datum=None, zeitplan="30 2 * * *")
    start = datetime(2026, 10, 24, 22, 0, tzinfo=timezone.utc).astimezone(BERLIN)
    end = datetime(2026, 10, 26, 0, 0, tzinfo=BERLIN)

    moments = schedule_calendar._moments(entry, start, start, end)

    assert [m.isoformat() for m in moments] == [
        "2026-10-25T02:30:00+02:00", "2026-10-25T02:30:00+01:00",
    ]


def _reference_moments(zeitplan: str, jetzt: datetime) -> list[datetime]:
    """Every due moment within two days of ``jetzt``, in order and each once —
    written out the long way, with no shortcut: every wall time of the
    expression, each read at both folds, the one in the missing hour read at
    the offset from before the jump."""
    from croniter import croniter

    cron = zeitplan if len(zeitplan.split()) == 5 else (
        f"{int(zeitplan[3:])} {int(zeitplan[:2])} * * *"
    )
    wall = jetzt.replace(tzinfo=None, fold=0)
    walk = croniter(cron, wall - timedelta(days=2))
    found: set[datetime] = set()
    current = walk.get_next(datetime)
    while current < wall + timedelta(days=2):
        zone = jetzt.tzinfo
        first = current.replace(tzinfo=zone, fold=0).astimezone(timezone.utc)
        second = current.replace(tzinfo=zone, fold=1).astimezone(timezone.utc)
        found.add(first)
        if second > first:
            found.add(second)
        current = walk.get_next(datetime)
    return sorted(found)


@pytest.mark.parametrize("zone_name", ["Europe/Berlin", "America/New_York", "Australia/Lord_Howe"])
@pytest.mark.parametrize("zeitplan", ["02:30", "30 2 * * *", "*/15 * * * *", "0 * * * *", "45 1 * * *"])
def test_the_walk_agrees_with_the_long_way_across_both_clock_changes(zone_name, zeitplan):
    """Every forty-seven minutes across the clock changes of 2026 and the
    days either side: the next and the most recent due moment are the ones a
    plain list of all of them gives. It is what keeps the shortcut away from
    a clock change honest."""
    zone = ZoneInfo(zone_name)
    spans = [
        datetime(2026, 3, 7, 0, 0, tzinfo=timezone.utc),
        datetime(2026, 3, 28, 0, 0, tzinfo=timezone.utc),
        datetime(2026, 4, 3, 12, 0, tzinfo=timezone.utc),
        datetime(2026, 10, 24, 0, 0, tzinfo=timezone.utc),
        datetime(2026, 11, 1, 0, 0, tzinfo=timezone.utc),
    ]
    for begin in spans:
        span_end = begin + timedelta(hours=40)
        moment = begin
        while moment < span_end:
            jetzt = moment.astimezone(zone)
            reference = _reference_moments(zeitplan, jetzt)
            upcoming_ref = next(m for m in reference if m >= moment)
            earlier_ref = [m for m in reference if m <= moment][-1]
            # In UTC: a time of the repeated hour never compares equal to a
            # time of another zone, whatever moment it names (PEP 495).
            next_found = terminplan.naechster_termin(zeitplan, jetzt).astimezone(timezone.utc)
            last_found = terminplan.letzter_termin(zeitplan, jetzt).astimezone(timezone.utc)
            assert next_found == upcoming_ref, (zeitplan, jetzt)
            assert last_found == earlier_ref, (zeitplan, jetzt)
            moment += timedelta(minutes=47)


def test_an_ordinary_day_every_quarter_hour_stays_as_it_was(config, client):
    """Silence probe for the one above: the same span a week earlier, no
    clock change in it — the same seventeen runs, a quarter of an hour
    apart."""
    agentdatei(Path(config.app.agenten_verzeichnis))
    provider_setzen(client, MockProvider(mock_endpunkt("test")))
    eintrag = eintrag_anlegen(client, "*/15 * * * *", datetime(2026, 10, 17, 12, 0, tzinfo=BERLIN))

    von = datetime(2026, 10, 17, 23, 0, tzinfo=timezone.utc)
    bis = datetime(2026, 10, 18, 3, 0, tzinfo=timezone.utc)
    gefeuert = feuerungen(client, eintrag.id, von, bis)

    erwartet = [von + n * QUARTER_HOUR for n in range(17)]
    assert gefeuert == [(moment, moment) for moment in erwartet]


@pytest.mark.parametrize("zeitplan", ZWEI_UHR_PLAENE)
def test_ein_gewoehnlicher_tag_feuert_einmal(config, client, zeitplan):
    """The control for the two above: over the same span of hours on a day
    without a transition, a 02:00 plan fires once — so the counts above are
    about the transition and not about the ticking."""
    agentdatei(Path(config.app.agenten_verzeichnis))
    provider_setzen(client, MockProvider(mock_endpunkt("test")))
    eintrag = eintrag_anlegen(client, zeitplan, datetime(2026, 10, 17, 12, 0, tzinfo=BERLIN))

    von = datetime(2026, 10, 17, 23, 0, tzinfo=timezone.utc)
    bis = datetime(2026, 10, 18, 3, 0, tzinfo=timezone.utc)
    gefeuert = feuerungen(client, eintrag.id, von, bis)

    assert len(auftraege_von(client)) == 1
    zwei_uhr = datetime(2026, 10, 18, 0, 0, tzinfo=timezone.utc)  # 02:00 +02:00
    assert gefeuert == [(zwei_uhr, zwei_uhr)]


# The preload that used to be tested here is retired: it read the
# model out of the agent file's ``model:`` head, and that head field is gone.
# Its purpose — the model already being warm when a due time arrives — is the
# slot's now, which is simply loaded from program start onwards.
