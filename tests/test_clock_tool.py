"""The clock tool: what it answers, where it is offered, and that it never asks.

Three things are worth pinning down.

**It is the only clock.** The date block at the front of a user turn carries
a day and a zone, never a minute. Everything a run needs a
minute for — "in ten minutes", "how long since" — it asks this tool for. So
the tool has to be in every run that has tools at all, including a run whose
agent wrote its own list before this tool existed; the reading has to be the
one the alarm clock itself uses, or a schedule would fire in one zone and be
computed in another; and "auto" has to mean auto, with no reading invented
when nothing is configured.

**It never asks.** It reads a clock and hands the reading back: no file, no
folder, no row, no message. Tor 3 therefore answers "ja" in every mode, not
only in the lenient one — in an unattended run "fragen" becomes "nein", and a
scheduled run refused the clock cannot work out what has happened since the
last one. An explicit per-tool rule still wins: that is somebody's word, not
a mode.

**It takes nothing.** An empty schema and no required fields, so there is
nothing to get wrong and nothing to invent.
"""

from __future__ import annotations

import json
from datetime import datetime

import pytest

from app import berechtigungen
from app.berechtigungsregeln import Regeldatei
from app.tools import uhr
from app.tools.registry import WerkzeugRegistry, WerkzeugVerboten


class _Uhr(datetime):
    """A clock the test holds still — the real one would only agree by luck."""

    @classmethod
    def now(cls, tz=None):
        return datetime(2026, 8, 24, 9, 41, tzinfo=tz)


@pytest.fixture
def uhr_steht(monkeypatch):
    monkeypatch.setattr("app.wecker.datetime", _Uhr)


# --- What it answers ---------------------------------------------------------


def test_the_reading_carries_zone_moment_and_weekday(uhr_steht):
    """The three fields the reference time server answers, and no others:
    the zone by name (not an abbreviation — a bare "CEST" cannot be computed
    with), the moment with its offset, and the weekday in English, because
    every other word that reaches the model is English too."""
    gelesen = json.loads(uhr.clock_reading("Europe/Berlin"))
    assert gelesen == {
        "timezone": "Europe/Berlin",
        "datetime": "2026-08-24T09:41:00+02:00",
        "day_of_week": "Monday",
    }


def test_without_a_configured_zone_it_reads_the_machines_clock(uhr_steht):
    """The same fallback the alarm clock takes (app/wecker.jetzt_in_zone).
    The name is the one the machine's own clock reports — the very reading
    the former sentence carried in that case."""
    gelesen = json.loads(uhr.clock_reading(None))
    assert gelesen["timezone"]  # the machine names its zone, or says nothing
    assert gelesen["datetime"].startswith("2026-08-24T09:41:00")
    assert gelesen["day_of_week"] == "Monday"


def test_the_description_names_no_example(uhr_steht):
    """A measurement stands behind this: with an example in the text, the
    model worked out relative times in every turn, asked or not — and the
    description rides in every request, like the sentence before it. The
    instruction stays, the example goes."""
    text = uhr.werkzeug_beschreibung().beschreibung
    assert "before you work out any time relative to now" in text
    for beispiel in ("in ten minutes", "tomorrow at nine", "how long ago"):
        assert beispiel not in text


def test_ohne_eingestellte_zone_kommt_ein_name_keine_abkuerzung(uhr_steht, monkeypatch):
    """``CEST`` is a name nothing can be computed with — an hour from now is
    not derivable from it. The zone database's name is what travels, also
    when the machine's own zone answers."""
    monkeypatch.setattr("app.tools.uhr.zone_name", lambda name: "Europe/Berlin")
    assert json.loads(uhr.clock_reading(None))["timezone"] == "Europe/Berlin"


def _mit_serverwerkzeugen(registry, *namen):
    """Takes tools of these names over, as a connected server would."""
    from app.tools.mcp_client import MCPWerkzeug
    from app.tools.registry import ServerEintrag

    class _Client:
        werkzeuge = [
            MCPWerkzeug(
                name=name, beschreibung="a server's own",
                schema={"type": "object", "properties": {}}, server="zeitserver",
            )
            for name in namen
        ]

        async def stoppen(self):
            return None

    registry._werkzeuge_uebernehmen(ServerEintrag(name="zeitserver"), _Client())


