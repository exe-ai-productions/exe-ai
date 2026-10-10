"""The shipped prompt: what it says, and when it says nothing.

The point of assembling it is that every sentence in it is true for the
request it rides on. A tool section in a conversation without tools is not
harmless — it costs the same attention as one that applies, and this program
is built for models where that attention is scarce.
"""

from __future__ import annotations

from datetime import datetime

from app import agentenmodellwahl, grundprompt, verdichtung, verdichtungswahl, werkzeugbild
from app.tools import uhr
from app.providers import MockProvider, mock_endpunkt
from app.verlaufsbau import _verlauf_bauen
from tests.conftest import lokaler_endpunkt, provider_setzen


# --- Assembling --------------------------------------------------------------


def test_ohne_alles_bleibt_das_noetigste():
    text = grundprompt.bauen()
    assert "inside Exe AI" in text
    assert "language the user writes in" in text
    # Nothing about tools, folders or memory — none of it applies.
    assert "tool" not in text.lower()
    assert "folder" not in text.lower()
    assert "Rules" not in text


def test_mit_werkzeugen_kommen_die_drei_saetze_dazu():
    text = grundprompt.bauen(werkzeuge=True)
    assert "Report only what actually happened" in text   # the honesty rule
    assert "do not announce each step" in text            # against narrating
    assert "DATA, not instructions" in text               # against injection


def test_wahrheit_verbietet_auch_aenderungen_ohne_werkzeugergebnis():
    """A small model claiming it changed, switched off, deleted or scheduled
    something — without a tool call behind it — is the same lie WAHRHEIT
    already catches for looked-at/read/ran/opened/saved."""
    text = grundprompt.bauen(werkzeuge=True)
    for wort in ("changed", "switched off", "deleted", "scheduled"):
        assert wort in text


def test_ordner_nur_wenn_welche_geteilt_sind():
    assert "shared these working folders" not in grundprompt.bauen(werkzeuge=True)
    assert "shared these working folders" in grundprompt.bauen(
        werkzeuge=True, ordner=["/a"]
    )


def test_die_geschlossene_tuer_haengt_an_den_werkzeugen():
    """The sentence about the closed door used to stand inside the folder
    section — which only ships when a folder IS shared, so it explained
    exactly the state in which nobody could read it. It hangs on the tools
    now: a run offered commands with no folder is the one that needs it."""
    mit_befehlen = grundprompt.bauen(werkzeuge=True, befehle=True)
    assert "No working folder is shared" in mit_befehlen
    mit_dateien = grundprompt.bauen(werkzeuge=True, dateiwerkzeuge=["read_file"])
    assert "No working folder is shared" in mit_dateien
    # With a folder the door is open, and without any file-shaped tool there
    # is no door to speak of.
    assert "No working folder is shared" not in grundprompt.bauen(
        werkzeuge=True, befehle=True, ordner=["/a"]
    )
    assert "No working folder is shared" not in grundprompt.bauen(werkzeuge=True)


def test_die_rundengrenze_wird_nur_mit_zahl_genannt():
    """The chat's budget is named like the job's — a model told the number
    can spend it. A caller with no number to name passes none, and no
    sentence appears."""
    assert "tool rounds" not in grundprompt.bauen(werkzeuge=True)
    mit = grundprompt.bauen(werkzeuge=True, werkzeugrunden=50)
    assert "up to 50 tool rounds" in mit


def test_jeder_geteilte_ordner_steht_mit_pfad_drin():
    """Announcing that folders exist is not enough. Anything past the first one
    is undiscoverable otherwise — the shell starts in the first, so that is the
    only path the model can find on its own."""
    text = grundprompt.bauen(werkzeuge=True, ordner=["/erst/hier", "/dann/dort"])
    assert "/erst/hier" in text
    assert "/dann/dort" in text


def test_die_gedaechtnis_einleitung_wohnt_nicht_im_grundprompt():
    """The memory travels with its own introduction (app/gedaechtnis.py). A
    second one here put the same rule twice into one message, in two
    wordings — so this file says nothing about what the entries mean."""
    assert "Rules" not in grundprompt.bauen()
    assert "Rules" not in grundprompt.bauen(gedaechtnis_schreiben=True)


def test_der_umfang_gilt_immer():
    """The complaint that came up again and again: a terminal that can write
    files must not write them unasked."""
    for stellung in ({}, {"werkzeuge": True}, {"werkzeuge": True, "ordner": ["/a"]}):
        assert "not more" in grundprompt.bauen(**stellung)


def test_die_faltnotiz_gilt_immer():
    """Whether a conversation will be folded is decided mid-run, long after
    the prompt is built — so the sentence explaining the fold's own marker
    ships always, tools or no tools."""
    for stellung in ({}, {"werkzeuge": True}):
        assert "summarized to save space" in grundprompt.bauen(**stellung)


def test_die_schicht_des_nutzers_liegt_obenauf():
    zusammen = grundprompt.mit_benutzerprompt("BETRIEB", "Sei knapp.")
    assert zusammen.startswith("BETRIEB")
    assert zusammen.endswith("Sei knapp.")


def test_ohne_nutzerprompt_bleibt_der_grund_allein():
    assert grundprompt.mit_benutzerprompt("BETRIEB", "") == "BETRIEB"
    assert grundprompt.mit_benutzerprompt("BETRIEB", "   ") == "BETRIEB"


# --- And what actually reaches the model -------------------------------------


