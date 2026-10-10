"""A tool round on OpenAI's Responses wire hands its items to the next round.

With ``store: false`` the server keeps nothing of a response, so the sealed
thinking and the text items of a round reach the next round of the same turn
only if the loop carries them there itself. Both loops are checked — the chat
(app/api/v1/generierung.py) and the job (app/api/v1/auftraege.py) — with a
provider that yields the items the way the real one does
(app/providers/openai_kompatibel.py, ``response_item``).

The SAME holds for the next TURN: its request is rebuilt from the stored row
(app/verlaufsbau.py), and a row that kept only the round's text handed the
model a round without its sealed thinking — the server then answers as if
the model had never thought, and it does the work over. The row remembers
the items beside the text now (``app/api/v1/generierung.py``,
``_runde_im_protokoll``); the last two tests here are that rebuild.
"""

from __future__ import annotations

from app.providers import MockProvider, mock_endpunkt
from app.providers.base import Stueck, Werkzeugaufruf
from tests.conftest import provider_setzen

DENKEN = {
    "type": "reasoning",
    "id": "rs_1",
    "status": "completed",
    "summary": [],
    "encrypted_content": "sealed-thinking",
}
KOMMENTAR = {
    "type": "message",
    "role": "assistant",
    "phase": "commentary",
    "content": [{"type": "output_text", "text": "Looking. "}],
}


class _RoundWithItems(MockProvider):
    """One round with sealed thinking, a commentary item and a tool call, then
    an answer. The tool does not exist; the call still joins the history."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.histories: list[list] = []

    async def streamen(self, anfrage):
        self.histories.append(list(anfrage.nachrichten))
        if len(self.histories) == 1:
            yield Stueck("response_item", daten={"eintrag": DENKEN})
            yield Stueck("response_item", daten={"eintrag": KOMMENTAR})
            yield Stueck("content", text="Looking. ")
            yield Stueck(
                "tool_call",
                werkzeugaufrufe=[Werkzeugaufruf(id="w1", name="no_such_tool", argumente={})],
            )
            return
        yield Stueck("content", text="Done.")


def _round_entry(history):
    return next(n for n in history if n.role == "assistant" and n.werkzeugaufrufe)


def test_chat_round_hands_its_items_to_the_next_round(client, chat_id):
    provider = provider_setzen(client, _RoundWithItems(mock_endpunkt("test")))

    antwort = client.post(
        "/api/v1/chat/completions",
        json={"chat_id": chat_id, "endpoint_id": "test", "content": "Frage"},
    )
    assert antwort.status_code == 200
    antwort.text  # drain the stream so the run finishes

    assert len(provider.histories) == 2
    eintrag = _round_entry(provider.histories[1])
    assert eintrag.reasoning_items == [DENKEN]
    assert eintrag.message_items == [KOMMENTAR]


def test_job_round_hands_its_items_to_the_next_round(config, client):
    from tests.test_auftraege_api import agent_schreiben, auf_ende_warten

    agent_schreiben(config)
    provider = provider_setzen(client, _RoundWithItems(mock_endpunkt("test")))

    kennung = client.post("/api/v1/jobs", json={"agent": "recherche", "task": "Los"}).json()["id"]
    auf_ende_warten(client, kennung)

    assert len(provider.histories) == 2
    eintrag = _round_entry(provider.histories[1])
    assert eintrag.reasoning_items == [DENKEN]
    assert eintrag.message_items == [KOMMENTAR]


class _RoundWithoutItems(_RoundWithItems):
    """The same round from a wire that sends no items."""

    async def streamen(self, anfrage):
        async for stueck in super().streamen(anfrage):
            if stueck.sorte != "response_item":
                yield stueck


def test_silence_probe_a_round_without_items_carries_none(client, chat_id):
    provider = provider_setzen(client, _RoundWithoutItems(mock_endpunkt("test")))

    client.post(
        "/api/v1/chat/completions",
        json={"chat_id": chat_id, "endpoint_id": "test", "content": "Frage"},
    ).text

    eintrag = _round_entry(provider.histories[1])
    assert eintrag.reasoning_items == []
    assert eintrag.message_items == []


class _CutByTheFolderCheck(MockProvider):
    """Thinks, then begins a write_file call in a folder that is gone — the
    folder check cuts the stream at the call's first piece."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.histories: list[list] = []

    async def streamen(self, anfrage):
        self.histories.append(list(anfrage.nachrichten))
        if len(self.histories) > 1:
            yield Stueck("content", text="Done.")
            return
        yield Stueck("response_item", daten={"eintrag": DENKEN})
        for zeichen in range(5):
            yield Stueck(
                "tool_call_laeuft",
                daten={"index": 0, "name": "write_file", "zeichen": zeichen * 100},
            )
        yield Stueck(
            "tool_call",
            werkzeugaufrufe=[
                Werkzeugaufruf(id="w1", name="write_file", argumente={"path": "a.txt"})
            ],
        )


