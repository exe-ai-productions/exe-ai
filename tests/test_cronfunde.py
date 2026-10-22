"""Three holes in a scheduled run: its tools, its chain, its announcement.

* **A run that quietly loses its tools.** The one field hands out an id, and
  nothing asked whether the endpoint behind it can call tools. An agent
  whose work IS its tools then ran on a model that cannot make a single
  call: no error, no refusal — a paragraph out of the model's own head, and
  a job that reads 'fertig'. The pre-flight check said "ready" for exactly
  the runs the start then refused, so the due time was logged as
  ``termin_fehlgeschlagen`` instead of being shown as "waiting for a model".
* **The chain that would not die.** A continuation whose run ended without
  writing another continuation and without being switched off stayed
  active. Its schedule is a daily 'HH:MM' two minutes out
  (``zwischenstand.bald``), so it fired again the next day with the stale
  handoff text, next to the fresh chain its origin opens — two chains for
  one job, both booking failed runs on the same origin.
* **The doubled announcement.** With ``fehlergrenze`` at 1, chain and origin
  reached their limit in the same booking and both said "stopped after 1
  failed runs" — the same sentence twice, because the chain's
  ``basisaufgabe`` is a copy of the origin's task.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from app import agentenmodellwahl, agentenserver, cronablauf, zwischenstand
from app.agenten import agenten_laden
from app.api.abhaengigkeiten import STANDARD_BENUTZER
from fastapi import HTTPException

from app.api.v1.auftraege import auftrag_anstossen
from app.providers import MockProvider, Stueck, mock_endpunkt
from app.providers.base import Werkzeugaufruf
from app.tools import cron_notiz
from app.tools.registry import WerkzeugRegistry
from tests.conftest import agentenmodell_leer, agentenmodell_setzen, provider_setzen
from tests.test_auftraege_api import _bis_beendet, agent_schreiben
from tests.test_kettenband import (
    AUFGABE,
    eintrag_anlegen,
    gemeldet,  # noqa: F401 — fixture, used by name
    kette_von,
    lauf_starten,
    ueberlauf,
)


@pytest.fixture(autouse=True)
def wartestand_leeren():
    """The waiting state lives in a module-level dict on purpose (it is a
    fact about right now, not about the entry) — which means it survives
    between tests unless it is emptied."""
    cronablauf._wartend.clear()
    yield
    cronablauf._wartend.clear()


class ImmerNotiz(MockProvider):
    """A note call every round, forever — a run that never ends by itself,
    so the round limit is what ends it. ``cron_note`` because a cron-fired
    run is offered it whatever else the registry holds."""

    async def streamen(self, anfrage):
        self.letzte_anfrage = anfrage
        self.alle_anfragen.append(anfrage)
        self.durchlaeufe += 1
        yield Stueck(
            "tool_call",
            werkzeugaufrufe=[
                Werkzeugaufruf(
                    id=f"n{self.durchlaeufe}",
                    name=cron_notiz.WERKZEUG_NAME,
                    argumente={"note": f"Stand {self.durchlaeufe}"},
                )
            ],
        )


# --- A run must never silently lose its tools -----------------------


def werkzeugfaehig(client, endpoint_id: str, faehig: bool) -> None:
    """What the endpoint says about tool calls. ``provider_setzen`` leaves
    the test endpoint incapable on purpose, so this is said out loud where a
    test needs the other answer."""
    zustand = client.app.state.discovery.zustaende[endpoint_id]
    zustand.endpunkt.capabilities.tool_calls = faehig


def werkzeuge_an(client) -> WerkzeugRegistry:
    """Tools switched on house-wide — without both of these no run is handed
    any, and then there is nothing for an endpoint's capability to cost."""
    registry = WerkzeugRegistry([], shell_an=True,
                                cronjobs_repo=client.app.state.repositories.cronjobs)
    client.app.state.config.features.mcp = True
    client.app.state.werkzeuge = registry
    return registry


async def test_das_modellfeld_wird_uebergangen_wenn_es_keine_werkzeuge_kann(
    config, client
):
    """The field points at an endpoint that cannot call tools, and the agent
    has some: the run goes to the MAIN model, with its tools — rather than to
    the field's own answer without them.

    It used to go to "the next endpoint that can", and next was the order of
    a list, not a decision: that is how a continuation landed on
    `openai:text-embedding-ada-002` and OpenAI answered 404 "This is not a
    chat model". The fallback names one
    model now, and it is the one the program starts itself.
    """
    agent_schreiben(config)
    registry = werkzeuge_an(client)
    # A tool-capable endpoint that is NOT the main model, registered FIRST:
    # this is the one the old loop would have taken, and taking it is what
    # the point forbids.
    await client.app.state.discovery.anmelden(mock_endpunkt("zweit"))
    # The main model, under the mark the field stores for it — reachable,
    # and tool-capable, because ``mock_endpunkt`` says so for itself.
    await client.app.state.discovery.anmelden(
        mock_endpunkt(agentenmodellwahl.HAUPTMODELL)
    )
    # ...and the field, pointed at an endpoint that cannot call tools.
    provider_setzen(client, MockProvider(mock_endpunkt("test"), haeppchen=["Ok."]))
    werkzeugfaehig(client, "test", False)

    repos = client.app.state.repositories
    auftrag = auftrag_anstossen(
        config=client.app.state.config, repositories=repos,
        discovery=client.app.state.discovery,
        generierungen=client.app.state.generierungen, registry=registry,
        agent=agenten_laden(*config.agentenverzeichnisse)["recherche"],
        task=AUFGABE, endpoint_id=None, user_id=STANDARD_BENUTZER, sprache="de",
    )
    await _bis_beendet(repos, auftrag.id)

    assert auftrag.endpoint_id.startswith(agentenmodellwahl.HAUPTMODELL)
    angeboten = [
        s.inhalt for s in repos.auftraege.schritte(auftrag.id)
        if s.inhalt.startswith("Werkzeuge angeboten")
    ]
    assert angeboten and angeboten[0] != "Werkzeuge angeboten: keine"