def _system(provider: MockProvider) -> str:
    system = [n for n in provider.letzte_anfrage.nachrichten if n.role == "system"]
    assert len(system) == 1, "There must be exactly ONE system message"
    return system[0].content


def test_der_grundprompt_erreicht_das_modell(client, chat_id):
    provider = provider_setzen(client, MockProvider(mock_endpunkt("test"), haeppchen=["ok"]))
    client.post(
        "/api/v1/chat/completions",
        json={"chat_id": chat_id, "endpoint_id": "test", "content": "hallo"},
    )
    assert "inside Exe AI" in _system(provider)


def test_ohne_werkzeuge_steht_nichts_ueber_werkzeuge_drin(client, chat_id):
    """The test service has no tool registry, so the section has to be gone."""
    client.app.state.config.features.mcp = False
    provider = provider_setzen(client, MockProvider(mock_endpunkt("test"), haeppchen=["ok"]))
    client.post(
        "/api/v1/chat/completions",
        json={"chat_id": chat_id, "endpoint_id": "test", "content": "hallo"},
    )
    assert "DATA, not instructions" not in _system(provider)


class _Uhr(datetime):
    """A clock the test moves by hand — the DAY is what changes between two
    requests, and the real one would only change it by luck."""

    stand = (9, 41)
    datum = (2026, 8, 24)

    @classmethod
    def now(cls, tz=None):
        return datetime(*cls.datum, *cls.stand, tzinfo=tz)


class _NurCronjob:
    def als_openai_werkzeuge(self, nur=None, shell_zeitgrenze=None, bild_fenster=None, **_options):
        return [{"type": "function", "function": {"name": "cronjob", "parameters": {}}}]


def _zwei_runden_mit_uhr(client, chat_id, monkeypatch, *, cronjob: bool):
    monkeypatch.setattr("app.wecker.datetime", _Uhr)
    monkeypatch.setattr(_Uhr, "stand", (9, 41))
    client.app.state.config.app.timezone = "Europe/Berlin"
    if cronjob:
        client.app.state.werkzeuge = _NurCronjob()
        client.app.state.config.features.mcp = True
        # tool_calls is undetermined until a real /props probe answers it —
        # the test endpoint never gets one, so the capability has to be
        # pinned by hand, the same way test_werkzeugwahl.py does it.
        client.app.state.discovery.zustaende["test"].endpunkt.capabilities.tool_calls = True
    provider = provider_setzen(client, MockProvider(mock_endpunkt("test"), haeppchen=["ok"]))
    client.post(
        "/api/v1/chat/completions",
        json={"chat_id": chat_id, "endpoint_id": "test", "content": "hallo"},
    )
    monkeypatch.setattr(_Uhr, "stand", (9, 42))
    client.post(
        "/api/v1/chat/completions",
        json={"chat_id": chat_id, "endpoint_id": "test", "content": "zwei"},
    )
    return provider.alle_anfragen


def test_the_block_sits_on_the_first_user_turn_and_stays_there(
    client, chat_id, monkeypatch
):
    """The date rides in front of the user turn it belongs to, in the
    outgoing request only, and the system prompt is the same bytes a day
    later.

    And it stays on that turn: the turn goes out exactly as it went out the
    first time. Handing the newest turn a fresh stamp instead — as the clock
    sentence did before it — moved the older turn on every request, and
    everything behind it had to be read again.

    The second turn of the SAME day adds nothing. The request already says
    which day it is; a second block would be the same fact twice."""
    erste, zweite = _zwei_runden_mit_uhr(client, chat_id, monkeypatch, cronjob=True)

    assert _system_aus(erste) == _system_aus(zweite)
    assert "current_date" not in _system_aus(zweite)

    block = grundprompt.environment_block("Europe/Berlin")
    nutzer_erste = [n.content for n in erste.nachrichten if n.role == "user"]
    nutzer = [n.content for n in zweite.nachrichten if n.role == "user"]
    assert nutzer[0] == nutzer_erste[0] == f"{block}\n\nhallo"
    assert nutzer[-1] == "zwei"

    gespeichert = [
        z.content
        for z in client.app.state.repositories.messages.fuer_das_modell(chat_id=chat_id)
        if z.role == "user"
    ]
    assert gespeichert == ["hallo", "zwei"]


def test_the_block_comes_even_without_a_tool_that_fires_at_a_time(
    client, chat_id, monkeypatch
):
    """The former clock sentence hung on the cronjob tool: without a tool
    firing at a time of its own, no clock anywhere. The block hangs on
    nothing — it is the surroundings the model reads in, and a run without
    any tool still has to know which day it is."""
    for anfrage in _zwei_runden_mit_uhr(client, chat_id, monkeypatch, cronjob=False):
        nutzer = [n.content for n in anfrage.nachrichten if n.role == "user"]
        assert nutzer[0].startswith("<environment_context>")
        assert "<current_date>2026-08-24</current_date>" in nutzer[0]


