"""The persistent memory: does it reach the model, and only where it may?

Two halves are worth proving. That prompt and memory arrive as ONE system
message, because the providers disagree about a second one and Anthropic
takes a single field. And that the two switches really decide — the local
one and the cloud one, nothing finer.

The route is part of it on purpose. A settings key that nobody vouches for
comes back as 400 while the interface quietly restores its own state; that
exact bug hid behind the model switch for a whole day.
"""

from __future__ import annotations

from app import agentenmodellwahl, gedaechtnis
from app.providers import MockProvider, mock_endpunkt
from tests.conftest import lokaler_endpunkt, provider_setzen


# --- Checking the switches --------------------------------------------------


def test_nur_die_beiden_schalter_kommen_durch():
    geprueft = gedaechtnis.schalter_pruefen(
        {"lokal": True, "cloud": False, "erfunden": True}
    )
    assert geprueft == {"lokal": True, "cloud": False}


def test_was_kein_objekt_ist_gilt_als_nichts():
    assert gedaechtnis.schalter_pruefen(["lokal"]) == {}
    assert gedaechtnis.schalter_pruefen(True) == {}


def test_werte_werden_zu_echten_wahrheitswerten():
    assert gedaechtnis.schalter_pruefen({"lokal": 1, "cloud": ""}) == {
        "lokal": True,
        "cloud": False,
    }


# --- Assembling into one system message -------------------------------------


def test_prompt_und_gedaechtnis_werden_eine_nachricht():
    zusammen = gedaechtnis.anhaengen("Du bist knapp.", "## Rules\n- Englisch.")
    assert zusammen.startswith("Du bist knapp.")
    assert "## Rules" in zusammen
    assert gedaechtnis.EINLEITUNG in zusammen


def test_ohne_gedaechtnis_bleibt_der_prompt_unberuehrt():
    assert gedaechtnis.anhaengen("Du bist knapp.", "") == "Du bist knapp."
    assert gedaechtnis.anhaengen("Du bist knapp.", "   ") == "Du bist knapp."


def test_ohne_prompt_steht_das_gedaechtnis_allein():
    zusammen = gedaechtnis.anhaengen("", "## Facts\n- Arbeitet am Mac.")
    assert zusammen.startswith(gedaechtnis.EINLEITUNG)
    assert "Arbeitet am Mac" in zusammen


# --- The default: on, here and out there ------------------------------------


class _Endpunkt:
    def __init__(self, group: str) -> None:
        self.group = group


class _Zustand:
    def __init__(self, group: str) -> None:
        self.endpunkt = _Endpunkt(group)


def test_the_memory_travels_to_both_sides_from_the_start(repos):
    assert gedaechtnis.mitschicken(repos, _Zustand("local")) is True
    assert gedaechtnis.mitschicken(repos, _Zustand("cloud")) is True


def test_a_side_switched_off_stays_home_and_the_other_still_travels(repos):
    repos.einstellungen.setzen("global", gedaechtnis.SCHLUESSEL, {"lokal": True, "cloud": False})
    assert gedaechtnis.mitschicken(repos, _Zustand("local")) is True
    assert gedaechtnis.mitschicken(repos, _Zustand("cloud")) is False


def test_beide_schalter_lassen_sich_umdrehen(repos):
    repos.einstellungen.setzen(
        "global", gedaechtnis.SCHLUESSEL, {"lokal": False, "cloud": True}
    )
    assert gedaechtnis.mitschicken(repos, _Zustand("local")) is False
    assert gedaechtnis.mitschicken(repos, _Zustand("cloud")) is True


def test_ein_schalter_allein_laesst_den_anderen_in_ruhe(repos):
    """The stored value is merged key by key, so switching the cloud on does
    not silently drop what was decided about local."""
    repos.einstellungen.setzen("global", gedaechtnis.SCHLUESSEL, {"cloud": True})
    assert gedaechtnis.mitschicken(repos, _Zustand("local")) is True
    assert gedaechtnis.mitschicken(repos, _Zustand("cloud")) is True


# --- And the whole way: file -> route -> what the model is handed ------------


def _system_nachricht(provider: MockProvider) -> str:
    nachrichten = provider.letzte_anfrage.nachrichten
    system = [n for n in nachrichten if n.role == "system"]
    assert len(system) == 1, "Prompt and memory must be ONE message"
    return system[0].content