def test_ein_server_mit_einem_eingebauten_namen_wird_uebersprungen():
    """The clock is in every run with tools and is reached before any server
    tool could be. A server reporting the same name would put it in the
    offer a second time — which strict OpenAI-compatible servers answer with
    400 — while its own tool stayed unreachable either way."""
    registry = WerkzeugRegistry([])
    assert uhr.WERKZEUG_NAME in registry.builtin_names()

    _mit_serverwerkzeugen(registry, uhr.WERKZEUG_NAME)

    assert uhr.WERKZEUG_NAME not in registry._werkzeuge
    namen = [w["function"]["name"] for w in registry.als_openai_werkzeuge()]
    assert namen.count(uhr.WERKZEUG_NAME) == 1


def test_a_server_keeps_its_tool_where_no_builtin_runs():
    """The silent case, and the one that must not be got wrong: with the
    shell switched off there is no built-in counterpart in the offer, so a
    file server's tools must come through untouched. Blocking them would
    take a user's whole file access away without a word — the settings
    window goes on listing them as chosen."""
    registry = WerkzeugRegistry([], shell_an=False)
    assert "read_file" not in registry.builtin_names()

    _mit_serverwerkzeugen(registry, "read_file", "list_dir")

    assert set(registry._werkzeuge) == {"read_file", "list_dir"}


def test_the_zone_never_comes_from_the_model():
    """The zone is a setting, not an argument: a run that could name its own
    would compute "in ten minutes" in a zone the entry does not fire in."""
    schema = uhr.werkzeug_beschreibung().schema
    assert schema == {"type": "object", "properties": {}}
    assert "timezone" not in json.dumps(schema)


# --- Where it is offered -----------------------------------------------------


def test_it_stands_everywhere_even_without_any_equipment():
    """No folder, no table, no file — and still there, like the goal tool.
    The clock is what a run without any other tool needs most."""
    registry = WerkzeugRegistry([])
    namen = [w["function"]["name"] for w in registry.als_openai_werkzeuge()]
    assert namen == ["goal", uhr.WERKZEUG_NAME]
    assert uhr.WERKZEUG_NAME in registry.namen()


def test_switched_off_it_disappears_from_the_offering():
    registry = WerkzeugRegistry([])
    registry.abgeschaltet = {uhr.WERKZEUG_NAME}
    namen = [w["function"]["name"] for w in registry.als_openai_werkzeuge()]
    assert uhr.WERKZEUG_NAME not in namen


async def test_the_call_reads_the_clock_of_the_configured_zone(uhr_steht):
    registry = WerkzeugRegistry([], zeitzone="Asia/Tokyo")
    gelesen = json.loads(await registry.ausfuehren(uhr.WERKZEUG_NAME, {}))
    assert gelesen["timezone"] == "Asia/Tokyo"
    assert gelesen["datetime"].endswith("+09:00")


# --- It never asks -----------------------------------------------------------


def test_no_mode_asks_about_it():
    """All three modes at once. Auto and Manuell answer "ja" anyway; the
    point is Restricted, which asks about everything else — and whose
    "fragen" becomes a flat "nein" for an unattended run."""
    streng = Regeldatei(standard={"chat": "fragen", "agent": "fragen"})
    for herkunft in ("chat", "agent"):
        urteil = berechtigungen.urteil(uhr.WERKZEUG_NAME, {}, [], herkunft, regeln=streng)
        assert urteil.antwort == "ja", (herkunft, urteil)


def test_an_explicit_rule_still_wins():
    """A mode is skipped; a person's own word is not. Who writes
    ``get_current_time: nein`` means it — the same rule every other tool
    obeys."""
    regeln = Regeldatei(regeln={uhr.WERKZEUG_NAME: "nein"})
    urteil = berechtigungen.urteil(uhr.WERKZEUG_NAME, {}, [], "chat", regeln=regeln)
    assert urteil.antwort == "nein"


async def test_the_executing_road_knows_no_confirmation():
    """Through the real gate, not only the pure function: `ausfuehren`
    judges the call itself once more, and a "fragen" would surface here as
    WerkzeugVerboten the moment the registry has no confirmation route."""
    registry = WerkzeugRegistry([], zeitzone="Europe/Berlin")
    assert registry.braucht_bestaetigung(uhr.WERKZEUG_NAME, {}) is False
    assert json.loads(await registry.ausfuehren(uhr.WERKZEUG_NAME, {}))["timezone"] == (
        "Europe/Berlin"
    )


async def test_switched_off_it_stays_locked():
    registry = WerkzeugRegistry([])
    registry.abgeschaltet = {uhr.WERKZEUG_NAME}
    with pytest.raises(WerkzeugVerboten):
        await registry.ausfuehren(uhr.WERKZEUG_NAME, {})
