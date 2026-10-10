"""Picking a skill by name: what the list offers and what reaches the model.

The typed path is the one that has to work on any model, including one too
small to choose for itself — so it deliberately depends on nothing: no tool
registry, no catalogue in the prompt, no switch.
"""

from __future__ import annotations

from app import agentenmodellwahl, skills
from app.providers import MockProvider, mock_endpunkt
from tests.conftest import lokaler_endpunkt


def _skill(config, name, beschreibung="Da", anleitung="Erst dies, dann das.", auto=False):
    _, eigen = config.skillverzeichnisse
    ordner = eigen / name
    ordner.mkdir(parents=True, exist_ok=True)
    (ordner / skills.SKILL_DATEI).write_text(
        f"---\ndescription: {beschreibung}\nauto: {str(auto).lower()}\n---\n\n{anleitung}\n",
        encoding="utf-8",
    )


def _system(provider: MockProvider) -> str:
    system = [n for n in provider.letzte_anfrage.nachrichten if n.role == "system"]
    assert len(system) == 1
    return system[0].content


def _newest_turn(provider: MockProvider) -> str:
    """The newest user turn as it went out — where a picked skill stands."""
    return [n for n in provider.letzte_anfrage.nachrichten if n.role == "user"][-1].content


def _fragen(client, chat_id, **extra) -> MockProvider:
    """One question to one of the two servers this program runs itself — the
    kind the memory travels to unasked (app/config.py LOKALE_ENDPUNKTE), which
    the layer order below is read off."""
    provider = lokaler_endpunkt(
        client, MockProvider(mock_endpunkt(agentenmodellwahl.HAUPTMODELL), haeppchen=["ok"])
    )
    client.post(
        "/api/v1/chat/completions",
        json={
            "chat_id": chat_id,
            "endpoint_id": agentenmodellwahl.HAUPTMODELL,
            "content": "bitte",
            **extra,
        },
    )
    return provider


# --- the list ----------------------------------------------------------------


def test_die_liste_nennt_namen_und_einen_satz(client):
    _skill(client.app.state.config, "handoff", "Fasst das Gespräch zusammen")
    eintraege = client.get("/api/v1/skills").json()
    assert eintraege == [
        {"name": "handoff", "beschreibung": "Fasst das Gespräch zusammen", "auto": False}
    ]


def test_die_liste_schickt_die_anleitung_nicht_mit(client):
    """It is answered on every keystroke that opens the list, and nobody
    needs the full text to pick from it."""
    _skill(client.app.state.config, "handoff", anleitung="GEHEIMES VERFAHREN")
    assert "GEHEIMES" not in client.get("/api/v1/skills").text


def test_ohne_skills_ist_die_liste_leer(client):
    assert client.get("/api/v1/skills").json() == []


# --- picking one -------------------------------------------------------------


def test_die_gewaehlte_anleitung_erreicht_das_modell(client, chat_id):
    """In front of the user's words, with the note that they picked it — and
    not in the system message, whose bytes stay the same."""
    _skill(client.app.state.config, "handoff", anleitung="Erst dies, dann das.")
    provider = _fragen(client, chat_id, skill="handoff")
    turn = _newest_turn(provider)
    # Behind the date block a first turn carries, in front of the words.
    assert '[IMPORTANT: The user has invoked the "handoff" skill' in turn
    assert "Erst dies, dann das." in turn
    assert turn.endswith(f"{skills.INVOCATION_HANDOVER}\n\nbitte")
    assert "Erst dies, dann das." not in _system(provider)


def test_sie_steht_hinter_allen_anderen_schichten(client, chat_id):
    """The layers of the system message keep their order, and the picked
    instruction stands after all of them — in the user's turn, the most
    immediate thing to do."""
    _skill(client.app.state.config, "handoff", anleitung="ANLEITUNG")
    client.put("/api/v1/system-prompt", json={"text": "MEINPROMPT"})
    client.app.state.config.memory_schreiben("## Facts\n- MEINFAKT")

    provider = _fragen(client, chat_id, skill="handoff")
    text = _system(provider)
    assert text.index("MEINPROMPT") < text.index("MEINFAKT")
    assert "ANLEITUNG" not in text
    assert "ANLEITUNG" in _newest_turn(provider)


def test_the_picked_skill_leaves_the_system_message_alone(client, chat_id):
    """Picking a skill does not move the front of the request: the system
    message of the turn with it is the same bytes as the one before."""
    _skill(client.app.state.config, "handoff", anleitung="ANLEITUNG")
    before = _system(_fragen(client, chat_id))
    after = _system(_fragen(client, chat_id, skill="handoff"))
    assert before == after


def test_the_picked_skill_goes_out_again_with_its_turn(client, chat_id):
    """Written onto the turn and sent with it every time after, the way it
    first went out — the next request reads it in the same place."""
    _skill(client.app.state.config, "handoff", anleitung="ANLEITUNG")
    _fragen(client, chat_id, skill="handoff")
    provider = _fragen(client, chat_id)
    turns = [n.content for n in provider.letzte_anfrage.nachrichten if n.role == "user"]
    assert "ANLEITUNG" in turns[0]
    assert "ANLEITUNG" not in turns[-1]


def test_ohne_wahl_reist_keine_anleitung_mit(client, chat_id):
    _skill(client.app.state.config, "handoff", anleitung="ANLEITUNG")
    assert "ANLEITUNG" not in _system(_fragen(client, chat_id))