def test_das_gedaechtnis_erreicht_das_modell(client, chat_id):
    client.app.state.config.memory_schreiben("## Facts\n- The touchstone is called Prüfstein.")
    client.app.state.config.system_prompt_schreiben("Sei knapp.")
    # One of the two servers this program runs itself — the half the memory
    # travels to unasked (app/config.py LOKALE_ENDPUNKTE).
    provider = lokaler_endpunkt(
        client, MockProvider(mock_endpunkt(agentenmodellwahl.HAUPTMODELL), haeppchen=["ok"])
    )
    client.post(
        "/api/v1/chat/completions",
        json={
            "chat_id": chat_id,
            "endpoint_id": agentenmodellwahl.HAUPTMODELL,
            "content": "hallo",
        },
    )

    system = _system_nachricht(provider)
    assert "Sei knapp." in system
    assert "The touchstone is called Prüfstein." in system


def test_abgeschaltet_bleibt_es_zuhause(client, chat_id):
    client.app.state.config.memory_schreiben("## Facts\n- Geheim.")
    client.app.state.config.system_prompt_schreiben("Sei knapp.")
    client.put(
        "/api/v1/settings/global/gedaechtnis", json={"wert": {"lokal": False}}
    )

    provider = lokaler_endpunkt(
        client, MockProvider(mock_endpunkt(agentenmodellwahl.HAUPTMODELL), haeppchen=["ok"])
    )
    client.post(
        "/api/v1/chat/completions",
        json={
            "chat_id": chat_id,
            "endpoint_id": agentenmodellwahl.HAUPTMODELL,
            "content": "hallo",
        },
    )

    system = _system_nachricht(provider)
    assert "Sei knapp." in system
    assert "Geheim." not in system


def test_ein_anbieter_bekommt_das_gedaechtnis_solange_es_nicht_ausgeschaltet_ist(client, chat_id):
    """An entry from the configuration is a provider, and to a provider the
    memory travels from the start, until somebody switches that off.

    The two halves in one test on purpose: with the cloud switch off it stays
    here, and the same request without it carries it — without the first
    half, a memory that travelled whatever the switch says would pass as
    well."""
    client.app.state.config.memory_schreiben("## Facts\n- Prüfstein.")
    client.app.state.config.system_prompt_schreiben("Sei knapp.")
    provider = MockProvider(mock_endpunkt("test"), haeppchen=["ok"])
    provider_setzen(client, provider)

    client.post(
        "/api/v1/chat/completions",
        json={"chat_id": chat_id, "endpoint_id": "test", "content": "hallo"},
    )
    assert "Prüfstein." in _system_nachricht(provider)

    client.put("/api/v1/settings/global/gedaechtnis", json={"wert": {"lokal": True, "cloud": False}})
    client.post(
        "/api/v1/chat/completions",
        json={"chat_id": chat_id, "endpoint_id": "test", "content": "hallo"},
    )
    assert "Prüfstein." not in _system_nachricht(provider)


def test_die_route_speichert_die_schalter(client):
    antwort = client.put(
        "/api/v1/settings/global/gedaechtnis",
        json={"wert": {"lokal": False, "cloud": True}},
    )
    assert antwort.status_code == 200, antwort.text
    assert antwort.json()["wert"] == {"lokal": False, "cloud": True}


def test_eine_fehlende_datei_ist_kein_fehler(client):
    """The as-shipped state, and the state after somebody deleted everything
    the program had learned about them."""
    assert client.app.state.config.memory_lesen() == ""


def test_the_prompt_names_the_memory_tool_only_where_the_model_has_it(client, chat_id):
    """The sentence about writing things down hangs on the tool being in the
    model's list, and the tool is there only where the memory travels. Both
    halves: without the first, a sentence that never appears would pass."""
    from app.tools.registry import WerkzeugRegistry

    config = client.app.state.config
    client.app.state.werkzeuge = WerkzeugRegistry(
        [], memory_pfad=config.pfad(config.app.memory_file)
    )
    config.features.mcp = True
    sentence = "Two things are worth writing down with memory_save"
    provider = lokaler_endpunkt(
        client, MockProvider(mock_endpunkt(agentenmodellwahl.HAUPTMODELL), haeppchen=["ok"])
    )
    client.app.state.discovery.zustaende[
        agentenmodellwahl.HAUPTMODELL
    ].endpunkt.capabilities.tool_calls = True

    def ask() -> str:
        client.post(
            "/api/v1/chat/completions",
            json={
                "chat_id": chat_id,
                "endpoint_id": agentenmodellwahl.HAUPTMODELL,
                "content": "hallo",
            },
        )
        return _system_nachricht(provider)

    assert sentence in ask()
    client.put("/api/v1/settings/global/gedaechtnis", json={"wert": {"lokal": False}})
    assert sentence not in ask()
