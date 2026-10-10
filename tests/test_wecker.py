"""The tick: the 30-second pass, and the retired ``schedule:``.

The passes are called with an explicit ``jetzt`` — the tests turn the clock
instead of waiting.

What used to stand here was the alarm clock's own agent path: an agent fired
from a ``schedule:`` field in its front matter, with catch-up, skipping and a
pause after three failures. That path is gone — the cron table is
the one way to say when something runs, and its own tests
(tests/test_cronablauf.py) cover catch-up and skipping for it. What is left
here is the tick itself, the daily arithmetic the tick's helpers still do,
and the guard that a file with an old ``schedule:`` fires nothing.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.agenten import agent_lesen
from app.wecker import letzter_termin, naechster_termin, zone_name
from tests.conftest import provider_setzen
from app.providers import MockProvider, mock_endpunkt


def schreiben(ordner: Path, name: str, inhalt: str) -> Path:
    ordner.mkdir(parents=True, exist_ok=True)
    datei = ordner / f"{name}.md"
    datei.write_text(inhalt, encoding="utf-8")
    return datei


MIT_WECKER = """---
model: test
schedule: "12:00"
schedule_task: "Collect the morning news."
---

You are the news agent.
"""


# --- The retired front-matter field ----------------------------------------


def test_zeitplan_wird_angenommen_und_ignoriert(tmp_path):
    """An existing file keeps working — the agent is playable, the schedule
    is simply not a schedule any more. Refusing the file instead would take
    the user's agent out of play over a field that merely stopped doing
    anything."""
    agent = agent_lesen(schreiben(tmp_path, "news", MIT_WECKER))
    assert agent.name == "news"
    assert not hasattr(agent, "zeitplan")


def test_zeitplan_wird_beim_laden_gemeldet(tmp_path, caplog):
    """Silently ignoring it would be the worst of both: the user sees a
    schedule in their file and nothing ever runs."""
    with caplog.at_level(logging.INFO, logger="app.agenten"):
        agent_lesen(schreiben(tmp_path, "news", MIT_WECKER))
    assert any(
        getattr(satz, "ereignis", None) == "agent_zeitplan_stillgelegt"
        for satz in caplog.records
    )


def test_kaputter_zeitplan_nimmt_den_agenten_nicht_aus_dem_spiel(tmp_path):
    """Not even the two shapes that used to be refusals: an unquoted 12:00
    (the sexagesimal number 720 to YAML) and a schedule without its task.
    Nothing reads the value any more, so nothing can trip over it."""
    ohne_anfuehrung = agent_lesen(
        schreiben(tmp_path, "a", '---\nschedule: 12:00\nschedule_task: "x"\n---\n\nP.\n')
    )
    assert ohne_anfuehrung.prompt == "P."
    ohne_aufgabe = agent_lesen(
        schreiben(tmp_path, "b", '---\nschedule: "25:99"\n---\n\nP.\n')
    )
    assert ohne_aufgabe.prompt == "P."


# --- Schedule arithmetic ---------------------------------------------------


# --- The machine's zone ------------------------------------------------------
#
# Asked of tzlocal, the one reader for both systems: on Windows there is
# neither TZ nor /etc/localtime, and the former reading of those two left
# the zone empty there. Faked here so the test does not depend on the
# machine it runs on.


def test_the_machines_zone_is_what_tzlocal_names(monkeypatch):
    monkeypatch.setattr("tzlocal.get_localzone_name", lambda: "Pacific/Auckland")
    assert zone_name("") == "Pacific/Auckland"


def test_a_machine_whose_zone_has_no_name_answers_nothing(monkeypatch):
    from zoneinfo import ZoneInfoNotFoundError

    def nothing():
        raise ZoneInfoNotFoundError("no zone")

    monkeypatch.setattr("tzlocal.get_localzone_name", nothing)
    assert zone_name("") == ""


def test_the_setting_wins_over_the_machine(monkeypatch):
    """The silence side: a configured zone is answered as before, and the
    machine is not even asked."""
    def nothing():
        raise AssertionError("the machine must not be asked")

    monkeypatch.setattr("tzlocal.get_localzone_name", nothing)
    assert zone_name("America/New_York") == "America/New_York"


def test_tz_and_etc_localtime_are_not_read_here_any_more(monkeypatch):
    """One way for both systems: what TZ says is tzlocal's business, not
    this function's — so a TZ that disagrees with tzlocal's answer changes
    nothing here."""
    monkeypatch.setenv("TZ", "Asia/Tokyo")
    monkeypatch.setattr("tzlocal.get_localzone_name", lambda: "Pacific/Auckland")
    assert zone_name("") == "Pacific/Auckland"


def test_letzter_termin_heute():
    jetzt = datetime(2026, 8, 4, 14, 0, tzinfo=timezone.utc)
    assert letzter_termin("12:00", jetzt) == datetime(
        2026, 8, 4, 12, 0, tzinfo=timezone.utc
    )


def test_letzter_termin_gestern():
    jetzt = datetime(2026, 8, 4, 7, 0, tzinfo=timezone.utc)
    assert letzter_termin("12:00", jetzt) == datetime(
        2026, 8, 3, 12, 0, tzinfo=timezone.utc
    )


def test_naechster_termin_heute():
    """The mirror of ``letzter_termin``: still ahead today
    stays today."""
    jetzt = datetime(2026, 8, 4, 7, 0, tzinfo=timezone.utc)
    assert naechster_termin("12:00", jetzt) == datetime(
        2026, 8, 4, 12, 0, tzinfo=timezone.utc
    )


def test_naechster_termin_morgen():
    jetzt = datetime(2026, 8, 4, 14, 0, tzinfo=timezone.utc)
    assert naechster_termin("12:00", jetzt) == datetime(
        2026, 8, 5, 12, 0, tzinfo=timezone.utc
    )


# --- The tick ---------------------------------------------------------------


def pruefen(client, jetzt: datetime) -> None:
    """One pass at a set time."""
    asyncio.run(client.app.state.wecker.einmal_pruefen(jetzt=jetzt))


def auftraege_von(client, agent: str) -> list[dict]:
    return [a for a in client.get("/api/v1/jobs").json() if a["agent"] == agent]


MORGEN_13 = datetime.now(timezone.utc).replace(
    hour=13, minute=0, second=0, microsecond=0
) + timedelta(days=1)


def test_agent_mit_zeitplan_feuert_nicht(config, client):
    """The measured heart of the one-schedule rule: the file says 12:00, the pass runs at
    13:00 the next day — the very moment the old alarm clock would have
    caught up on — and nothing starts."""
    schreiben(Path(config.app.agenten_verzeichnis), "news", MIT_WECKER)
    provider_setzen(client, MockProvider(mock_endpunkt("test")))

    pruefen(client, MORGEN_13)
    pruefen(client, MORGEN_13 + timedelta(minutes=30))
    assert auftraege_von(client, "news") == []


def test_agents_liefert_kein_zeitplanfeld(config, client):
    """The API stops offering a schedule it no longer honours."""
    schreiben(Path(config.app.agenten_verzeichnis), "news", MIT_WECKER)
    (eintrag,) = [a for a in client.get("/api/v1/agents").json() if a["name"] == "news"]
    assert "schedule" not in eintrag
    assert "schedule_paused" not in eintrag


def test_takt_reicht_an_die_crontabelle_durch(config, client):
    """What the pass still does: fire what the cron table has due."""
    schreiben(Path(config.app.agenten_verzeichnis), "recherche",
              "---\nmodel: test\n---\n\nPrompt.\n")
    provider_setzen(client, MockProvider(mock_endpunkt("test")))
    client.app.state.repositories.cronjobs.erstellen(
        agent="recherche", task="Los", zeitplan="12:00", herkunft="chat"
    )

    pruefen(client, MORGEN_13)
    assert len(auftraege_von(client, "recherche")) == 1


def _language_of_a_due_time(client, monkeypatch, choice: str | None) -> str | None:
    """What a scheduled run is started with, under a stored interface choice
    (None: nothing stored) and `de` in the configuration."""
    from types import SimpleNamespace

    from app import sprachwahl
    from app.api.v1 import auftraege
    from app.wecker import termin_ausloesen

    client.app.state.config.app.language = "de"
    if choice is not None:
        client.app.state.repositories.einstellungen.setzen(
            "global", sprachwahl.SCHLUESSEL, {"sprache": choice}
        )
    started: list[str | None] = []

    def capture(**fields):
        started.append(fields["sprache"])
        return None

    monkeypatch.setattr(auftraege, "auftrag_anstossen", capture)
    asyncio.run(termin_ausloesen(client.app, SimpleNamespace(name="news"), "Los"))
    return started[0]


def test_a_due_time_speaks_the_language_chosen_for_the_interface(client, monkeypatch):
    """The interface is set to English, the configuration says German: the
    scheduled run's texts come in English, like the same schedule's error
    note (app/cronablauf.py)."""
    assert _language_of_a_due_time(client, monkeypatch, "en") == "en"


def test_a_due_time_on_auto_keeps_the_configured_language(client, monkeypatch):
    """Silence probe: on `auto` the device decides, which the service cannot
    see, so the configured language stands as before."""
    assert _language_of_a_due_time(client, monkeypatch, "auto") == "de"


def test_a_due_time_with_nothing_stored_keeps_the_configured_language(client, monkeypatch):
    """Silence probe: no choice stored at all reads as `auto`."""
    assert _language_of_a_due_time(client, monkeypatch, None) == "de"
