"""``ask_user`` is the question itself — no permission box stands before it,
and a waiting question takes a text, never a rule."""

from __future__ import annotations

import asyncio

import pytest

from app import berechtigungswahl
from app.api.v1.generierung import bestaetigen as confirm_endpunkt
from app.api.v1.schemas import BestaetigungAnfrage
from app.berechtigungsregeln import laden
from app.generationen import Generierungsverwaltung
from app.tools import frage_werkzeug
from app.tools.registry import WerkzeugRegistry


@pytest.mark.parametrize("modus", ["manuell", "restricted", "auto"])
def test_ask_user_braucht_in_keinem_modus_eine_freigabe(tmp_path, modus):
    regeln = tmp_path / "berechtigungen.json"
    berechtigungswahl.anwenden(regeln, "chat", modus)
    registry = WerkzeugRegistry([], shell_an=True, berechtigungen_pfad=regeln)

    assert registry.braucht_bestaetigung(frage_werkzeug.WERKZEUG_NAME, {"question": "x"}) is False


def test_ein_anderes_werkzeug_fragt_im_modus_manuell_weiter(tmp_path):
    """The silence test: only the question is exempt — a tool with no path and
    no rule of its own still falls under the mode's "ask"."""
    regeln = tmp_path / "berechtigungen.json"
    berechtigungswahl.anwenden(regeln, "chat", "manuell")
    registry = WerkzeugRegistry([], shell_an=True, berechtigungen_pfad=regeln)

    assert registry.braucht_bestaetigung("web_search", {"query": "x"}) is True


# --- The confirm route: a waiting question takes a text, never a rule -------


async def _wartende_frage(verwaltung, name):
    """A run that stands at ``name`` waiting for an answer."""
    wartet = asyncio.Event()

    async def arbeit(lauf):
        zukunft = lauf.bestaetigung_erwarten("c1", name)
        wartet.set()
        await zukunft

    lauf = verwaltung.starten(chat_id="c", endpoint_id="e", arbeit=arbeit)
    await asyncio.wait_for(wartet.wait(), timeout=2)
    return lauf


def _anfrage(lauf, **felder):
    return BestaetigungAnfrage(
        generation_id=lauf.id, aufruf_id="c1", name="ask_user", **felder
    )


@pytest.mark.asyncio
async def test_immer_erlauben_auf_eine_frage_schreibt_keine_regel_und_stellt_nichts_zu(config):
    verwaltung = Generierungsverwaltung()
    lauf = await _wartende_frage(verwaltung, "ask_user")

    antwort = confirm_endpunkt(
        _anfrage(lauf, erlaubt=True, dauerhaft=True), generierungen=verwaltung, config=config
    )

    assert antwort.zugestellt is False
    assert not lauf.bestaetigungen["c1"].done()
    assert laden(config.pfad(config.app.berechtigungen_datei)).regeln == {}


@pytest.mark.asyncio
async def test_ein_text_wird_der_frage_zugestellt(config):
    verwaltung = Generierungsverwaltung()
    lauf = await _wartende_frage(verwaltung, "ask_user")

    antwort = confirm_endpunkt(
        _anfrage(lauf, erlaubt=True, antwort="Blue"), generierungen=verwaltung, config=config
    )

    assert antwort.zugestellt is True
    assert lauf.bestaetigungen["c1"].result() == "Blue"


@pytest.mark.asyncio
async def test_eine_leere_antwort_schliesst_die_frage_weiterhin(config):
    """The box closes a question with an empty text (it is not a yes): that
    still arrives, the run goes on with `OHNE_ANTWORT`."""
    verwaltung = Generierungsverwaltung()
    lauf = await _wartende_frage(verwaltung, "ask_user")

    antwort = confirm_endpunkt(
        _anfrage(lauf, erlaubt=False, antwort=""), generierungen=verwaltung, config=config
    )

    assert antwort.zugestellt is True


@pytest.mark.asyncio
async def test_immer_erlauben_auf_eine_werkzeugfreigabe_schreibt_die_regel_wie_zuvor(config):
    """The silence test: a waiting tool permission still becomes a rule."""
    verwaltung = Generierungsverwaltung()
    lauf = await _wartende_frage(verwaltung, "web_search")

    antwort = confirm_endpunkt(
        BestaetigungAnfrage(
            generation_id=lauf.id, aufruf_id="c1", name="web_search",
            erlaubt=True, dauerhaft=True,
        ),
        generierungen=verwaltung, config=config,
    )

    assert antwort.zugestellt is True
    assert laden(config.pfad(config.app.berechtigungen_datei)).regeln["web_search"] == "ja"