async def test_ohne_feld_laeuft_es_auf_dem_hauptmodell(config, client):
    """The point itself: nobody picked anything, so the main model runs it —
    and not whichever endpoint the list happens to name first."""
    agent_schreiben(config)
    registry = werkzeuge_an(client)
    provider_setzen(client, MockProvider(mock_endpunkt("test"), haeppchen=["Ok."]))
    # Two more, in this order: a tool-capable stranger first — the one the
    # old loop would have taken — and the main model behind it.
    await client.app.state.discovery.anmelden(mock_endpunkt("zweit"))
    await client.app.state.discovery.anmelden(
        mock_endpunkt(agentenmodellwahl.HAUPTMODELL)
    )
    agentenmodell_leer(client)

    repos = client.app.state.repositories
    auftrag = auftrag_anstossen(
        config=client.app.state.config, repositories=repos,
        discovery=client.app.state.discovery,
        generierungen=client.app.state.generierungen, registry=registry,
        agent=agenten_laden(*config.agentenverzeichnisse)["recherche"],
        task=AUFGABE, endpoint_id=None, user_id=STANDARD_BENUTZER, sprache="de",
    )
    await _bis_beendet(repos, auftrag.id)

    assert auftrag.endpoint_id.startswith(agentenmodellwahl.HAUPTMODELL)


async def test_ohne_hauptmodell_faellt_der_lauf_auf_den_agentenserver(config, client):
    """The main server is not up: the run takes our AGENT server instead of
    being refused. It is the first of the two servers a run may take, and the
    main model is the fallback behind it — a third
    server, whatever its address, is never one of them."""
    agent_schreiben(config)
    registry = werkzeuge_an(client)
    provider_setzen(client, MockProvider(mock_endpunkt("test"), haeppchen=["Ok."]))
    await client.app.state.discovery.anmelden(mock_endpunkt(agentenserver.ENDPUNKT_ID))
    provider_setzen(
        client,
        MockProvider(mock_endpunkt(agentenserver.ENDPUNKT_ID), haeppchen=["Ok."]),
        endpoint_id=agentenserver.ENDPUNKT_ID,
    )
    agentenmodell_leer(client)

    repos = client.app.state.repositories
    auftrag = auftrag_anstossen(
        config=client.app.state.config, repositories=repos,
        discovery=client.app.state.discovery,
        generierungen=client.app.state.generierungen, registry=registry,
        agent=agenten_laden(*config.agentenverzeichnisse)["recherche"],
        task=AUFGABE, endpoint_id=None, user_id=STANDARD_BENUTZER, sprache="de",
    )
    await _bis_beendet(repos, auftrag.id)

    assert auftrag.endpoint_id == agentenserver.ENDPUNKT_ID


async def test_ein_erreichbarer_cloud_endpunkt_wird_nicht_genommen(config, client):
    """The fallback is LOCAL and nothing else. A cloud endpoint costs money
    and sends the run off this machine — neither is a decision a missing
    main server may make, so the run is still refused."""
    agent_schreiben(config)
    registry = werkzeuge_an(client)
    provider_setzen(client, MockProvider(mock_endpunkt("test"), haeppchen=["Ok."]))
    await client.app.state.discovery.anmelden(mock_endpunkt("wolke", group="cloud"))
    agentenmodell_leer(client)

    with pytest.raises(HTTPException) as fehler:
        auftrag_anstossen(
            config=client.app.state.config,
            repositories=client.app.state.repositories,
            discovery=client.app.state.discovery,
            generierungen=client.app.state.generierungen, registry=registry,
            agent=agenten_laden(*config.agentenverzeichnisse)["recherche"],
            task=AUFGABE, endpoint_id=None, user_id=STANDARD_BENUTZER, sprache="de",
        )
    assert fehler.value.status_code == 400


async def test_ein_fremder_endpunkt_ist_kein_rueckfall(config, client):
    """The counter-check to "the agent server takes over": a THIRD server is
    not a fallback, however well it answers. Both of ours are down, a
    tool-capable stranger is reachable — and the run is refused. Taking it
    would send the work somewhere this program did not start and does not
    know — the decision behind this bounds the fallback to nothing else."""
    agent_schreiben(config)
    registry = werkzeuge_an(client)
    provider_setzen(client, MockProvider(mock_endpunkt("test"), haeppchen=["Ok."]))
    await client.app.state.discovery.anmelden(mock_endpunkt("zweit"))
    werkzeugfaehig(client, "zweit", True)
    agentenmodell_leer(client)

    with pytest.raises(HTTPException) as fehler:
        auftrag_anstossen(
            config=client.app.state.config,
            repositories=client.app.state.repositories,
            discovery=client.app.state.discovery,
            generierungen=client.app.state.generierungen, registry=registry,
            agent=agenten_laden(*config.agentenverzeichnisse)["recherche"],
            task=AUFGABE, endpoint_id=None, user_id=STANDARD_BENUTZER, sprache="de",
        )
    assert fehler.value.status_code == 400


async def test_die_angezeigte_vorschau_ist_der_endpunkt_des_laufs(config, client):
    """The window's second line and the run itself, asked in the same
    situation: both name the same endpoint.

    The window reads its line from ``/jobs/laufmodell``, and that route asks
    ``agentenmodellwahl.lauf_kennung`` — the very call the start books the run
    with. So a preview naming an endpoint the run never goes to is no longer
    possible; this holds the two answers against each other in both states of
    the agent server, up and gone.
    """
    agent_schreiben(config)
    registry = werkzeuge_an(client)
    provider_setzen(client, MockProvider(mock_endpunkt("test"), haeppchen=["Ok."]))
    await client.app.state.discovery.anmelden(mock_endpunkt(agentenserver.ENDPUNKT_ID))
    provider_setzen(
        client,
        MockProvider(mock_endpunkt(agentenserver.ENDPUNKT_ID), haeppchen=["Ok."]),
        endpoint_id=agentenserver.ENDPUNKT_ID,
    )
    await client.app.state.discovery.anmelden(
        mock_endpunkt(agentenmodellwahl.HAUPTMODELL)
    )
    agentenmodell_leer(client)
    repos = client.app.state.repositories
    frage = "/api/v1/jobs/laufmodell"

    def starten():
        return auftrag_anstossen(
            config=client.app.state.config, repositories=repos,
            discovery=client.app.state.discovery,
            generierungen=client.app.state.generierungen, registry=registry,
            agent=agenten_laden(*config.agentenverzeichnisse)["recherche"],
            task=AUFGABE, endpoint_id=agentenserver.ENDPUNKT_ID,
            user_id=STANDARD_BENUTZER, sprache="de",
        )

    # The agent server answers: the line names it, and the run lands there.
    angezeigt = client.get(
        frage, params={"endpoint_id": agentenserver.ENDPUNKT_ID}
    ).json()
    assert angezeigt["endpoint_id"] == agentenserver.ENDPUNKT_ID
    auftrag = starten()
    await _bis_beendet(repos, auftrag.id)
    assert auftrag.endpoint_id == angezeigt["endpoint_id"]

    # And with it gone, both name the main model the run takes over to.
    client.app.state.discovery.zustaende[agentenserver.ENDPUNKT_ID].erreichbar = False
    angezeigt = client.get(
        frage, params={"endpoint_id": agentenserver.ENDPUNKT_ID}
    ).json()
    assert angezeigt["endpoint_id"].startswith(agentenmodellwahl.HAUPTMODELL)
    auftrag = starten()
    await _bis_beendet(repos, auftrag.id)
    assert auftrag.endpoint_id == angezeigt["endpoint_id"]