def test_the_next_day_gets_a_fresh_block(client, chat_id, monkeypatch):
    """The other half of the same question: on a new day the request knows
    nothing about today — the older turn carries yesterday. The new turn
    gets its own block, and the older one keeps its own bytes."""
    monkeypatch.setattr("app.wecker.datetime", _Uhr)
    monkeypatch.setattr(_Uhr, "datum", (2026, 8, 24))
    monkeypatch.setattr(_Uhr, "stand", (9, 41))
    client.app.state.config.app.timezone = "Europe/Berlin"
    provider = provider_setzen(client, MockProvider(mock_endpunkt("test"), haeppchen=["ok"]))
    client.post(
        "/api/v1/chat/completions",
        json={"chat_id": chat_id, "endpoint_id": "test", "content": "hallo"},
    )
    monkeypatch.setattr(_Uhr, "datum", (2026, 8, 25))
    client.post(
        "/api/v1/chat/completions",
        json={"chat_id": chat_id, "endpoint_id": "test", "content": "zwei"},
    )

    nutzer = [n.content for n in provider.alle_anfragen[-1].nachrichten if n.role == "user"]
    # Yesterday's turn keeps its own bytes …
    assert nutzer[0] == (
        "<environment_context>\n"
        "<current_date>2026-08-24</current_date>\n"
        "<timezone>Europe/Berlin</timezone>\n"
        "</environment_context>\n\nhallo"
    )
    # … and today's turn gets a block of its own.
    assert nutzer[-1] == f"{grundprompt.environment_block('Europe/Berlin')}\n\nzwei"
    assert "<current_date>2026-08-25</current_date>" in nutzer[-1]


def test_after_a_fold_the_block_comes_back(client, chat_id, monkeypatch):
    """A fold that swallows the row carrying the block takes the date with
    it — which is why the decision is made AFTER the fold, from the very
    rows the prompt is built from. Made one step earlier it would answer
    "the history has today" about a history that no longer does.

    Laid out so that the fold really takes that row: three rows stay pinned
    at the opening (``verdichtung.ERSTE_FEST``), the verbatim tail keeps the
    end, and the row with the block sits in the middle the summary replaces.
    """
    monkeypatch.setattr("app.wecker.datetime", _Uhr)
    monkeypatch.setattr(_Uhr, "datum", (2026, 8, 24))
    monkeypatch.setattr(_Uhr, "stand", (9, 41))
    client.app.state.config.app.timezone = "Europe/Berlin"
    repositories = client.app.state.repositories
    provider = provider_setzen(client, MockProvider(mock_endpunkt("test"), haeppchen=["ok"]))

    def schwer(anzahl: int, marke: str) -> None:
        for nr in range(anzahl):
            repositories.messages.speichern(
                chat_id=chat_id, role="user", content=f"{marke} frage {nr} " + "x" * 12_000
            )
            repositories.messages.speichern(
                chat_id=chat_id, role="assistant",
                content=f"{marke} antwort {nr} " + "x" * 12_000, zustand="fertig",
            )

    schwer(2, "alt")  # rows 1-4: the pinned opening and the row before the block
    client.post(
        "/api/v1/chat/completions",
        json={"chat_id": chat_id, "endpoint_id": "test", "content": "hallo"},
    )
    schwer(8, "neu")  # the verbatim tail
    repositories.einstellungen.setzen(
        bereich=f"chat:{chat_id}", schluessel=verdichtungswahl.SCHLUESSEL, wert=1
    )
    # The reading the fold weighs: the last answer said the prompt filled the
    # window. `MockProvider` reports no token count of its own, so the
    # reading is put there by hand — the DB is the one place it is read from.
    letzte = repositories.messages.fuer_das_modell(chat_id=chat_id)[-1]
    repositories.messages.tokenstand_setzen(letzte.id, 127_000)

    client.post(
        "/api/v1/chat/completions",
        json={"chat_id": chat_id, "endpoint_id": "test", "content": "zwei"},
    )

    # The fold really happened — the summary stands where the folded rows
    # stood, so the row that carried the block is gone from the history …
    uebrig = repositories.messages.fuer_das_modell(chat_id=chat_id)
    assert any(verdichtung.VORSPANN in z.content for z in uebrig), "no fold"
    assert not any(
        "hallo" in z.content for z in uebrig
    ), "the line with the block is still there — the test checks nothing"
    # … and the request after it carries the date again.
    nutzer = [n.content for n in provider.alle_anfragen[-1].nachrichten if n.role == "user"]
    assert any(
        "<current_date>2026-08-24</current_date>" in n for n in nutzer
    ), "the folded request no longer knows the tag"


def test_the_block_never_lands_on_a_report_the_service_wrote(client, chat_id):
    """A finished background run's report travels as the user's side of the
    conversation (app/verlaufsbau.py) and can stand behind the question: a
    fold that takes the turn carrying the block leaves the report the newest
    user message of the request. The block goes in front of the question
    being answered. In front of the report it is surroundings for a sentence
    about a run, and the turn it belongs to goes on reading no day at all."""
    repositories = client.app.state.repositories
    repositories.messages.speichern(
        chat_id=chat_id, role="user", content="Wie viele Zeilen hat die Datei?"
    )
    repositories.messages.speichern(
        chat_id=chat_id,
        role="assistant",
        content="[background run #2 finished: exit 0]",
        art="werkzeugmeldung",
    )
    verlauf = _verlauf_bauen(repositories.chats.holen(chat_id), repositories, "SYS")
    block = grundprompt.environment_block("Europe/Berlin")

    assert grundprompt.restore_environment_block(verlauf, block) is True
    assert verlauf[1].content == f"{block}\n\nWie viele Zeilen hat die Datei?"
    assert verlauf[2].content == "[background run #2 finished: exit 0]"