def test_die_anleitung_bleibt_nicht_im_verlauf(client, chat_id):
    """It rides along with one request. What should outlast it is the answer,
    not the instruction that produced it."""
    _skill(client.app.state.config, "handoff", anleitung="ANLEITUNG")
    _fragen(client, chat_id, skill="handoff")
    assert "ANLEITUNG" not in _system(_fragen(client, chat_id))

    gespeichert = client.get(f"/api/v1/chats/{chat_id}/messages").json()["nachrichten"]
    assert not any("ANLEITUNG" in (n.get("content") or "") for n in gespeichert)


def test_ein_erfundener_name_laesst_die_nachricht_durch(client, chat_id):
    """The message itself was still meant. Refusing it would lose it over a
    typo in something the user only added on top."""
    antwort = client.post(
        "/api/v1/chat/completions",
        json={"chat_id": chat_id, "endpoint_id": "test", "content": "bitte", "skill": "gibtsnicht"},
    )
    assert antwort.status_code == 200


def test_der_getippte_weg_braucht_keine_werkzeuge(client, chat_id):
    """No registry, no catalogue, no switch — this is the path that has to
    work on a model too small to choose for itself."""
    _skill(client.app.state.config, "handoff", anleitung="ANLEITUNG")
    client.app.state.config.features.mcp = False
    assert "ANLEITUNG" in _newest_turn(_fragen(client, chat_id, skill="handoff"))


# --- the settings mask -------------------------------------------------------


def _mitgeliefert(config, name, beschreibung="Ab Werk", anleitung="Werk.", auto=False):
    haus, _ = config.skillverzeichnisse
    ordner = haus / name
    ordner.mkdir(parents=True, exist_ok=True)
    (ordner / skills.SKILL_DATEI).write_text(
        f"---\ndescription: {beschreibung}\nauto: {str(auto).lower()}\n---\n\n{anleitung}\n",
        encoding="utf-8",
    )
    return ordner


def test_die_verwaltung_sagt_woher_eine_skill_kommt(client):
    _mitgeliefert(client.app.state.config, "handoff")
    _skill(client.app.state.config, "meine")

    zeilen = {z["name"]: z for z in client.get("/api/v1/skills/verwaltung").json()}
    assert zeilen["handoff"] == {
        "name": "handoff", "beschreibung": "Ab Werk", "auto": False,
        "eigen": False, "mitgeliefert": True,
    }
    assert zeilen["meine"]["eigen"] is True
    assert zeilen["meine"]["mitgeliefert"] is False


def test_auto_umschalten_legt_bei_einer_mitgelieferten_eine_kopie_an(client):
    """The same copy-on-edit that keeps the next update from taking the
    change back."""
    config = client.app.state.config
    haus, eigen = config.skillverzeichnisse
    _mitgeliefert(config, "handoff", anleitung="Werk.")

    antwort = client.patch("/api/v1/skills/handoff", json={"auto": True})
    assert antwort.json()["eigen"] is True
    assert (eigen / "handoff" / skills.SKILL_DATEI).is_file()
    # The shipped one is untouched, and the instruction survived the copy.
    assert "auto: false" in (haus / "handoff" / skills.SKILL_DATEI).read_text()
    geladen = skills.skills_laden(haus, eigen)["handoff"]
    assert geladen.auto is True
    assert geladen.anleitung == "Werk."


def test_die_beilagen_reisen_bei_der_kopie_mit(client):
    """A skill without the script it points at is an instruction to nothing."""
    config = client.app.state.config
    haus, eigen = config.skillverzeichnisse
    ordner = _mitgeliefert(config, "vektoren")
    (ordner / "generator.py").write_text("egal", encoding="utf-8")

    client.patch("/api/v1/skills/vektoren", json={"auto": True})
    assert (eigen / "vektoren" / "generator.py").is_file()


def test_zuruecksetzen_bringt_die_ausgelieferte_fassung_zurueck(client):
    config = client.app.state.config
    haus, eigen = config.skillverzeichnisse
    _mitgeliefert(config, "handoff", anleitung="Werk.")
    client.patch("/api/v1/skills/handoff", json={"auto": True})

    assert client.delete("/api/v1/skills/handoff").status_code == 204
    geladen = skills.skills_laden(haus, eigen)["handoff"]
    assert geladen.auto is False
    assert geladen.eigen is False


def test_ein_name_mit_pfadtrick_kommt_nicht_durch(client, tmp_path):
    """The name goes into a path. Without the check it would reach straight
    out of the skill folder.

    Some of these never get as far as the route — the router normalises them
    and answers 405. What matters is the same either way: nothing outside the
    skill folder is touched, and nothing is answered with success.
    """
    zeuge = tmp_path / "nicht-anfassen"
    zeuge.mkdir()
    (zeuge / "wichtig.txt").write_text("da", encoding="utf-8")

    for boese in ("..", "%2e%2e", "..%2Fnicht-anfassen", "Gross", "mit punkt"):
        assert client.patch(f"/api/v1/skills/{boese}", json={"auto": True}).status_code >= 400
        assert client.delete(f"/api/v1/skills/{boese}").status_code >= 400

    assert (zeuge / "wichtig.txt").is_file()


def test_eine_unbekannte_skill_gibt_es_nicht(client):
    assert client.patch("/api/v1/skills/gibtsnicht", json={"auto": True}).status_code == 404
    assert client.delete("/api/v1/skills/gibtsnicht").status_code == 404