async def test_die_handwahl_des_agentenservers_faellt_auf_das_hauptmodell(
    config, client
):
    """The start window preselects the agent server, and nobody chose that
    preselection. With the agent server not up, the run goes to the main
    model instead of being refused at it — if the agent server drops out, the
    main model takes over — the pick is the first entry of the order, not a
    claim that this server is running."""
    agent_schreiben(config)
    registry = werkzeuge_an(client)
    provider_setzen(client, MockProvider(mock_endpunkt("test"), haeppchen=["Ok."]))
    await client.app.state.discovery.anmelden(
        mock_endpunkt(agentenmodellwahl.HAUPTMODELL)
    )
    agentenmodell_leer(client)

    repos = client.app.state.repositories
    auftrag = auftrag_anstossen(
        config=client.app.state.config, repositories=repos,
        discovery=client.app.state.discovery,
        generierungen=client.app.state.generierungen, registry=registry,
        agent=agenten_laden(*config.agentenverzeichnisse)["recherche"],
        task=AUFGABE, endpoint_id=agentenserver.ENDPUNKT_ID,
        user_id=STANDARD_BENUTZER, sprache="de",
    )
    await _bis_beendet(repos, auftrag.id)

    assert auftrag.endpoint_id.startswith(agentenmodellwahl.HAUPTMODELL)


async def test_eine_slot_datei_im_feld_wartet_auf_ihren_server(config, client):
    """A slot FILE in the field is not a pick of the agent server: the field
    says "this program holds this file" and the autostart brings it up, so a
    run somebody configured waits for it instead of quietly going elsewhere.

    Both answer with the agent server's id, which is why they have to be told
    apart by WHERE the id came from — the window's preselection falls through
    (the test below), the field's own file does not."""
    agent_schreiben(config)
    registry = werkzeuge_an(client)
    provider_setzen(client, MockProvider(mock_endpunkt("test"), haeppchen=["Ok."]))
    await client.app.state.discovery.anmelden(
        mock_endpunkt(agentenmodellwahl.HAUPTMODELL)
    )
    agentenmodell_setzen(client, "noch-nicht-geladen.gguf", sorte="slot")

    with pytest.raises(HTTPException) as fehler:
        auftrag_anstossen(
            config=client.app.state.config,
            repositories=client.app.state.repositories,
            discovery=client.app.state.discovery,
            generierungen=client.app.state.generierungen, registry=registry,
            agent=agenten_laden(*config.agentenverzeichnisse)["recherche"],
            task=AUFGABE, endpoint_id=None, user_id=STANDARD_BENUTZER, sprache="de",
        )
    assert fehler.value.status_code == 404


async def test_ein_fremdes_modell_ohne_werkzeuge_wird_nicht_genommen(config, client):
    """The field names ``fremd:klein`` — an id WITH a model part, which the
    order keeps for ``runner:B``. A foreign id that failed the tool check must
    not travel on that guard: it answers out of its own head and the job reads
    'fertig'. The run goes to the main model."""
    agent_schreiben(config)
    registry = werkzeuge_an(client)
    provider_setzen(client, MockProvider(mock_endpunkt("test"), haeppchen=["Ok."]))
    await client.app.state.discovery.anmelden(mock_endpunkt("fremd"))
    provider_setzen(
        client, MockProvider(mock_endpunkt("fremd"), haeppchen=["Ok."]),
        endpoint_id="fremd",
    )
    werkzeugfaehig(client, "fremd", False)
    await client.app.state.discovery.anmelden(
        mock_endpunkt(agentenmodellwahl.HAUPTMODELL)
    )
    agentenmodell_setzen(client, "fremd:klein")

    repos = client.app.state.repositories
    auftrag = auftrag_anstossen(
        config=client.app.state.config, repositories=repos,
        discovery=client.app.state.discovery,
        generierungen=client.app.state.generierungen, registry=registry,
        agent=agenten_laden(*config.agentenverzeichnisse)["recherche"],
        task=AUFGABE, endpoint_id=None, user_id=STANDARD_BENUTZER, sprache="de",
    )
    await _bis_beendet(repos, auftrag.id)

    assert auftrag.endpoint_id.startswith(agentenmodellwahl.HAUPTMODELL)


async def test_eine_leere_kennung_ist_keine_handwahl(config, client):
    """``endpoint_id=""`` is what a request without a pick looks like once a
    query string kept its key (the preview route declares it as one). Read as
    a pick, the same call would skip the tool rule it gets without the
    parameter — and the run would land on the server that cannot call tools."""
    agent_schreiben(config)
    registry = werkzeuge_an(client)
    provider_setzen(client, MockProvider(mock_endpunkt("test"), haeppchen=["Ok."]))
    await client.app.state.discovery.anmelden(mock_endpunkt("fremd"))
    provider_setzen(
        client, MockProvider(mock_endpunkt("fremd"), haeppchen=["Ok."]),
        endpoint_id="fremd",
    )
    werkzeugfaehig(client, "fremd", False)
    await client.app.state.discovery.anmelden(
        mock_endpunkt(agentenmodellwahl.HAUPTMODELL)
    )
    agentenmodell_setzen(client, "fremd")

    repos = client.app.state.repositories
    auftrag = auftrag_anstossen(
        config=client.app.state.config, repositories=repos,
        discovery=client.app.state.discovery,
        generierungen=client.app.state.generierungen, registry=registry,
        agent=agenten_laden(*config.agentenverzeichnisse)["recherche"],
        task=AUFGABE, endpoint_id="", user_id=STANDARD_BENUTZER, sprache="de",
    )
    await _bis_beendet(repos, auftrag.id)

    assert auftrag.endpoint_id.startswith(agentenmodellwahl.HAUPTMODELL)