def test_the_block_never_lands_on_a_tool_picture(client, chat_id):
    """The same for the note that carries the pictures a tool read: a user
    message by role (app/werkzeugbild.py), appended after the round's
    results, so it stands behind the question. What it says belongs to the
    files it names and to nothing else — the date block does not."""
    repositories = client.app.state.repositories
    repositories.messages.speichern(chat_id=chat_id, role="user", content="Was zeigt das Bild?")
    verlauf = _verlauf_bauen(repositories.chats.holen(chat_id), repositories, "SYS")
    bildzug = werkzeugbild.nachricht(
        ["foto.png"], ["data:image/png;base64,AAAA"], ["/tmp/foto.png"]
    )
    assert bildzug is not None
    # Where the round's own results put it: behind everything the request
    # went out with, and therefore the newest user message there is.
    verlauf.append(bildzug)
    block = grundprompt.environment_block("Europe/Berlin")

    assert grundprompt.restore_environment_block(verlauf, block) is True
    assert verlauf[1].content == f"{block}\n\nWas zeigt das Bild?"
    assert bildzug.content == werkzeugbild.EINLEITUNG.format(namen="foto.png")


def test_a_request_that_carries_the_block_sends_no_second_one(client, chat_id):
    """Silence test: the question carries the block and the report stands
    behind it — not one byte of the request changes. A second block would
    say the same thing twice, and re-wording the report would move a message
    the server has already read."""
    repositories = client.app.state.repositories
    frage = repositories.messages.speichern(
        chat_id=chat_id, role="user", content="Wie viele Zeilen hat die Datei?"
    )
    repositories.messages.speichern(
        chat_id=chat_id, role="assistant", content="[report]", art="werkzeugmeldung"
    )
    block = grundprompt.environment_block("Europe/Berlin")
    repositories.messages.set_clock_sentence(frage.id, block)
    verlauf = _verlauf_bauen(repositories.chats.holen(chat_id), repositories, "SYS")
    vorher = [nachricht.content for nachricht in verlauf]

    assert grundprompt.restore_environment_block(verlauf, block) is False
    assert [nachricht.content for nachricht in verlauf] == vorher


def test_the_block_stands_in_front_of_a_summary_where_no_turn_is_left(client, chat_id):
    """The fallback: a fold took every turn of this chat, and what is left
    of the user's side of the conversation is the summary standing in for
    them. The block goes in front of that one — the request would otherwise
    read no day at all."""
    repositories = client.app.state.repositories
    repositories.messages.speichern(
        chat_id=chat_id,
        role="user",
        content=f"{verdichtung.VORSPANN}\n\n## Done\n- alles",
        art="verdichtung",
    )
    verlauf = _verlauf_bauen(repositories.chats.holen(chat_id), repositories, "SYS")
    block = grundprompt.environment_block("Europe/Berlin")

    assert grundprompt.restore_environment_block(verlauf, block) is True
    assert verlauf[-1].content.startswith(block)
    assert verdichtung.VORSPANN in verlauf[-1].content


def _system_aus(anfrage) -> str:
    system = [n for n in anfrage.nachrichten if n.role == "system"]
    assert len(system) == 1, "there must be exactly ONE system message"
    return system[0].content


def _auftrag_mit_uhr(config, monkeypatch, werkzeuge: str):
    import time
    from pathlib import Path

    from fastapi.testclient import TestClient

    from app.main import app_erstellen

    monkeypatch.setattr("app.wecker.datetime", _Uhr)
    monkeypatch.setattr(_Uhr, "stand", (9, 41))
    config.app.timezone = "Europe/Berlin"
    config.features.mcp = True
    config.mcp.servers_file = str(Path(config.app.data_dir) / "keine_server.json")
    agenten = Path(config.app.agenten_verzeichnis)
    agenten.mkdir(parents=True, exist_ok=True)
    (agenten / "uhr.md").write_text(
        f"---\ntools: [{werkzeuge}]\n---\n\nPlant.\n", encoding="utf-8"
    )
    with TestClient(app_erstellen(config)) as client:
        client.headers["X-Sitzungsschluessel"] = client.app.state.sitzungsschluessel
        client.app.state.discovery.zustaende["test"].endpunkt.capabilities.tool_calls = True
        provider = provider_setzen(client, MockProvider(mock_endpunkt("test"), haeppchen=["ok"]))
        kennung = client.post(
            "/api/v1/jobs", json={"agent": "uhr", "task": "in 10 Minuten", "endpoint_id": "test"}
        ).json()["id"]
        frist = time.time() + 8
        stand = None
        while time.time() < frist:
            stand = client.get(f"/api/v1/jobs/{kennung}").json().get("state")
            if stand in {"fertig", "abgebrochen", "gescheitert", "unterbrochen"}:
                break
            time.sleep(0.05)
        assert stand == "fertig", stand
        return provider.alle_anfragen[0]


def test_a_job_carries_the_block_in_front_of_the_task(config, monkeypatch):
    """The job path, the same road: the date block in front of the task, the
    system prompt free of it — and unconditional, where the clock sentence
    needed the cronjob tool first. A job is built once at its start and then
    runs for as long as it runs; it has to know the day either way."""
    anfrage = _auftrag_mit_uhr(config, monkeypatch, "cronjob")
    assert "current_date" not in _system_aus(anfrage)
    nutzer = [n.content for n in anfrage.nachrichten if n.role == "user"]
    assert nutzer[0] == (
        f"{grundprompt.environment_block('Europe/Berlin')}\n\nin 10 Minuten"
    )