def test_items_reach_the_round_when_the_folder_check_cuts_the_stream(
    client, chat_id, tmp_path
):
    import shutil

    from tests.test_chatordner_boden import _dateiwerkzeuge_an

    _dateiwerkzeuge_an(client)
    geteilt = tmp_path / "shared"
    geteilt.mkdir()
    assert client.patch(
        f"/api/v1/chats/{chat_id}", json={"working_dirs": [str(geteilt)]}
    ).status_code == 200
    shutil.rmtree(geteilt)
    provider = provider_setzen(client, _CutByTheFolderCheck(mock_endpunkt("test")))

    client.post(
        "/api/v1/chat/completions",
        json={"chat_id": chat_id, "endpoint_id": "test", "content": "schreib"},
    ).text

    assert len(provider.histories) == 2
    eintrag = _round_entry(provider.histories[1])
    # The call that stands in the history is the cut one, with no argument.
    assert eintrag.werkzeugaufrufe[0].argumente == {}
    assert eintrag.reasoning_items == [DENKEN]


def _zwei_nachrichten(client, chat_id, provider):
    for frage in ("Frage", "Und weiter?"):
        client.post(
            "/api/v1/chat/completions",
            json={"chat_id": chat_id, "endpoint_id": "test", "content": frage},
        ).text
    assert len(provider.histories) == 3


class _Werkzeug:
    """Offers the one tool the script calls. A request that offers no tools
    at all reads the rebuilt round as text (app/verlaufsbau.py), and then
    there is no round to carry items."""

    def als_openai_werkzeuge(self, nur=None, shell_zeitgrenze=None, bild_fenster=None, **_options):
        return [{"type": "function", "function": {"name": "no_such_tool", "parameters": {}}}]

    def braucht_bestaetigung(self, name, argumente=None, ordner=None):
        return False

    def server_von(self, name):
        return ""

    def bestaetigungsgrund(self, name, argumente=None, ordner=None):
        return ""

    async def ausfuehren(
        self, name, argumente, bild_senke=None, ordner=None, chat_id=None,
        shell_zeitgrenze=None, **_rest,
    ):
        return "getan"


def _mit_werkzeug(client):
    client.app.state.werkzeuge = _Werkzeug()
    client.app.state.config.features.mcp = True
    client.app.state.discovery.zustaende["test"].endpunkt.capabilities.tool_calls = True


def test_die_naechste_nachricht_traegt_die_teile_der_runde_wieder(client, chat_id):
    """The stored row keeps the round's items, so the next turn has them.

    Falls today: the row kept only the round's text, and the rebuilt round
    came without ``encrypted_content`` and without the ``phase`` item —
    a stateless server then thinks from scratch again.
    """
    _mit_werkzeug(client)
    provider = provider_setzen(client, _RoundWithItems(mock_endpunkt("test")))

    _zwei_nachrichten(client, chat_id, provider)

    im_lauf = _round_entry(provider.histories[1])
    im_nachbau = _round_entry(provider.histories[2])
    assert im_lauf.reasoning_items == [DENKEN]
    assert im_nachbau.reasoning_items == im_lauf.reasoning_items
    assert im_nachbau.message_items == im_lauf.message_items == [KOMMENTAR]


def test_eine_zeile_ohne_teile_baut_wie_bisher_nach(client, chat_id):
    """Silence probe: a round that never carried items — the chat wire, or a
    row written before this — rebuilds as it did, with nothing added."""
    _mit_werkzeug(client)
    provider = provider_setzen(client, _RoundWithoutItems(mock_endpunkt("test")))

    _zwei_nachrichten(client, chat_id, provider)

    im_nachbau = _round_entry(provider.histories[2])
    assert im_nachbau.reasoning_items == []
    assert im_nachbau.message_items == []