async def test_ein_agentenserver_ohne_werkzeuge_geht_an_das_hauptmodell(
    config, client
):
    """A run that USES tools may not land on a server that cannot call them:
    it would answer out of its own head and report 'fertig'. The
    order therefore walks past the agent server and takes the main model —
    the two servers are the only entries, and the tool question decides
    between them."""
    agent_schreiben(config)
    registry = werkzeuge_an(client)
    provider_setzen(client, MockProvider(mock_endpunkt("test"), haeppchen=["Ok."]))
    await client.app.state.discovery.anmelden(mock_endpunkt(agentenserver.ENDPUNKT_ID))
    provider_setzen(
        client,
        MockProvider(mock_endpunkt(agentenserver.ENDPUNKT_ID), haeppchen=["Ok."]),
        endpoint_id=agentenserver.ENDPUNKT_ID,
    )
    werkzeugfaehig(client, agentenserver.ENDPUNKT_ID, False)
    await client.app.state.discovery.anmelden(
        mock_endpunkt(agentenmodellwahl.HAUPTMODELL)
    )
    werkzeugfaehig(client, agentenmodellwahl.HAUPTMODELL, True)
    agentenmodell_leer(client)

    repos = client.app.state.repositories
    auftrag = auftrag_anstossen(
        config=client.app.state.config, repositories=repos,
        discovery=client.app.state.discovery,
        generierungen=client.app.state.generierungen, registry=registry,
        agent=agenten_laden(*config.agentenverzeichnisse)["recherche"],
        task=AUFGABE, endpoint_id=None, user_id=STANDARD_BENUTZER, sprache="de",
    )
    await _bis_beendet(repos, auftrag.id)

    assert auftrag.endpoint_id.startswith(agentenmodellwahl.HAUPTMODELL)


async def test_ein_hauptmodell_ohne_werkzeuge_geht_an_den_agentenserver(
    config, client
):
    """A main model that answers but cannot call tools is not "the main model"
    for a run that needs them. The run goes to the tool-capable agent server
    instead of answering out of the model's own head — the mirror image of
    the test above, and the reason the order is a rule and not a preference."""
    agent_schreiben(config)
    registry = werkzeuge_an(client)
    provider_setzen(client, MockProvider(mock_endpunkt("test"), haeppchen=["Ok."]))
    await client.app.state.discovery.anmelden(mock_endpunkt(agentenserver.ENDPUNKT_ID))
    provider_setzen(
        client,
        MockProvider(mock_endpunkt(agentenserver.ENDPUNKT_ID), haeppchen=["Ok."]),
        endpoint_id=agentenserver.ENDPUNKT_ID,
    )
    werkzeugfaehig(client, agentenserver.ENDPUNKT_ID, True)
    await client.app.state.discovery.anmelden(
        mock_endpunkt(agentenmodellwahl.HAUPTMODELL)
    )
    werkzeugfaehig(client, agentenmodellwahl.HAUPTMODELL, False)
    agentenmodell_leer(client)

    repos = client.app.state.repositories
    auftrag = auftrag_anstossen(
        config=client.app.state.config, repositories=repos,
        discovery=client.app.state.discovery,
        generierungen=client.app.state.generierungen, registry=registry,
        agent=agenten_laden(*config.agentenverzeichnisse)["recherche"],
        task=AUFGABE, endpoint_id=None, user_id=STANDARD_BENUTZER, sprache="de",
    )
    await _bis_beendet(repos, auftrag.id)

    assert auftrag.endpoint_id == agentenserver.ENDPUNKT_ID


async def test_ein_werkzeugfaehiges_feld_bleibt_das_feld(config, client):
    """The counter-check: where the field's own endpoint CAN call tools,
    nothing is overruled — it runs where it was told to."""
    agent_schreiben(config)
    registry = werkzeuge_an(client)
    await client.app.state.discovery.anmelden(mock_endpunkt("zweit"))
    provider_setzen(client, MockProvider(mock_endpunkt("test"), haeppchen=["Ok."]))
    werkzeugfaehig(client, "test", True)

    repos = client.app.state.repositories
    auftrag = auftrag_anstossen(
        config=client.app.state.config, repositories=repos,
        discovery=client.app.state.discovery,
        generierungen=client.app.state.generierungen, registry=registry,
        agent=agenten_laden(*config.agentenverzeichnisse)["recherche"],
        task=AUFGABE, endpoint_id=None, user_id=STANDARD_BENUTZER, sprache="de",
    )
    await _bis_beendet(repos, auftrag.id)

    assert auftrag.endpoint_id.startswith("test")


def gleich_faellig(client) -> datetime:
    """A moment far enough past an entry's creation that its ``*/15``
    schedule really has a due time behind it."""
    name = client.app.state.config.app.timezone
    from zoneinfo import ZoneInfo

    jetzt = datetime.now(ZoneInfo(name)) if name else datetime.now().astimezone()
    return jetzt + timedelta(hours=1)


async def test_ohne_werkzeugfaehiges_modell_wartet_der_termin(config, client):
    """Nothing to run this on: the due time stays open and the entry says
    what it is waiting for. Before, the pre-flight check called this ready,
    the start then refused it with 400, and the entry showed nothing at
    all — a schedule that had simply stopped firing."""
    agent_schreiben(config)
    werkzeuge_an(client)
    provider_setzen(client, MockProvider(mock_endpunkt("test"), haeppchen=["Ok."]))
    werkzeugfaehig(client, "test", False)
    repos = client.app.state.repositories
    eintrag = eintrag_anlegen(repos, ziel=None)

    await cronablauf.einmal_pruefen(client.app, gleich_faellig(client))

    assert repos.auftraege.auflisten(user_id=STANDARD_BENUTZER) == []
    assert cronablauf.wartet_auf_modell(eintrag.id) is True