def test_a_job_without_the_cron_tool_still_gets_the_block(config, monkeypatch):
    """An agent that named its tools before there was a clock tool still gets
    the block, and its run still gets the tool: nothing else in the request
    names a minute any more, and a run asked to work out what has happened
    since the last one cannot do it without a clock."""
    anfrage = _auftrag_mit_uhr(config, monkeypatch, "read_file")
    nutzer = [n.content for n in anfrage.nachrichten if n.role == "user"]
    assert nutzer[0].startswith("<environment_context>")
    assert "<current_date>2026-08-24</current_date>" in nutzer[0]
    assert uhr.WERKZEUG_NAME in [
        w["function"]["name"] for w in anfrage.werkzeuge
    ], "the job does not have the clock tool"


def test_mit_arbeitsordner_kommt_der_abschnitt_dazu(client, chat_id, tmp_path):
    """Two folders, because the second one was the one that went missing: the
    model could reach the first through its shell and had no way to learn the
    rest, so it looked for them as subfolders of the first."""
    erst = tmp_path / "arbeit"
    zweit = tmp_path / "marken-assets"
    erst.mkdir()
    zweit.mkdir()
    client.patch(
        f"/api/v1/chats/{chat_id}", json={"working_dirs": [str(erst), str(zweit)]}
    )

    provider = provider_setzen(client, MockProvider(mock_endpunkt("test"), haeppchen=["ok"]))
    client.post(
        "/api/v1/chat/completions",
        json={"chat_id": chat_id, "endpoint_id": "test", "content": "hallo"},
    )
    system = _system(provider)
    assert "shared these working folders" in system
    assert str(erst) in system
    assert str(zweit) in system


def test_die_drei_schichten_stehen_in_der_richtigen_reihenfolge(client, chat_id):
    """Shipped instructions, the user's layer, then what is known about them.

    On one of the two servers this program runs itself: the memory travels
    there unasked, while an entry from the configuration would need the cloud
    switch (app/config.py LOKALE_ENDPUNKTE)."""
    client.put("/api/v1/system-prompt", json={"text": "MEINPROMPT"})
    client.app.state.config.memory_schreiben("## Facts\n- MEINFAKT")

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
    text = _system(provider)
    assert text.index("inside Exe AI") < text.index("MEINPROMPT") < text.index("MEINFAKT")


def test_skills_stehen_nur_mit_namen_und_einem_satz_drin():
    """The catalogue is a table of contents, not the content. The long text
    stays on disk until something actually needs it."""
    text = grundprompt.bauen(
        werkzeuge=True, skills=[("handoff", "Sums this conversation up")]
    )
    assert "handoff — Sums this conversation up" in text
    assert "skill_load" in text


def test_ohne_automatische_skills_steht_nichts_davon_drin():
    """Skills the user has to name cost nothing — that is the whole reason
    the switch is worth having."""
    assert "skill_load" not in grundprompt.bauen(werkzeuge=True)


# --- The blocks that came with the new tools --------------------------------


def test_die_dateiwerkzeuge_bekommen_ihren_satz_nur_wenn_sie_da_sind():
    """A sentence about a tool that is switched off costs attention on the
    smallest local model and buys nothing."""
    ohne = grundprompt.bauen(werkzeuge=True)
    mit = grundprompt.bauen(werkzeuge=True, dateiwerkzeuge=["read_file"])
    assert "read_file" not in ohne
    assert "read_file" in mit
    # And NOT a word about the background. A job refuses background=true
    # outright (app/tools/shell.py), so the shipped prompt must not recommend
    # it — an agent following that advice walks into a refusal every time.
    assert "background" not in mit


def test_der_dateisatz_nennt_nur_die_werkzeuge_dieses_laufs():
    """A run with two file tools was being sent to five. It calls the three
    it does not have, once each, and is refused three times."""
    text = grundprompt.bauen(
        werkzeuge=True, dateiwerkzeuge=["read_file", "list_dir"]
    )
    assert "read_file, list_dir" in text
    assert "search_files" not in text
    assert "edit_file" not in text


def test_die_zeile_ueber_befehle_haengt_an_der_shell():
    """`cd` between calls is the shell's business. It used to ride along in
    "you have tools", so an agent that may only read files read it too."""
    ohne = grundprompt.bauen(werkzeuge=True, dateiwerkzeuge=["read_file"])
    mit = grundprompt.bauen(
        werkzeuge=True, dateiwerkzeuge=["read_file"], befehle=True
    )
    assert "`cd` persists" not in ohne
    assert "run_command is for everything else" not in ohne
    assert "`cd` persists" in mit
    assert "run_command is for everything else" in mit


def test_skill_save_bekommt_seinen_satz():
    """The one tool in the registry that had no sentence anywhere."""
    ohne = grundprompt.bauen(werkzeuge=True)
    mit = grundprompt.bauen(werkzeuge=True, skills_schreiben=True)
    assert "skill_save" not in ohne
    assert "skill_save" in mit


def test_der_fragen_baustein_haengt_am_werkzeug():
    ohne = grundprompt.bauen(werkzeuge=True)
    mit = grundprompt.bauen(werkzeuge=True, fragen=True)
    assert "ask_user" not in ohne
    assert "ask_user" in mit


def test_die_vorschau_wird_nur_erwaehnt_wenn_es_sie_gibt():
    ohne = grundprompt.bauen(werkzeuge=True)
    mit = grundprompt.bauen(werkzeuge=True, vorschau=True)
    assert "beside the chat" not in ohne
    assert "beside the chat" in mit


