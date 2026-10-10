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

from app import terminplan
from app.ohne_agent import NAME as OHNE_AGENT
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


def test_minutentakt_ist_gerade_noch_erlaubt():
    """The floor is a minute, and '* * * * *' sits exactly on it."""
    terminplan.abstand_pruefen("* * * * *")


@pytest.mark.parametrize("zeitplan", ["08:00", "2026-09-04T09:00"])
def test_abstandspruefung_geht_die_beiden_anderen_formen_nichts_an(zeitplan):
    terminplan.abstand_pruefen(zeitplan)


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
        terminplan.abstand_pruefen(zeitplan)


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
        agent=OHNE_AGENT, task="x", zeitplan="08:00", herkunft="chat",
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
        agent=OHNE_AGENT, task="x", zeitplan="08:00", herkunft="chat",
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
        agent=OHNE_AGENT, task="x", zeitplan="*/15 * * * *", herkunft="chat",
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


@pytest.mark.parametrize(
    "zeitplan, zweite_feuerung",
    [
        # The daily form catches the repeated hour the moment it comes
        # round again: 01:00 UTC is 02:00 +01:00.
        ("02:00", datetime(2026, 10, 25, 1, 0, tzinfo=timezone.utc)),
        # The cron form stands for the same due moment but only reaches it
        # an hour late, at 03:00 +01:00 (02:00 UTC): croniter keeps
        # answering with the FIRST pass through 02:00 for as long as that
        # pass lasts. Frozen here as MEASURED, not as wanted — this is a
        # known, deliberately deferred fault (a cron-form entry loses its
        # run across a clock change), and a repair of it has to show up as
        # this line turning red.
        ("0 2 * * *", datetime(2026, 10, 25, 2, 0, tzinfo=timezone.utc)),
    ],
)
def test_herbstumstellung_feuert_wie_der_altbestand(config, client, zeitplan, zweite_feuerung):
    """25 October 2026: 02:00 comes round twice — once at +02:00 and again an
    hour later at +01:00.

    MEASURED, and not what one might assume: both forms fire
    TWICE. The fired-at stamp cannot block the second one, because the two
    are not the same moment — they are an hour apart in absolute time, and
    the stamp of the first is genuinely older than the second. The daily
    'HH:MM' form has always done this; the cron form does the same. Making
    it one fire would be a change to WHEN an entry fires, which is
    deliberately left as it is.
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
    # Both forms stand for the same two due moments; only WHEN the second
    # one is noticed differs, which is what the parameter above pins down.
    assert [termin for _, termin in gefeuert] == [erste, zweite]
    assert [tick for tick, _ in gefeuert] == [erste, zweite_feuerung]


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