async def test_mit_werkzeugfaehigem_modell_feuert_der_termin(config, client):
    """The counter-check on the same setup: capability is the only thing
    that changes, and the due time fires."""
    agent_schreiben(config)
    werkzeuge_an(client)
    provider_setzen(client, MockProvider(mock_endpunkt("test"), haeppchen=["Ok."]))
    werkzeugfaehig(client, "test", True)
    repos = client.app.state.repositories
    eintrag = eintrag_anlegen(repos, ziel=None)

    await cronablauf.einmal_pruefen(client.app, gleich_faellig(client))

    (auftrag,) = repos.auftraege.auflisten(user_id=STANDARD_BENUTZER)
    assert cronablauf.wartet_auf_modell(eintrag.id) is False
    # The fired run keeps streaming in its own background task after this
    # check — left running past the end of the test, it and the loop it
    # depends on would be torn down together with it still mid-flight.
    await _bis_beendet(repos, auftrag.id)


# --- A finished chain row must not fire a second time ---------------


async def test_eine_abgearbeitete_kettenzeile_bleibt_nicht_aktiv(
    config, client, gemeldet
):
    """A chain run that ends at the round limit writes no continuation. The
    row it ran on has nothing left to do — and left active it would fire
    again tomorrow at the daily time ``bald()`` gave it, with the stale
    handoff text."""
    agent_schreiben(config, kopf="max_rounds: 3")
    repos = client.app.state.repositories
    ursprung = eintrag_anlegen(repos, ziel=None)
    ueberlauf(client)

    await lauf_starten(client, config, ursprung.id)
    kette = kette_von(repos, ursprung.id)
    # It IS the continuation at this point, and it has to run.
    assert kette.aktiv is True

    agent_schreiben(config, kopf="max_rounds: 1")
    provider_setzen(client, ImmerNotiz(mock_endpunkt("test")))
    auftrag = await lauf_starten(client, config, kette.id)
    assert repos.auftraege.holen(auftrag.id).ende_grund == "rundengrenze"

    assert repos.cronjobs.holen(kette.id).aktiv is False
    # And gone from the very list the firing loop walks.
    faellig = {e.id for e in repos.cronjobs.aktive()}
    assert kette.id not in faellig
    # Untouched: the entry a person made comes back tomorrow.
    assert ursprung.id in faellig
    assert repos.cronjobs.holen(ursprung.id).aktiv is True


async def test_eine_kette_mit_fortsetzung_bleibt_aktiv(config, client):
    """The counter-check: a run that DID hand its work on keeps its row —
    that row is the continuation, and switching it off would end the chain
    the run just wrote."""
    agent_schreiben(config, kopf="max_rounds: 3")
    repos = client.app.state.repositories
    ursprung = eintrag_anlegen(repos, ziel=None)
    ueberlauf(client)

    await lauf_starten(client, config, ursprung.id)
    kette = kette_von(repos, ursprung.id)
    await lauf_starten(client, config, kette.id)

    assert repos.cronjobs.holen(kette.id).aktiv is True


# --- One announcement, not two -------------------------------------


def kette_zu(repos, ursprung):
    """A continuation of this entry, made the way the two handoff sites make
    one (``zwischenstand.kettenfelder``)."""
    return repos.cronjobs.erstellen(
        agent=ursprung.agent, task=f"Continue this job. Original task: {ursprung.task}",
        zeitplan="08:00", herkunft="agent", basisaufgabe=ursprung.task,
        **zwischenstand.kettenfelder(ursprung, "erstlauf"),
    )


async def test_kette_und_ursprung_an_der_grenze_melden_einmal(repos, gemeldet):
    """Both reach their limit in the same booking. One sentence goes out,
    and it is the origin's — the row a person made, and the only one for
    which "this schedule has stopped" is a true statement."""
    # On 'announce': the limit's sentence is a notification like every
    # other, and an entry on 'log' gets it in the log alone. Which of the
    # two rows speaks is what this test is about. The chain inherits
    # ``deliver`` from the origin
    # (``kettenfelder``), so setting it here sets it for both.
    ursprung = eintrag_anlegen(
        repos, ziel=None, fehlergrenze=1, deliver="announce"
    )
    kette = kette_zu(repos, ursprung)

    gemeldet_zurueck = await cronablauf.ausgang_verbuchen(
        repos, kette.id, AUFGABE, erfolgreich=False
    )

    assert gemeldet == [(f"{AUFGABE} - stopped after 1 failed run", False)]
    assert gemeldet_zurueck is True
    # Silence is not a skipped booking: both rows are counted and both are
    # switched off, exactly as before.
    assert repos.cronjobs.holen(kette.id).fehlversuche == 1
    assert repos.cronjobs.holen(kette.id).aktiv is False
    assert repos.cronjobs.holen(ursprung.id).fehlversuche == 1
    assert repos.cronjobs.holen(ursprung.id).aktiv is False


async def test_die_kette_meldet_nicht_fuer_einen_ursprung_der_weiterlaeuft(
    repos, gemeldet
):
    """The worse half of the same fault: the chain at its limit next to an
    origin nowhere near its own said "stopped after 2 failed runs" about a
    schedule that runs again tomorrow."""
    # On 'announce': on the default 'log' nothing reaches the announcing
    # module at all (``_mitteilen``), so the empty list said
    # nothing about which row speaks — the chain could have announced for
    # this running origin and the test would still have been green. The
    # chain inherits ``deliver`` (``kettenfelder``), so setting it on the
    # origin sets it for both.
    ursprung = eintrag_anlegen(repos, ziel=None, fehlergrenze=2, deliver="announce")
    kette = kette_zu(repos, ursprung)
    repos.cronjobs.fehlversuch_zaehlen(kette.id)  # one already behind it

    await cronablauf.ausgang_verbuchen(repos, kette.id, AUFGABE, erfolgreich=False)

    assert gemeldet == []
    assert repos.cronjobs.holen(kette.id).aktiv is False
    assert repos.cronjobs.holen(ursprung.id).aktiv is True