def test_the_environment_block_names_the_date_and_the_zone(monkeypatch):
    """The failure case: a model asked to fire something "in 10 minutes"
    has no day to be relative to, and invents one. The block carries the
    zone with the date, because a schedule crossing a timezone boundary
    cannot be computed from a bare date.

    And it is a BLOCK, not a sentence. The former sentence stood in the
    user's own voice — "The current local date and time is …" — so the model
    read it as part of the request and answered the clock instead of the
    question. A marked block with no verb in it is surroundings; nothing in
    it tells the model to do anything."""
    monkeypatch.setattr("app.wecker.datetime", _Uhr)
    monkeypatch.setattr(_Uhr, "stand", (9, 41))
    text = grundprompt.environment_block("Europe/Berlin")
    assert text == (
        "<environment_context>\n"
        "<current_date>2026-08-24</current_date>\n"
        "<timezone>Europe/Berlin</timezone>\n"
        "</environment_context>"
    )
    # No instruction and no minute: what a run needs the minute for, it asks
    # the clock tool for (app/tools/uhr.py).
    assert "09:41" not in text
    assert "Use it when" not in text
    assert "current_date" not in grundprompt.bauen(werkzeuge=True)


def test_ohne_werkzeuge_bleibt_der_prompt_wie_er_war():
    """The blocks belong to the tools. Without them nothing new appears."""
    schlicht = grundprompt.bauen()
    assert "read_file" not in schlicht
    assert "ask_user" not in schlicht


# --- What the program can do, assembled from what is switched on ------------


def test_die_faehigkeiten_nennen_nur_was_angeboten_wird():
    """The draft had this as a fixed sentence naming five abilities. Every one
    of them can be switched off individually, and a fixed sentence would then
    promise what is not there — the one thing this prompt must never do."""
    nur_bilder = grundprompt.bauen(kann=grundprompt.faehigkeiten({"draw_image"}))
    assert "draw pictures" in nur_bilder
    assert "schedule" not in nur_bilder
    assert "remember things" not in nur_bilder

    mit_mehr = grundprompt.bauen(
        kann=grundprompt.faehigkeiten({"cronjob", "memory_save"})
    )
    assert "draw pictures" not in mit_mehr
    assert "schedule" in mit_mehr
    assert "remember things" in mit_mehr


def test_ohne_ein_einziges_werkzeug_steht_kein_ueberblick_da():
    assert "Besides answering" not in grundprompt.bauen(kann=grundprompt.faehigkeiten(set()))


def test_die_werkzeugnamen_im_ueberblick_sind_die_echten():
    """The mapping is by tool name. A renamed tool would silently drop its
    line from the overview, which is exactly the drift this catches."""
    from app.tools import (
        agentendock, auftrag_werkzeug, bild_werkzeug, create_folder, cron_notiz,
        cronjob, datei_aendern, datei_lesen, datei_schreiben, datei_suchen,
        frage_werkzeug, memory, ordner_lesen, shell, skill, uhr, video_tool, ziel_werkzeug,
    )

    namen = {name for name, _ in grundprompt.FAEHIGKEIT_JE_WERKZEUG}
    assert namen == {
        datei_lesen.WERKZEUG_NAME,
        ordner_lesen.WERKZEUG_NAME,
        datei_suchen.WERKZEUG_NAME,
        datei_schreiben.WERKZEUG_NAME,
        datei_aendern.WERKZEUG_NAME,
        create_folder.WERKZEUG_NAME,
        cron_notiz.WERKZEUG_NAME,
        frage_werkzeug.WERKZEUG_NAME,
        agentendock.WERKZEUG_NAME,
        shell.WERKZEUG_NAME,
        bild_werkzeug.WERKZEUG_NAME,
        video_tool.WERKZEUG_NAME,
        auftrag_werkzeug.WERKZEUG_NAME,
        cronjob.WERKZEUG_NAME,
        ziel_werkzeug.WERKZEUG_NAME,
        uhr.WERKZEUG_NAME,
        skill.LADEN,
        skill.SCHREIBEN,
        memory.WERKZEUG_NAME,
    }


def test_auf_dieser_maschine_faellt_beim_anbieter_weg():
    """"runs on this machine" is simply untrue with a provider at the wheel,
    and WAHRHEIT two blocks down forbids saying it anyway."""
    assert "running on this machine" in grundprompt.bauen(lokal=True)
    assert "running on this machine" not in grundprompt.bauen(lokal=False)


# --- The blocks from the draft ----------------------------------------------


def test_die_suche_haengt_an_einem_suchwerkzeug():
    ohne = grundprompt.bauen(werkzeuge=True)
    mit = grundprompt.bauen(werkzeuge=True, suche=True)
    assert "not one call" not in ohne
    assert "not one call" in mit
    # And no tool name in it: the file search is ours, a web search comes out
    # of mcp_servers.json, and that file belongs to the user.
    assert "search_files" not in mit
    assert "web_search" not in mit


def test_suche_wird_am_namen_erkannt():
    assert grundprompt.hat_suche({"search_files"})
    assert grundprompt.hat_suche({"read_file", "web_search"})
    assert not grundprompt.hat_suche({"read_file", "run_command"})
    assert not grundprompt.hat_suche(set())


def test_der_anhaengesatz_kommt_nur_mit_einem_anhang():
    ohne = grundprompt.bauen(werkzeuge=True)
    mit = grundprompt.bauen(werkzeuge=True, anhaenge=True)
    assert "attached to a message" not in ohne
    assert "attached to a message" in mit
    # NOT the truncation sentence: the truncation header already carries it,
    # at the cut, and only when there was one.
    assert "cut short" not in mit