async def test_ohne_ursprung_meldet_die_kette_selbst(repos, gemeldet):
    """A job nobody scheduled writes a continuation whose origin is that
    run — and a run is no entry, so the chain row is the only one there is,
    and it says it itself."""
    kette = repos.cronjobs.erstellen(
        agent="recherche", task="Continue this job.", zeitplan="08:00",
        herkunft="agent", basisaufgabe=AUFGABE, fehlergrenze=1,
        # And on 'announce': 'log' is silent everywhere.
        deliver="announce",
        **{k: v for k, v in zwischenstand.kettenfelder(None, "erstlauf").items()
           if k not in {"fehlergrenze", "deliver"}},
    )

    await cronablauf.ausgang_verbuchen(repos, kette.id, AUFGABE, erfolgreich=False)

    assert gemeldet == [(f"{AUFGABE} - stopped after 1 failed run", False)]


# --- `deliver` · one piece of work, one announcement -------------------------
#
# An `announce` entry whose run hands its work on used to say it twice — once
# from the run that ran out of room, once from the continuation that finished
# it. With a provider that stays dead the chain restarts every couple of
# minutes, so ONE job could put ten notifications into the machine's
# notification centre in a day. The run that hands off is not an ending and
# stays quiet; whichever run really ends is the one that speaks.


async def test_eine_uebergebene_arbeit_meldet_sich_einmal_am_ende(
    config, client, gemeldet
):
    """The overflow path end to end: the run that hands the rest of the work
    to a continuation says nothing, the continuation that finishes says it —
    once, with the entry's own task text and the success sound."""
    agent_schreiben(config)
    repos = client.app.state.repositories
    ursprung = eintrag_anlegen(repos, ziel=None, deliver="announce")

    ueberlauf(client)
    await lauf_starten(client, config, ursprung.id)
    kette = kette_von(repos, ursprung.id)
    # The chain inherits the setting — the silence below is the guard, not
    # a chain that was never going to announce anyway.
    assert kette.deliver == "announce"
    assert gemeldet == []

    provider_setzen(client, MockProvider(mock_endpunkt("test")))
    auftrag = await lauf_starten(client, config, kette.id)

    assert repos.auftraege.holen(auftrag.id).zustand == "fertig"
    assert gemeldet == [(AUFGABE, True)]


async def test_auf_log_meldet_auch_die_fortsetzung_nichts(config, client, gemeldet):
    """The counter-check on the default: 'log' never reaches the announcing
    module at all, before and after the guard alike."""
    agent_schreiben(config)
    repos = client.app.state.repositories
    ursprung = eintrag_anlegen(repos, ziel=None, deliver="log")

    ueberlauf(client)
    await lauf_starten(client, config, ursprung.id)
    kette = kette_von(repos, ursprung.id)
    provider_setzen(client, MockProvider(mock_endpunkt("test")))
    await lauf_starten(client, config, kette.id)

    assert kette.deliver == "log"
    assert gemeldet == []


# --- The pre-check and the start, one answer --------------------------------
#
# The fallback lost its loop over every reachable endpoint, and
# `_modell_bereit` still carried the same loop. Left there it answered
# "ready" for a schedule the start then refused: the due time stays open,
# nothing is booked, nothing is shown, and the warning repeats on every tick
# for ever — the case the comment above `_modell_bereit` already forbids.


async def test_die_cron_vorpruefung_geht_mit_dem_agentenserver(config, client):
    """Without the main model the start takes our agent server — so the
    pre-check has to call that same schedule 'ready'. Saying 'not ready' here
    would leave the due time open and repeat its warning on every tick for a
    run the start would have taken."""
    agent_schreiben(config)
    werkzeuge_an(client)
    provider_setzen(client, MockProvider(mock_endpunkt("test"), haeppchen=["Ok."]))
    await client.app.state.discovery.anmelden(mock_endpunkt(agentenserver.ENDPUNKT_ID))
    provider_setzen(
        client,
        MockProvider(mock_endpunkt(agentenserver.ENDPUNKT_ID), haeppchen=["Ok."]),
        endpoint_id=agentenserver.ENDPUNKT_ID,
    )
    agentenmodell_leer(client)

    agent = agenten_laden(*config.agentenverzeichnisse)["recherche"]

    assert cronablauf._modell_bereit(client.app, agent) is True


async def test_die_cron_vorpruefung_wartet_ohne_lokalen_endpunkt(config, client):
    """A reachable cloud endpoint is not a replacement: the start refuses
    that run, so the pre-check has to wait — the counter-check to the test
    above, without which 'ready' would mean nothing."""
    agent_schreiben(config)
    werkzeuge_an(client)
    provider_setzen(client, MockProvider(mock_endpunkt("test"), haeppchen=["Ok."]))
    await client.app.state.discovery.anmelden(mock_endpunkt("wolke", group="cloud"))
    agentenmodell_leer(client)

    agent = agenten_laden(*config.agentenverzeichnisse)["recherche"]

    assert cronablauf._modell_bereit(client.app, agent) is False


async def test_die_cron_vorpruefung_geht_mit_hauptmodell(config, client):
    """The counter-check: with the main model answering, the same schedule is
    ready — the pre-check has not simply been turned off."""
    agent_schreiben(config)
    werkzeuge_an(client)
    provider_setzen(client, MockProvider(mock_endpunkt("test"), haeppchen=["Ok."]))
    await client.app.state.discovery.anmelden(mock_endpunkt("zweit"))
    await client.app.state.discovery.anmelden(
        mock_endpunkt(agentenmodellwahl.HAUPTMODELL)
    )
    agentenmodell_leer(client)

    agent = agenten_laden(*config.agentenverzeichnisse)["recherche"]

    assert cronablauf._modell_bereit(client.app, agent) is True