def test_der_bildersatz_haengt_am_sehvermoegen():
    """Said next to a model without vision the sentence would promise sight
    that is not there."""
    assert "attach images" not in grundprompt.bauen(werkzeuge=True)
    assert "attach images" in grundprompt.bauen(werkzeuge=True, bilder=True)


def test_der_agentensatz_haengt_an_start_job():
    ohne = grundprompt.bauen(werkzeuge=True)
    mit = grundprompt.bauen(werkzeuge=True, agenten=True)
    assert "can be handed off" not in ohne
    assert "can be handed off" in mit
    # "repeats" belongs to the cronjob tool, not to an agent — the draft
    # would have sent the model to the wrong one.
    assert "repeats" not in mit


def test_das_schreiben_ins_gedaechtnis_haengt_am_werkzeug_nicht_am_inhalt():
    """The saving guidance hangs on memory_save being offered — without the
    tool the prompt must not name it, and with it the guidance appears
    whether or not any memory content happens to travel along."""
    assert "memory_save" not in grundprompt.bauen()
    nur_werkzeug = grundprompt.bauen(gedaechtnis_schreiben=True)
    assert "memory_save" in nur_werkzeug


def test_das_gedaechtnis_verspricht_keinen_klick_zum_loeschen():
    """The draft's reason for saving freely was that a wrong entry "costs one
    click to delete". It does not — the memory is one text file, edited whole
    in the settings window. A reason the model can check and find false
    teaches it to discount the rest."""
    text = grundprompt.bauen(gedaechtnis_schreiben=True)
    assert "one click" not in text
    assert "cheaper mistake" in text


def test_der_prompt_und_die_werkzeugbeschreibung_sagen_dasselbe():
    """They contradicted each other: the tool said "save a rule only when the
    user actually asked for one", the prompt says to write down a correction
    and a preference stated in passing. The model reads both."""
    from app.tools import memory

    beschreibung = memory.werkzeug_beschreibung().beschreibung
    assert "only when the user actually asked" not in beschreibung
    assert "in passing" in beschreibung
    assert "in passing" in grundprompt.bauen(gedaechtnis_schreiben=True)


# --- Only for an agent run ---------------------------------------------------


def test_ein_chat_bekommt_den_agentenzusatz_nie():
    assert "running as a job" not in grundprompt.bauen(werkzeuge=True, ordner=["/a"])


def test_der_agentenlauf_hebt_das_nachfragen_auf():
    """Two sentences reach a job today that are wrong there: UMFANG's "ask one
    short question" (nobody can answer) and WERKZEUGE's "the program … asks
    them for you" (a job has no confirmation prompt)."""
    text = grundprompt.bauen(
        werkzeuge=True, agentenlauf=grundprompt.Agentenlauf(runden=8, minuten=20)
    )
    # UMFANG wraps its line, hence the short match.
    assert "ask one short" in text                   # still there, from UMFANG
    assert "there is no way to ask one" in text      # and taken back here
    assert "confirmation prompt in a job" in text
    # The correction has to stand AFTER what it corrects.
    assert text.index("there is no way to ask one") > text.index("ask one short")


def test_der_agentenlauf_nennt_die_zahlen_statt_limited():
    """A model told "8 rounds" can budget; one told "limited" can only guess —
    the same reason ZEIT names the clock instead of saying it is some time."""
    text = grundprompt.bauen(
        agentenlauf=grundprompt.Agentenlauf(runden=8, minuten=20.0)
    )
    assert "You have 8 rounds and 20 minutes" in text
    assert "limited number of rounds" not in text


def test_der_bericht_ist_alles_ausserhalb_eines_werkzeugaufrufs():
    """The draft said "your last message IS the report". It is not:
    app/api/v1/auftraege.py collects the text of EVERY round. A model that
    believed the draft would chatter in round two and have it in the report."""
    text = grundprompt.bauen(agentenlauf=grundprompt.Agentenlauf(runden=8, minuten=20))
    assert "Everything you write outside a tool call becomes the report" in text
    assert "last message" not in text


def test_die_agentenbausteine_haengen_je_an_ihrem_werkzeug():
    ohne = grundprompt.bauen(agentenlauf=grundprompt.Agentenlauf(runden=8, minuten=20))
    assert "deliver_file" not in ohne
    assert "run_command" not in ohne
    assert "belongs in the memory" not in ohne

    mit = grundprompt.bauen(
        gedaechtnis_schreiben=True,
        agentenlauf=grundprompt.Agentenlauf(
            runden=8, minuten=20, befehle=True, ablegen=True
        ),
    )
    assert "deliver_file" in mit
    assert "cannot put anything in the background" in mit
    assert "belongs in the memory" in mit


def test_der_assistent_heisst_exe_egal_welches_modell_antwortet():
    """The name is the one thing about "who is speaking" the shipped prompt
    settles, because it must not change with the engine underneath. A model
    left to itself introduces the name of its maker — true about the engine,
    false about the program."""
    text = grundprompt.bauen()
    assert "You are Exe" in text
    assert "never as the model or its maker" in text
    # And it is in the block that has no gate: every run reads it.
    assert "You are Exe" in grundprompt.GRUNDLAGE


def test_der_name_verbietet_die_ehrliche_antwort_nicht():
    """WAHRHEIT outranks a name. Asked outright which model is running, it
    may say so — a name that forced a denial would be the first sentence in
    this file to ask for one."""
    assert "say it plainly" in grundprompt.bauen()