async def test_die_cron_vorpruefung_wartet_auf_werkzeuge(config, client):
    """The other half of the same line: the main model answers, but it
    cannot call the tools this run would be handed — and neither can the
    only local endpoint beside it. There is nothing this run could work on,
    so the pre-check waits rather than report 'go'."""
    agent_schreiben(config)
    werkzeuge_an(client)
    provider_setzen(client, MockProvider(mock_endpunkt("test"), haeppchen=["Ok."]))
    await client.app.state.discovery.anmelden(
        mock_endpunkt(agentenmodellwahl.HAUPTMODELL)
    )
    werkzeugfaehig(client, agentenmodellwahl.HAUPTMODELL, False)
    agentenmodell_leer(client)

    agent = agenten_laden(*config.agentenverzeichnisse)["recherche"]

    assert cronablauf._modell_bereit(client.app, agent) is False


async def test_die_cron_vorpruefung_geht_mit_dem_agentenserver_ohne_werkzeuge(
    config, client
):
    """A tool-less main model beside our agent server that CAN call tools:
    the run goes to the agent server, so the pre-check has to say ready. It
    said "not ready" while the start ran the very same schedule — the due
    time stayed open, nothing was booked, and the warning repeated on every
    tick."""
    agent_schreiben(config)
    werkzeuge_an(client)
    provider_setzen(client, MockProvider(mock_endpunkt("test"), haeppchen=["Ok."]))
    await client.app.state.discovery.anmelden(mock_endpunkt(agentenserver.ENDPUNKT_ID))
    provider_setzen(
        client,
        MockProvider(mock_endpunkt(agentenserver.ENDPUNKT_ID), haeppchen=["Ok."]),
        endpoint_id=agentenserver.ENDPUNKT_ID,
    )
    werkzeugfaehig(client, agentenserver.ENDPUNKT_ID, True)
    await client.app.state.discovery.anmelden(
        mock_endpunkt(agentenmodellwahl.HAUPTMODELL)
    )
    werkzeugfaehig(client, agentenmodellwahl.HAUPTMODELL, False)
    agentenmodell_leer(client)

    agent = agenten_laden(*config.agentenverzeichnisse)["recherche"]

    assert cronablauf._modell_bereit(client.app, agent) is True


async def test_ein_gemeldeter_name_ausserhalb_des_katalogs_haelt_den_lauf_nicht_auf(
    config, client
):
    """The order hands the main server out under its reported model name —
    but only while the server also lists it. A name it does not offer
    resolves to nothing, and an id that resolves to nothing is a run that
    cannot start: the bare endpoint id is handed out instead, and that one
    resolves always."""
    agent_schreiben(config)
    werkzeuge_an(client)
    provider_setzen(client, MockProvider(mock_endpunkt("test"), haeppchen=["Ok."]))
    await client.app.state.discovery.anmelden(
        mock_endpunkt(agentenmodellwahl.HAUPTMODELL)
    )
    agentenmodell_leer(client)
    zustand = client.app.state.discovery.zustaende[agentenmodellwahl.HAUPTMODELL]
    zustand.gemeldeter_name = "alias-vom-server"
    zustand.modelle = ["der-andere-name"]

    agent = agenten_laden(*config.agentenverzeichnisse)["recherche"]

    assert (
        agentenmodellwahl.rueckfall(
            client.app.state.discovery,
            slot_id=agentenserver.ENDPUNKT_ID,
            werkzeuge=True,
        )
        == agentenmodellwahl.HAUPTMODELL
    )
    assert cronablauf._modell_bereit(client.app, agent) is True


async def test_eine_handwahl_des_hauptmodells_faellt_auf_den_agentenserver(
    config, client
):
    """The main model picked BY HAND is the same run as nothing picked at
    all: what is being asked for is the server this program starts itself,
    and it is not up. The run then takes our agent server instead of being
    refused with 503 — the hand pick is not a claim that the server IS
    running, and the two servers are the only ones either way."""
    agent_schreiben(config)
    registry = werkzeuge_an(client)
    provider_setzen(client, MockProvider(mock_endpunkt("test"), haeppchen=["Ok."]))
    await client.app.state.discovery.anmelden(mock_endpunkt(agentenserver.ENDPUNKT_ID))
    provider_setzen(
        client,
        MockProvider(mock_endpunkt(agentenserver.ENDPUNKT_ID), haeppchen=["Ok."]),
        endpoint_id=agentenserver.ENDPUNKT_ID,
    )
    agentenmodell_leer(client)

    repos = client.app.state.repositories
    auftrag = auftrag_anstossen(
        config=client.app.state.config, repositories=repos,
        discovery=client.app.state.discovery,
        generierungen=client.app.state.generierungen, registry=registry,
        agent=agenten_laden(*config.agentenverzeichnisse)["recherche"],
        task=AUFGABE, endpoint_id=agentenmodellwahl.HAUPTMODELL,
        user_id=STANDARD_BENUTZER, sprache="de",
    )
    await _bis_beendet(repos, auftrag.id)

    assert auftrag.endpoint_id == agentenserver.ENDPUNKT_ID


async def test_eine_handwahl_des_geladenen_modells_bleibt_dieses_modell(
    config, client
):
    """The main server reports several models and is handed out as
    `runner:<modell>` per model. A hand pick of `runner:B` is a choice of B;
    writing the reported name over it would run A — the model the server
    happens to hold loaded — one second after somebody picked B."""
    agent_schreiben(config)
    registry = werkzeuge_an(client)
    provider_setzen(client, MockProvider(mock_endpunkt("test"), haeppchen=["Ok."]))
    await client.app.state.discovery.anmelden(
        mock_endpunkt(agentenmodellwahl.HAUPTMODELL)
    )
    provider_setzen(
        client,
        MockProvider(mock_endpunkt(agentenmodellwahl.HAUPTMODELL), haeppchen=["Ok."]),
        endpoint_id=agentenmodellwahl.HAUPTMODELL,
    )
    zustand = client.app.state.discovery.zustaende[agentenmodellwahl.HAUPTMODELL]
    zustand.modelle = ["A", "B"]
    zustand.gemeldeter_name = "A"
    agentenmodell_leer(client)

    gewaehlt = f"{agentenmodellwahl.HAUPTMODELL}:B"
    repos = client.app.state.repositories
    auftrag = auftrag_anstossen(
        config=client.app.state.config, repositories=repos,
        discovery=client.app.state.discovery,
        generierungen=client.app.state.generierungen, registry=registry,
        agent=agenten_laden(*config.agentenverzeichnisse)["recherche"],
        task=AUFGABE, endpoint_id=gewaehlt, user_id=STANDARD_BENUTZER, sprache="de",
    )
    await _bis_beendet(repos, auftrag.id)

    assert auftrag.endpoint_id == gewaehlt