def test_der_ordnersatz_nennt_die_zugriffslage():
    """The prompt used to say the setting was one it could not see. It can:
    the same rules the gate applies are read for it, so a model that knows
    a question is coming does not read it as a failure."""
    # Read with the line breaks folded: where the template wraps is layout,
    # not behaviour, and a rewrap must not turn these red.
    text = " ".join(
        grundprompt.bauen(
            werkzeuge=True, befehle=True, ordner=["/a"], zugriff=("ja", "fragen")
        ).split()
    )
    assert "commands and file tools run without asking" in text
    assert "outside them they ask the user first" in text
    assert "cannot see" not in text


def test_ein_agent_hoert_dass_die_tuer_nach_aussen_zu_ist():
    text = " ".join(
        grundprompt.bauen(
            werkzeuge=True, befehle=True, ordner=["/a"], zugriff=("ja", "nein")
        ).split()
    )
    assert "outside them they are refused" in text


def test_ohne_zugriffslage_bleibt_der_neutrale_satz():
    text = " ".join(grundprompt.bauen(werkzeuge=True, befehle=True, ordner=["/a"]).split())
    assert "a setting this prompt cannot see" in text


# --- The clock lives in the tool, not in the prompt ---------------------------


def test_the_old_clock_sentence_is_gone():
    """The sentence is replaced, not kept beside the block. Two
    places naming a time — one a date, one a minute — would be two answers,
    and the one in the user's voice is the one the model obeyed."""
    assert not hasattr(grundprompt, "zeitvorsatz")
    assert not hasattr(grundprompt, "ZEIT")


# --- The chat's own folder is not one the user shared -------------------------


def test_the_chats_own_folder_alone_is_no_share():
    text = grundprompt.bauen(
        werkzeuge=True, ordner=["/data/chat_files/c1"], own_folder="/data/chat_files/c1",
        dateiwerkzeuge=["read_file"],
    )
    assert "The user has shared" not in text
    assert "has a folder of its own" in text
    assert "- /data/chat_files/c1" in text


def test_shares_and_the_own_folder_stand_apart():
    """The silence probe: shares are still named as shares, exactly these,
    and the chat's own folder stands apart below them."""
    text = grundprompt.bauen(
        werkzeuge=True, ordner=["/u/a", "/u/b", "/data/chat_files/c1"],
        own_folder="/data/chat_files/c1", dateiwerkzeuge=["read_file"],
    )
    shared = text.split("The user has shared these working folders with you:\n\n")[1]
    shared = shared.split("\n\n")[0]
    assert shared == "- /u/a\n- /u/b"
    assert "also has a folder of its own, where its uploads are kept:\n\n- /data/chat_files/c1" in text


def test_a_chat_sharing_nothing_hears_of_no_share(client, chat_id):
    from app import dokumentablage

    provider = provider_setzen(client, MockProvider(mock_endpunkt("test"), haeppchen=["ok"]))
    client.app.state.config.features.mcp = True
    client.post(
        "/api/v1/chat/completions",
        json={"chat_id": chat_id, "endpoint_id": "test", "content": "hallo"},
    )
    system_text = _system(provider)
    own = dokumentablage.chatordner(client.app.state.config.datenverzeichnis, chat_id)
    assert "The user has shared" not in system_text
    assert f"- {own}" in system_text


def test_the_own_folder_shared_by_the_user_is_a_share_named_once(tmp_path):
    from app import dokumentablage

    own = dokumentablage.chatordner(tmp_path, "c1")
    own.mkdir(parents=True)
    folders = dokumentablage.ordner_dieses_chats(tmp_path, [str(own)], "c1")
    assert dokumentablage.own_folder_in(tmp_path, "c1", [str(own)], folders) is None
    text = grundprompt.bauen(
        werkzeuge=True, ordner=folders, own_folder=None, dateiwerkzeuge=["read_file"]
    )
    assert text.count(f"- {own}") == 1
    assert "has a folder of its own" not in text


def test_the_dock_and_the_image_folder_stand_apart_last():
    """Both are the program's, named apart after the chat's own folder and
    never among the user's shares."""
    text = grundprompt.bauen(
        werkzeuge=True,
        ordner=["/u/a", "/data/chat_files/c1", "/data/agent_dock", "/data/images"],
        own_folder="/data/chat_files/c1",
        dock="/data/agent_dock",
        images="/data/images",
        dateiwerkzeuge=["read_file"],
    )
    shared = text.split("The user has shared these working folders with you:\n\n")[1]
    assert shared.split("\n\n")[0] == "- /u/a"
    assert text.index("The dock folder is where") < text.index("The image folder is where")
    assert "- /data/agent_dock" in text
    assert "- /data/images" in text


def test_a_chat_prompt_names_the_dock_and_the_image_folder(client, chat_id):
    from app import agentendock, speicherorte

    provider = provider_setzen(client, MockProvider(mock_endpunkt("test"), haeppchen=["ok"]))
    client.app.state.config.features.mcp = True
    client.post(
        "/api/v1/chat/completions",
        json={"chat_id": chat_id, "endpoint_id": "test", "content": "hallo"},
    )
    system_text = _system(provider)
    config = client.app.state.config
    assert f"- {speicherorte.ort(config, agentendock.ORT_NAME)}" in system_text
    assert f"- {speicherorte.ort(config, 'images')}" in system_text
    assert "The image folder is where" in system_text
    # Silence probe: the data folder above them is never named on its own.
    assert f"- {config.datenverzeichnis}\n" not in system_text