# --- The first entry of the start window means the model the field names ---


def _lauf_aus_dem_fenster(client, config, registry, endpoint_id):
    """One start with the pick the start window sends, and the preview route
    asked the same question — with the tool rule, as the window asks it for an
    agent that works through tools."""
    repos = client.app.state.repositories
    angezeigt = client.get(
        "/api/v1/jobs/laufmodell",
        params={"endpoint_id": endpoint_id, "werkzeuge": True},
    ).json()
    auftrag = auftrag_anstossen(
        config=client.app.state.config, repositories=repos,
        discovery=client.app.state.discovery,
        generierungen=client.app.state.generierungen, registry=registry,
        agent=agenten_laden(*config.agentenverzeichnisse)["recherche"],
        task=AUFGABE, endpoint_id=endpoint_id,
        user_id=STANDARD_BENUTZER, sprache="de",
    )
    return repos, auftrag, angezeigt


async def _fremdes_agentenmodell(client, *, hauptmodell_laeuft: bool, faehig: bool = True):
    """A model of its own in the field, on an endpoint that is neither of our
    two servers; the agent server is not there."""
    await client.app.state.discovery.anmelden(mock_endpunkt("wolke", group="cloud"))
    provider_setzen(
        client, MockProvider(mock_endpunkt("wolke"), haeppchen=["Ok."]),
        endpoint_id="wolke",
    )
    werkzeugfaehig(client, "wolke", faehig)
    if hauptmodell_laeuft:
        await client.app.state.discovery.anmelden(
            mock_endpunkt(agentenmodellwahl.HAUPTMODELL)
        )
    agentenmodell_setzen(client, "wolke")


@pytest.mark.parametrize("hauptmodell_laeuft", [False, True])
async def test_the_first_entry_runs_on_the_model_of_the_field_when_it_is_a_cloud_model(
    config, client, hauptmodell_laeuft
):
    """The window sends the agent server as its pick, the field names a cloud
    model and no local server is there (or only the main one): the run books
    on the cloud model and the preview names the same endpoint, instead of the
    window saying that no model is reachable."""
    agent_schreiben(config)
    registry = werkzeuge_an(client)
    await _fremdes_agentenmodell(client, hauptmodell_laeuft=hauptmodell_laeuft)

    repos, auftrag, angezeigt = _lauf_aus_dem_fenster(
        client, config, registry, agentenserver.ENDPUNKT_ID
    )
    await _bis_beendet(repos, auftrag.id)

    assert angezeigt["endpoint_id"] == "wolke"
    assert auftrag.endpoint_id == "wolke"


async def test_the_first_entry_keeps_the_tool_rule_of_the_field(config, client):
    """A cloud model in the field that cannot call tools, an agent that works
    through tools: the run goes the way a start from a chat goes, to the main
    model — the pick of the window does not lift the rule."""
    agent_schreiben(config)
    registry = werkzeuge_an(client)
    await _fremdes_agentenmodell(client, hauptmodell_laeuft=True, faehig=False)

    repos, auftrag, angezeigt = _lauf_aus_dem_fenster(
        client, config, registry, agentenserver.ENDPUNKT_ID
    )
    await _bis_beendet(repos, auftrag.id)

    assert auftrag.endpoint_id.startswith(agentenmodellwahl.HAUPTMODELL)
    assert angezeigt["endpoint_id"] == auftrag.endpoint_id


async def test_the_first_entry_with_a_slot_file_in_the_field_still_falls_to_the_main_model(
    config, client
):
    """The field names a file of the agent server and that server is not up:
    the entry means the agent server, so the main model takes over as before."""
    agent_schreiben(config)
    registry = werkzeuge_an(client)
    provider_setzen(client, MockProvider(mock_endpunkt("test"), haeppchen=["Ok."]))
    await client.app.state.discovery.anmelden(
        mock_endpunkt(agentenmodellwahl.HAUPTMODELL)
    )
    agentenmodell_setzen(client, "noch-nicht-geladen.gguf", sorte="slot")

    repos, auftrag, angezeigt = _lauf_aus_dem_fenster(
        client, config, registry, agentenserver.ENDPUNKT_ID
    )
    await _bis_beendet(repos, auftrag.id)

    assert auftrag.endpoint_id.startswith(agentenmodellwahl.HAUPTMODELL)
    assert angezeigt["endpoint_id"] == auftrag.endpoint_id


async def test_the_first_entry_with_the_main_model_in_the_field_is_unchanged(config, client):
    """The field names the main model: nothing of its own, the entry is read
    as before and lands on the main model when the agent server is not up."""
    agent_schreiben(config)
    registry = werkzeuge_an(client)
    provider_setzen(client, MockProvider(mock_endpunkt("test"), haeppchen=["Ok."]))
    await client.app.state.discovery.anmelden(
        mock_endpunkt(agentenmodellwahl.HAUPTMODELL)
    )
    agentenmodell_setzen(client, agentenmodellwahl.HAUPTMODELL)

    repos, auftrag, angezeigt = _lauf_aus_dem_fenster(
        client, config, registry, agentenserver.ENDPUNKT_ID
    )
    await _bis_beendet(repos, auftrag.id)

    assert auftrag.endpoint_id.startswith(agentenmodellwahl.HAUPTMODELL)
    assert angezeigt["endpoint_id"] == auftrag.endpoint_id


async def test_the_main_model_entry_ignores_the_field_of_the_agent_model(config, client):
    """The window's other entry is a pick of the main model and stays one,
    whatever the field says."""
    agent_schreiben(config)
    registry = werkzeuge_an(client)
    await _fremdes_agentenmodell(client, hauptmodell_laeuft=True)

    repos, auftrag, angezeigt = _lauf_aus_dem_fenster(
        client, config, registry, agentenmodellwahl.HAUPTMODELL
    )
    await _bis_beendet(repos, auftrag.id)

    assert auftrag.endpoint_id.startswith(agentenmodellwahl.HAUPTMODELL)
    assert angezeigt["endpoint_id"] == auftrag.endpoint_id
