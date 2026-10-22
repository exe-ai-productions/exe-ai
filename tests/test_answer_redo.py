"""The arrow under the chat's last answer: a new answer in its place, and a
failed answer asked again.

End to end over the chat route — request, provider stand-in, rows — because
the rule is about what the chat holds afterwards, whoever watches the
stream.
"""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

import httpx
import pytest

from app import answer_redo, answer_replay, faltbitte
from app.answer_sections import SectionLog
from app.db.models import Message
from app.providers import MockProvider, ProviderFehler, mock_endpunkt
from app.providers.base import Stueck, Werkzeugaufruf
from tests.conftest import node_script, provider_setzen, senden
from tests.test_auftraege_api import mcp_client as _mcp_client
from tests.fensterquelle import WINDOW_SOURCE

mcp_client = _mcp_client

ROOT = Path(__file__).resolve().parents[1]
WINDOW = WINDOW_SOURCE
BUBBLE = ROOT / "frontend/src/teile/Nachricht.svelte"
WINDOW_API = ROOT / "frontend/src/lib/api.js"
ENDING = ROOT / "frontend/src/lib/answerEnding.js"

ROUTE = "/api/v1/chat/completions"


def _events(text: str) -> list[dict]:
    return [
        json.loads(line[5:].strip())
        for line in text.splitlines()
        if line.startswith("data:")
    ]


def _rows(client, chat_id: str) -> list[dict]:
    return client.get(f"/api/v1/chats/{chat_id}/messages").json()["nachrichten"]


def _said(rows: list[dict]) -> list[tuple[str, str]]:
    return [(row["role"], row["content"]) for row in rows]


def _redo(client, chat_id: str, **fields) -> list[dict]:
    """A request that names an answer instead of bringing a turn."""
    answer = client.post(ROUTE, json={"chat_id": chat_id, "endpoint_id": "test", **fields})
    assert answer.status_code == 200, answer.text
    return _events(answer.text)


def _answered_chat(client, chat_id: str, text: str = "the first answer") -> dict:
    """A chat with one question and one finished answer; the answer's row."""
    provider_setzen(client, MockProvider(haeppchen=[text]))
    senden(client, chat_id)
    question, answer = _rows(client, chat_id)
    assert (question["role"], answer["role"]) == ("user", "assistant")
    assert answer["zustand"] == "fertig"
    return answer


# --- A new answer in the place of a finished one ------------------------------


def test_a_new_answer_that_fails_leaves_the_old_one_as_it_was(client, chat_id):
    old = _answered_chat(client, chat_id)
    before = _rows(client, chat_id)
    provider_setzen(client, MockProvider(fehler="the model fell over"))

    events = _redo(client, chat_id, replaces=old["id"])

    # The chat holds the question and the old answer, character for
    # character, and not one row of the attempt.
    assert _rows(client, chat_id) == before
    # Why it ended is said in the stream, in the provider's own sentence.
    assert [e["text"] for e in events if e["typ"] == "error"] == ["the model fell over"]
    done = events[-1]
    assert (done["typ"], done["zustand"]) == ("done", "fehler")
    assert done["discarded"] is True
    assert "replaced" not in done


def test_a_new_answer_that_finishes_takes_the_old_ones_place(client, chat_id):
    old = _answered_chat(client, chat_id)
    provider = provider_setzen(client, MockProvider(haeppchen=["the second ", "answer"]))

    events = _redo(client, chat_id, replaces=old["id"])

    rows = _rows(client, chat_id)
    assert _said(rows) == [("user", "Question"), ("assistant", "the second answer")]
    # The old answer's row is gone for good, not hidden.
    assert old["id"] not in [row["id"] for row in rows]
    assert client.app.state.repositories.messages.holen(old["id"]) is None
    done = events[-1]
    assert (done["typ"], done["zustand"]) == ("done", "fertig")
    assert done["replaced"] == old["id"]
    assert done["message_id"] == rows[1]["id"]
    assert "discarded" not in done
    # Written on the history without the old answer.
    sent = [(n.role, n.content) for n in provider.letzte_anfrage.nachrichten]
    assert all("the first answer" not in (content or "") for _, content in sent)
    assert sent[-1][0] == "user"


def test_the_old_answer_stands_in_the_chat_while_the_new_one_is_written(client, chat_id):
    old = _answered_chat(client, chat_id)
    seen = []

    class Looking(MockProvider):
        async def streamen(self, anfrage):
            rows = client.app.state.repositories.messages.auflisten(chat_id=chat_id)
            seen.append([(row.role, row.content, row.zustand) for row in rows])
            async for piece in super().streamen(anfrage):
                yield piece

    provider_setzen(client, Looking(haeppchen=["new"]))
    _redo(client, chat_id, replaces=old["id"])

    assert seen == [
        [
            ("user", "Question", None),
            ("assistant", "the first answer", "fertig"),
            ("assistant", "", "laeuft"),
        ]
    ]


def test_a_stopped_answer_is_replaced_like_a_finished_one(client, chat_id):
    old = _answered_chat(client, chat_id)
    client.app.state.repositories.messages.inhalt_aktualisieren(
        old["id"], content="half an ans", stats={"abgebrochen": True}, zustand="abgebrochen"
    )
    provider_setzen(client, MockProvider(haeppchen=["whole"]))

    events = _redo(client, chat_id, replaces=old["id"])

    assert events[-1]["replaced"] == old["id"]
    assert _said(_rows(client, chat_id)) == [("user", "Question"), ("assistant", "whole")]


def test_silence_probe_an_ordinary_question_stores_as_before(client, chat_id):
    _answered_chat(client, chat_id)
    provider_setzen(client, MockProvider(haeppchen=["and the next"]))

    events = senden(client, chat_id, content="Another question")

    assert _said(_rows(client, chat_id)) == [
        ("user", "Question"),
        ("assistant", "the first answer"),
        ("user", "Another question"),
        ("assistant", "and the next"),
    ]
    done = events[-1]
    assert "replaced" not in done and "discarded" not in done


def test_silence_probe_a_request_without_a_turn_and_without_a_name_adds_an_answer(
    client, chat_id
):
    """The request the window sent before, with the old answer deleted
    first: it still writes an answer on the history as it stands."""
    _answered_chat(client, chat_id)
    provider_setzen(client, MockProvider(haeppchen=["one more"]))

    _redo(client, chat_id)

    assert _said(_rows(client, chat_id)) == [
        ("user", "Question"),
        ("assistant", "the first answer"),
        ("assistant", "one more"),
    ]


@pytest.mark.parametrize("kind", ["werkzeugmeldung", "bild"])
def test_a_row_that_is_no_answer_is_never_replaced(client, chat_id, kind):
    """A finished background command's report or a picture standing last is
    not what the arrow means, whatever id a request names."""
    old = _answered_chat(client, chat_id)
    other = client.app.state.repositories.messages.speichern(
        chat_id=chat_id, role="assistant", content="not an answer", art=kind
    )
    before = _rows(client, chat_id)
    provider_setzen(client, MockProvider(haeppchen=["new"]))

    refused = client.post(
        ROUTE, json={"chat_id": chat_id, "endpoint_id": "test", "replaces": other.id}
    )

    assert refused.status_code == 404
    assert _rows(client, chat_id) == before
    # The answer above it still is the chat's last answer, and replacing it
    # leaves the other row where it stands.
    _redo(client, chat_id, replaces=old["id"])
    assert _said(_rows(client, chat_id)) == [
        ("user", "Question"),
        ("assistant", "not an answer"),
        ("assistant", "new"),
    ]


def test_only_the_chats_last_answer_can_be_named(client, chat_id):
    first = _answered_chat(client, chat_id)
    provider_setzen(client, MockProvider(haeppchen=["the later answer"]))
    senden(client, chat_id, content="Another question")
    before = _rows(client, chat_id)

    for named in (first["id"], before[0]["id"], "no-such-row"):
        refused = client.post(
            ROUTE, json={"chat_id": chat_id, "endpoint_id": "test", "replaces": named}
        )
        assert refused.status_code == 404, named
    assert _rows(client, chat_id) == before


def test_an_answer_of_another_chat_cannot_be_named(client, chat_id):
    _answered_chat(client, chat_id)
    other_chat = client.post("/api/v1/chats", json={"title": "Other"}).json()["id"]
    foreign = _answered_chat(client, other_chat)
    before = _rows(client, chat_id)

    refused = client.post(
        ROUTE, json={"chat_id": chat_id, "endpoint_id": "test", "replaces": foreign["id"]}
    )

    assert refused.status_code == 404
    assert _rows(client, chat_id) == before
    assert _rows(client, other_chat)[1]["id"] == foreign["id"]


def test_a_failed_answer_is_not_replaced(client, chat_id):
    """Under a failed answer the arrow asks the failed call again; a request
    to replace it is turned away and deletes nothing."""
    provider_setzen(client, MockProvider(fehler="broke"))
    senden(client, chat_id)
    failed = _rows(client, chat_id)[1]
    assert failed["zustand"] == "fehler"
    before = _rows(client, chat_id)
    provider_setzen(client, MockProvider(haeppchen=["new"]))

    refused = client.post(
        ROUTE, json={"chat_id": chat_id, "endpoint_id": "test", "replaces": failed["id"]}
    )

    assert refused.status_code == 404
    assert _rows(client, chat_id) == before


@pytest.mark.parametrize(
    "fields",
    [
        {"content": "words"},
        {"bilder": ["a" * 32 + ".png"]},
        {"dokumente": ["some-document"]},
        {"retries": "another-row"},
    ],
)
def test_a_request_naming_an_answer_brings_nothing_else(client, chat_id, fields):
    old = _answered_chat(client, chat_id)
    before = _rows(client, chat_id)

    refused = client.post(
        ROUTE,
        json={"chat_id": chat_id, "endpoint_id": "test", "replaces": old["id"], **fields},
    )

    assert refused.status_code == 422
    assert _rows(client, chat_id) == before


# --- Stop, and a client that goes away ----------------------------------------


async def _chat_with_answer(client: httpx.AsyncClient, app, text: str = "the first answer"):
    state = app.state.discovery.zustaende["test"]
    state.provider = MockProvider(mock_endpunkt("test"), haeppchen=[text])
    state.erreichbar = True
    chat_id = (await client.post("/api/v1/chats", json={"title": "Redo"})).json()["id"]
    await client.post(
        ROUTE, json={"chat_id": chat_id, "endpoint_id": "test", "content": "Question"}
    )
    rows = (await client.get(f"/api/v1/chats/{chat_id}/messages")).json()["nachrichten"]
    return chat_id, rows


@pytest.mark.asyncio
async def test_a_new_answer_that_is_stopped_leaves_the_old_one_as_it_was(laufender_server):
    app, address = laufender_server
    headers = {"X-Sitzungsschluessel": app.state.sitzungsschluessel}
    async with httpx.AsyncClient(base_url=address, timeout=30, headers=headers) as client:
        chat_id, before = await _chat_with_answer(client, app)
        app.state.discovery.zustaende["test"].provider = MockProvider(
            mock_endpunkt("test"), haeppchen=[f"piece{i} " for i in range(50)], verzoegerung=0.05
        )

        read = []
        async with client.stream(
            "POST",
            ROUTE,
            json={"chat_id": chat_id, "endpoint_id": "test", "replaces": before[1]["id"]},
        ) as answer:
            async for line in answer.aiter_lines():
                if not line.startswith("data:"):
                    continue
                read.append(json.loads(line[5:].strip()))
                if read[-1]["typ"] == "content" and len(read) == 4:
                    await client.post("/api/v1/chat/stop", json={"chat_id": chat_id})

        done = read[-1]
        assert (done["typ"], done["abgebrochen"], done["zustand"]) == ("done", True, "abgebrochen")
        assert done["discarded"] is True
        # A stop is no failure: nothing is said about one.
        assert not [e for e in read if e["typ"] == "error"]
        rows = (await client.get(f"/api/v1/chats/{chat_id}/messages")).json()["nachrichten"]
        assert rows == before


@pytest.mark.asyncio
@pytest.mark.parametrize("ending", ["fails", "finishes"])
async def test_a_client_that_goes_away_changes_nothing_about_the_rule(
    laufender_server, ending
):
    """The window closes or reloads while the new answer is written: the
    service keeps or deletes, exactly as with somebody watching."""
    import asyncio

    app, address = laufender_server
    headers = {"X-Sitzungsschluessel": app.state.sitzungsschluessel}
    async with httpx.AsyncClient(base_url=address, timeout=30, headers=headers) as client:
        chat_id, before = await _chat_with_answer(client, app)
        gate = asyncio.Event()

        class LateEnding(MockProvider):
            async def streamen(self, anfrage):
                yield_from = super().streamen(anfrage)
                async for piece in yield_from:
                    yield piece
                if ending == "fails":
                    from app.providers import ProviderFehler

                    raise ProviderFehler("fell over after the client left")

        app.state.discovery.zustaende["test"].provider = LateEnding(
            mock_endpunkt("test"), haeppchen=["new ", "answer"], tor=gate
        )

        async with client.stream(
            "POST",
            ROUTE,
            json={"chat_id": chat_id, "endpoint_id": "test", "replaces": before[1]["id"]},
        ) as answer:
            async for line in answer.aiter_lines():
                if line.startswith("data:") and json.loads(line[5:].strip())["typ"] == "content":
                    break
        # The connection is closed; the run goes on. While it does, both
        # answers are stored.
        rows = (await client.get(f"/api/v1/chats/{chat_id}/messages")).json()
        assert [row["id"] for row in rows["nachrichten"]][:2] == [r["id"] for r in before]
        assert rows["laufend"] is not None
        run = app.state.generierungen.holen(rows["laufend"]["generation_id"])

        gate.set()
        await asyncio.wait_for(run.fertig.wait(), timeout=10)

        after = (await client.get(f"/api/v1/chats/{chat_id}/messages")).json()["nachrichten"]
        if ending == "fails":
            assert after == before
        else:
            assert [(r["role"], r["content"]) for r in after] == [
                ("user", "Question"),
                ("assistant", "new answer"),
            ]
            assert before[1]["id"] not in [r["id"] for r in after]


# --- How a row's ending is read ------------------------------------------------


class _Row:
    def __init__(self, zustand=None, stats=None):
        self.zustand = zustand
        self.stats = stats


@pytest.mark.parametrize(
    ("row", "state", "may_be_replaced"),
    [
        (_Row("fertig"), "fertig", True),
        (_Row("abgebrochen"), "abgebrochen", True),
        (_Row("fehler"), "fehler", False),
        (_Row("laeuft"), "laeuft", False),
        # A row from before the column: the blob says it.
        (_Row(None, {"fehler": "broke"}), "fehler", False),
        (_Row(None, {"abgebrochen": True}), "abgebrochen", True),
        (_Row(None, {}), None, True),
        (_Row(None, None), None, True),
        # The column wins where both speak.
        (_Row("fertig", {"fehler": "an older reading"}), "fertig", True),
    ],
)
def test_how_a_run_ended_is_read_off_the_column_and_then_the_blob(
    row, state, may_be_replaced
):
    assert answer_redo.run_state(row) == state
    assert answer_redo.replaceable(row) is may_be_replaced


# --- A failed answer asked again ----------------------------------------------


class Chain(MockProvider):
    """A run of ``rounds`` tool rounds — a thought, a line of text and one
    call each — whose next model call fails ``failures`` times before it
    answers.

    Which call a request is, is read off the request itself: the number of
    tool results it carries. So a repeated call is answered as the call it
    repeats only if it brings the rounds before it, results included.
    """

    def __init__(self, *args, rounds=3, failures=1, half="", closing="all done", **kwargs):
        super().__init__(*args, **kwargs)
        self.rounds = rounds
        self.failures = failures
        self.half = half
        self.closing = closing
        self.requests = []

    async def streamen(self, anfrage):
        self.letzte_anfrage = anfrage
        self.requests.append(
            [
                (n.role, n.content, [c.id for c in n.werkzeugaufrufe], n.werkzeugaufruf_id)
                for n in anfrage.nachrichten
                if n.role != "system"
            ]
        )
        finished = sum(1 for n in anfrage.nachrichten if n.role == "tool")
        if finished < self.rounds:
            number = finished + 1
            yield Stueck("reasoning", text=f"thinking {number}. ")
            yield Stueck("content", text=f"step {number}. ")
            yield Stueck(
                "tool_call",
                werkzeugaufrufe=[
                    Werkzeugaufruf(
                        id=f"call-{number}", name="addieren", argumente={"a": number, "b": 1}
                    )
                ],
            )
            return
        if self.failures:
            self.failures -= 1
            if self.half:
                yield Stueck("reasoning", text="about to ")
                yield Stueck("content", text=self.half)
            raise ProviderFehler("the server went away")
        yield Stueck("content", text=self.closing)


THREE_ROUNDS = [
    ("assistant", "step 1. ", ["call-1"], None),
    ("tool", "3", [], "call-1"),
    ("assistant", "\n\nstep 2. ", ["call-2"], None),
    ("tool", "3", [], "call-2"),
    ("assistant", "\n\nstep 3. ", ["call-3"], None),
    ("tool", "3", [], "call-3"),
]


def _failed_run(client, **chain):
    """A chat whose one answer made three tool calls and failed in the
    model's fourth call; the provider stand-in, the chat and that answer."""
    provider = provider_setzen(client, Chain(mock_endpunkt("test"), **chain))
    chat_id = client.post("/api/v1/chats", json={"title": "Redo"}).json()["id"]
    senden(client, chat_id)
    question, answer = _rows(client, chat_id)
    assert answer["zustand"] == "fehler"
    assert answer["stats"]["fehler"] == "the server went away"
    assert [call["kennung"] for call in answer["stats"]["werkzeuge"]] == [
        "call-1", "call-2", "call-3",
    ]
    assert len(client.app.state.werkzeuge.aufrufe) == 3
    assert len(provider.requests) == 4
    return provider, chat_id, answer


def _calls_in(row: dict) -> list[tuple]:
    return [
        (call["kennung"], call["name"], call["argumente"], call["ergebnis"], call["runde"])
        for call in row["stats"]["werkzeuge"]
    ]


# --- The thinking blocks of the rounds, on Anthropic's wire --------------------


def _thinking(number: int) -> dict:
    return {"type": "thinking", "thinking": f"thinking {number}. ", "signature": f"sig-{number}"}


def _round_blocks(number: int) -> list[dict]:
    """What the Anthropic reader reports for one round that thought: the
    thinking whole, text and call as markers of their place."""
    return [
        _thinking(number),
        {"type": "text", "id": None},
        {"type": "tool_use", "id": f"call-{number}"},
    ]


class ThinkingChain(Chain):
    """``Chain``, with each round's content blocks as the Anthropic reader
    reports them — and a record of the blocks every request carried on its
    assistant turns."""

    def __init__(self, *args, thinks=True, **kwargs):
        super().__init__(*args, **kwargs)
        self.thinks = thinks
        self.carried = []

    async def streamen(self, anfrage):
        self.carried.append(
            [list(n.anthropic_blocks) for n in anfrage.nachrichten if n.role == "assistant"]
        )
        finished = sum(1 for n in anfrage.nachrichten if n.role == "tool")
        if finished < self.rounds:
            number = finished + 1
            if self.thinks:
                yield Stueck("anthropic_block", daten={"block": _thinking(number)})
            yield Stueck("reasoning", text=f"thinking {number}. ")
            yield Stueck("content", text=f"step {number}. ")
            yield Stueck("anthropic_block", daten={"block": {"type": "text", "id": None}})
            yield Stueck("anthropic_block", daten={"block": {"type": "tool_use", "id": f"call-{number}"}})
            yield Stueck(
                "tool_call",
                werkzeugaufrufe=[
                    Werkzeugaufruf(
                        id=f"call-{number}", name="addieren", argumente={"a": number, "b": 1}
                    )
                ],
            )
            return
        if self.failures:
            self.failures -= 1
            raise ProviderFehler("the server went away")
        yield Stueck("content", text=self.closing)


def _failed_thinking_run(client, **chain):
    provider = provider_setzen(client, ThinkingChain(mock_endpunkt("test"), **chain))
    chat_id = client.post("/api/v1/chats", json={"title": "Redo"}).json()["id"]
    senden(client, chat_id)
    _question, answer = _rows(client, chat_id)
    assert answer["zustand"] == "fehler"
    return provider, chat_id, answer


def _anthropic_body(request) -> list[dict]:
    """The assistant turns of one request as the Anthropic wire sends them."""
    from tests.test_anthropic_provider import bauen, ohne_marken

    body = bauen()._koerper_bauen(request)
    return [
        turn["content"]
        for turn in ohne_marken(body["messages"])
        if turn["role"] == "assistant"
    ]


def test_a_round_that_thought_stores_its_blocks_with_its_first_call(mcp_client):
    _provider, _chat_id, failed = _failed_thinking_run(mcp_client)

    stored = {
        call["runde"]: call.get("blocks") for call in failed["stats"]["werkzeuge"]
    }

    assert stored == {0: _round_blocks(1), 1: _round_blocks(2), 2: _round_blocks(3)}


def test_the_repeated_call_hands_each_round_its_thinking_back_unchanged(mcp_client):
    provider, chat_id, failed = _failed_thinking_run(mcp_client)

    _redo(mcp_client, chat_id, retries=failed["id"])

    # The failed call carried the three rounds' blocks it had just been
    # handed; the repeated one carries the stored ones — the same.
    assert provider.carried[3] == [_round_blocks(1), _round_blocks(2), _round_blocks(3)]
    assert provider.carried[4] == provider.carried[3]


def test_the_blocks_of_a_stored_round_reach_the_wire_in_their_place(mcp_client):
    """The rebuilt turns, as the Anthropic request builder writes them."""
    from app import answer_replay, verlaufsbau
    from app.providers.base import Generierungsanfrage

    _provider, chat_id, failed = _failed_thinking_run(mcp_client)
    row = mcp_client.app.state.repositories.messages.holen(failed["id"])
    part = answer_replay.kept(row)

    turns = verlaufsbau.answer_turns(
        answer_replay.carried(row, part), part.content, werkzeuge=True
    )

    sent = _anthropic_body(Generierungsanfrage(nachrichten=turns))
    assert [content[0] for content in sent] == [_thinking(1), _thinking(2), _thinking(3)]
    assert [[block["type"] for block in content] for content in sent] == [
        ["thinking", "text", "tool_use"]
    ] * 3


def test_silence_probe_a_round_without_thinking_stores_nothing_new(mcp_client):
    _provider, _chat_id, failed = _failed_thinking_run(mcp_client, thinks=False)

    assert all("blocks" not in call for call in failed["stats"]["werkzeuge"])


def test_silence_probe_the_history_of_an_earlier_answer_carries_no_stored_block(mcp_client):
    """Only the one answer asked again hands its blocks back: a plain
    question after a finished answer sends them to nobody."""
    provider, chat_id, failed = _failed_thinking_run(mcp_client)
    _redo(mcp_client, chat_id, retries=failed["id"])
    assert _rows(mcp_client, chat_id)[-1]["zustand"] == "fertig"
    sent_before = len(provider.carried)

    senden(mcp_client, chat_id, content="and now?")

    assert len(provider.carried) > sent_before
    # The three rounds and the closing text of the earlier answer, each as
    # a turn of its own — none of them with a block.
    history = provider.carried[sent_before]
    assert len(history) == 4
    assert all(blocks == [] for blocks in history)


def test_silence_probe_a_round_without_thinking_is_asked_again_as_before(mcp_client):
    provider, chat_id, failed = _failed_thinking_run(mcp_client, thinks=False)

    _redo(mcp_client, chat_id, retries=failed["id"])

    assert provider.carried[4] == [[], [], []]


# --- A refusal over the thinking blocks is asked once more without them -------

REFUSED_MODIFIED = {
    "type": "error",
    "error": {
        "type": "invalid_request_error",
        "message": "messages.1.content.0: `thinking` or `redacted_thinking` blocks in the "
        "latest assistant message cannot be modified. These blocks must remain as they "
        "were in the original response.",
    },
}
REFUSED_SIGNATURE = {
    "type": "error",
    "error": {
        "type": "invalid_request_error",
        "message": "messages.1.content.0: Invalid `signature` in `thinking` block",
    },
}
REFUSED_OTHER = {
    "type": "error",
    "error": {"type": "invalid_request_error", "message": "max_tokens: must be positive"},
}


def _stored_round_request(*, round_number=1):
    from app.providers.base import ChatNachricht, Generierungsanfrage

    call = Werkzeugaufruf(id="call-1", name="addieren", argumente={"a": 1, "b": 1})
    return Generierungsanfrage(
        nachrichten=[
            ChatNachricht(role="user", content="add"),
            ChatNachricht(
                role="assistant",
                content="step 1. ",
                werkzeugaufrufe=[call],
                anthropic_blocks=_round_blocks(round_number),
            ),
            ChatNachricht(role="tool", content="2", werkzeugaufruf_id="call-1"),
        ]
    )


def _answers(*replies):
    """A transport that answers the requests it gets with ``replies`` in
    turn — a dict is a 400 with that body, a string the text of a 200 stream
    — and keeps the bodies it was sent."""
    sent = []
    left = list(replies)

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(request.content))
        reply = left.pop(0)
        if isinstance(reply, dict):
            return httpx.Response(400, json=reply)
        return httpx.Response(200, text=reply, headers={"content-type": "text/event-stream"})

    return httpx.MockTransport(handler), sent


def _done_stream(text="done") -> str:
    events = [
        {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}},
        {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": text}},
        {"type": "content_block_stop", "index": 0},
        {"type": "message_delta", "delta": {"stop_reason": "end_turn"}, "usage": {"output_tokens": 3}},
        {"type": "message_stop"},
    ]
    return "".join(f"data: {json.dumps(event)}\n\n" for event in events)


async def _ask(provider, transport, request):
    from tests.test_anthropic_provider import stuecke

    return await stuecke(provider, transport, request)


@pytest.mark.parametrize("refusal", [REFUSED_MODIFIED, REFUSED_SIGNATURE])
async def test_a_refusal_over_the_thinking_blocks_is_asked_once_more_without_them(refusal):
    from tests.test_anthropic_provider import bauen

    transport, sent = _answers(refusal, _done_stream())
    request = _stored_round_request()

    chunks = await _ask(bauen(), transport, request)

    assert len(sent) == 2
    first = [turn for turn in sent[0]["messages"] if turn["role"] == "assistant"][0]["content"]
    second = [turn for turn in sent[1]["messages"] if turn["role"] == "assistant"][0]["content"]
    assert first[0]["type"] == "thinking"
    assert [block["type"] for block in second] == ["text", "tool_use"]
    assert "".join(c.text for c in chunks if c.sorte == "content") == "done"
    # Gone from the messages for the rounds that follow: none asks twice.
    assert all(turn.anthropic_blocks == [] for turn in request.nachrichten)


async def test_a_second_refusal_is_the_error_and_nothing_is_asked_a_third_time():
    from app.providers import ProviderFehler
    from tests.test_anthropic_provider import bauen

    transport, sent = _answers(REFUSED_MODIFIED, REFUSED_OTHER)

    with pytest.raises(ProviderFehler) as error:
        await _ask(bauen(), transport, _stored_round_request())

    assert len(sent) == 2
    assert "max_tokens" in (error.value.rohtext or "")


async def test_silence_probe_another_refusal_is_not_asked_again():
    from app.providers import ProviderFehler
    from tests.test_anthropic_provider import bauen

    transport, sent = _answers(REFUSED_OTHER)

    with pytest.raises(ProviderFehler):
        await _ask(bauen(), transport, _stored_round_request())

    assert len(sent) == 1


async def test_silence_probe_a_request_without_thinking_blocks_is_not_asked_again():
    from app.providers import ProviderFehler
    from app.providers.base import ChatNachricht, Generierungsanfrage
    from tests.test_anthropic_provider import bauen

    transport, sent = _answers(REFUSED_MODIFIED)
    request = Generierungsanfrage(nachrichten=[ChatNachricht(role="user", content="hello")])

    with pytest.raises(ProviderFehler):
        await _ask(bauen(), transport, request)

    assert len(sent) == 1


async def test_silence_probe_another_server_of_the_dialect_is_not_asked_again():
    """Its requests carry no thinking block, so a refusal over one is not
    about anything this request sent."""
    from app.providers import ProviderFehler
    from tests.test_anthropic_provider import bauen

    transport, sent = _answers(REFUSED_MODIFIED)

    with pytest.raises(ProviderFehler):
        await _ask(bauen(base_url="https://compatible.example/v1"), transport, _stored_round_request())

    assert len(sent) == 1
    assert all(
        block["type"] != "thinking"
        for turn in sent[0]["messages"]
        if isinstance(turn["content"], list)
        for block in turn["content"]
    )


@pytest.mark.parametrize("half", ["", "and the answer is"])
def test_a_failed_answer_asked_again_goes_on_in_the_same_answer(mcp_client, half):
    provider, chat_id, failed = _failed_run(mcp_client, half=half)

    events = _redo(mcp_client, chat_id, retries=failed["id"])

    # The same one answer: no row more, no row less, the same id.
    question, answer = _rows(mcp_client, chat_id)
    assert answer["id"] == failed["id"]
    assert answer["zustand"] == "fertig"
    assert "fehler" not in answer["stats"]
    # Its three calls as they were, and the rest behind them.
    assert _calls_in(answer) == _calls_in(failed)
    assert answer["content"] == "step 1. \n\nstep 2. \n\nstep 3. \n\nall done"
    assert answer["reasoning"] == "thinking 1. thinking 2. thinking 3. "
    # The repeated call carried the question and the three rounds with
    # their results — exactly what the failed call had carried.
    assert len(provider.requests) == 5
    assert provider.requests[4] == provider.requests[3]
    assert provider.requests[4][1:] == THREE_ROUNDS
    assert provider.requests[4][0][0] == "user"
    # And not one of the three tools ran a second time.
    assert len(mcp_client.app.state.werkzeuge.aufrufe) == 3
    done = events[-1]
    assert (done["typ"], done["zustand"], done["message_id"]) == ("done", "fertig", failed["id"])
    assert "replaced" not in done and "discarded" not in done


def test_the_stream_of_a_repeated_call_opens_with_what_the_run_had_done(mcp_client):
    """The window empties the answer at ``start`` and draws it from the
    stream: the three rounds come again as events, in their order, before
    anything new."""
    _, chat_id, failed = _failed_run(mcp_client, half="and the answer is")

    events = _redo(mcp_client, chat_id, retries=failed["id"])

    told = [
        (e["typ"], e.get("text") if e["typ"] != "tool_call" else e["aufruf_id"])
        for e in events
        if e["typ"] in ("start", "reasoning", "content", "tool_call", "tool_result")
    ]
    assert told == [
        ("start", None),
        ("reasoning", "thinking 1. "),
        ("content", "step 1. "),
        ("tool_call", "call-1"),
        ("tool_result", "3"),
        ("reasoning", "thinking 2. "),
        ("content", "\n\nstep 2. "),
        ("tool_call", "call-2"),
        ("tool_result", "3"),
        ("reasoning", "thinking 3. "),
        ("content", "\n\nstep 3. "),
        ("tool_call", "call-3"),
        ("tool_result", "3"),
        ("content", "\n\nall done"),
    ]
    # The answer keeps the order it happened in, across both runs.
    answer = _rows(mcp_client, chat_id)[1]
    assert [section["kind"] for section in answer["stats"]["sections"]] == [
        "reasoning", "content", "tool",
        "reasoning", "content", "tool",
        "reasoning", "content", "tool",
        "content",
    ]


def test_a_thinking_stretch_keeps_its_times_when_it_is_said_again(mcp_client):
    _, chat_id, failed = _failed_run(mcp_client)
    before = [s for s in failed["stats"]["sections"] if s["kind"] == "reasoning"]
    assert len(before) == 3 and all(type(s["end_ms"]) is int for s in before)

    _redo(mcp_client, chat_id, retries=failed["id"])

    after = [
        s for s in _rows(mcp_client, chat_id)[1]["stats"]["sections"] if s["kind"] == "reasoning"
    ]
    assert after == before


@pytest.mark.parametrize("half", ["", "and the answer is"])
def test_a_repeated_call_that_fails_again_leaves_the_answer_as_before_the_press(
    mcp_client, half
):
    provider, chat_id, failed = _failed_run(mcp_client, failures=2, half=half)
    # The second failure brings nothing before it fails.
    provider.half = ""

    class Again(ProviderFehler):
        pass

    original = provider.streamen

    async def with_new_reason(anfrage):
        try:
            async for piece in original(anfrage):
                yield piece
        except ProviderFehler:
            raise Again("still away") from None

    provider.streamen = with_new_reason

    events = _redo(mcp_client, chat_id, retries=failed["id"])

    question, answer = _rows(mcp_client, chat_id)
    # As before the press — what the failed call had begun to write
    # included — with the new reason.
    assert answer["stats"].pop("fehler") == "still away"
    expected = dict(failed, stats={k: v for k, v in failed["stats"].items() if k != "fehler"})
    assert answer == expected
    assert [e["text"] for e in events if e["typ"] == "error"] == ["still away"]
    assert events[-1]["zustand"] == "fehler"
    assert len(mcp_client.app.state.werkzeuge.aufrufe) == 3

    # And the arrow can be pressed again: the third try gets through.
    provider.streamen = original
    _redo(mcp_client, chat_id, retries=failed["id"])
    question, answer = _rows(mcp_client, chat_id)
    assert (answer["id"], answer["zustand"]) == (failed["id"], "fertig")
    assert answer["content"].endswith("step 3. \n\nall done")
    assert len(mcp_client.app.state.werkzeuge.aufrufe) == 3


def test_a_repeated_call_that_writes_and_then_fails_keeps_what_it_wrote(mcp_client):
    provider, chat_id, failed = _failed_run(mcp_client, failures=2, half="first half ")
    provider.half = "second try "

    _redo(mcp_client, chat_id, retries=failed["id"])

    answer = _rows(mcp_client, chat_id)[1]
    assert answer["zustand"] == "fehler"
    assert answer["stats"]["fehler"] == "the server went away"
    # Everything from before, and what the repeated call wrote in place of
    # what the failed one had begun.
    assert answer["content"] == "step 1. \n\nstep 2. \n\nstep 3. \n\nsecond try "
    assert _calls_in(answer) == _calls_in(failed)


def test_the_repeated_call_may_go_on_calling_tools(mcp_client):
    """The run goes on: a round behind the kept ones carries the next
    number, its call runs once, and the rounds before it are not run."""
    provider, chat_id, failed = _failed_run(mcp_client)
    provider.rounds = 4

    _redo(mcp_client, chat_id, retries=failed["id"])

    answer = _rows(mcp_client, chat_id)[1]
    assert answer["zustand"] == "fertig"
    assert [(call["kennung"], call["runde"]) for call in answer["stats"]["werkzeuge"]] == [
        ("call-1", 0), ("call-2", 1), ("call-3", 2), ("call-4", 3),
    ]
    assert [args for _, args in mcp_client.app.state.werkzeuge.aufrufe] == [
        {"a": 1, "b": 1}, {"a": 2, "b": 1}, {"a": 3, "b": 1}, {"a": 4, "b": 1},
    ]
    assert answer["content"].endswith("step 4. \n\nall done")
    # The next question finds the rounds in the row as one run.
    provider_setzen(mcp_client, follow_up := Chain(mock_endpunkt("test"), rounds=0, failures=0))
    senden(mcp_client, chat_id, content="And then?")
    sent = follow_up.requests[-1]
    assert [turn[2] for turn in sent if turn[0] == "assistant" and turn[2]] == [
        ["call-1"], ["call-2"], ["call-3"], ["call-4"],
    ]


def test_an_answer_that_failed_in_its_first_call_is_simply_asked_again(client, chat_id):
    provider_setzen(client, MockProvider(fehler="broke"))
    senden(client, chat_id)
    failed = _rows(client, chat_id)[1]
    provider = provider_setzen(client, MockProvider(haeppchen=["there ", "it is"]))

    events = _redo(client, chat_id, retries=failed["id"])

    question, answer = _rows(client, chat_id)
    assert (answer["id"], answer["zustand"], answer["content"]) == (
        failed["id"], "fertig", "there it is",
    )
    # Nothing of the row goes out as a turn of its own: the request ends in
    # the question, as the failed one did.
    sent = [(n.role, n.content) for n in provider.letzte_anfrage.nachrichten]
    assert sent[-1][0] == "user" and "Question" in sent[-1][1]
    assert [e["typ"] for e in events][:2] == ["start", "content"]


def test_a_stop_before_the_repeated_call_wrote_leaves_the_failed_answer(mcp_client):
    """Pressed and stopped again before anything came: the answer is the
    failed one it was, old reason and all."""
    provider, chat_id, failed = _failed_run(mcp_client, half="and the answer is")
    registry = mcp_client.app.state.generierungen

    class Stopped(Chain):
        async def streamen(self, anfrage):
            registry.alle_im_chat_abbrechen(chat_id)
            async for piece in super().streamen(anfrage):
                yield piece

    provider_setzen(mcp_client, Stopped(mock_endpunkt("test"), failures=0))
    events = _redo(mcp_client, chat_id, retries=failed["id"])

    assert events[-1]["abgebrochen"] is True
    assert _rows(mcp_client, chat_id)[1] == failed


@pytest.mark.parametrize("state", ["fertig", "abgebrochen"])
def test_silence_probe_only_a_failed_answer_is_asked_again(client, chat_id, state):
    """Under a finished and under a stopped answer the arrow means a new
    answer; a request to repeat their call is turned away."""
    old = _answered_chat(client, chat_id)
    client.app.state.repositories.messages.inhalt_aktualisieren(
        old["id"], content=old["content"], stats=old["stats"], zustand=state
    )
    before = _rows(client, chat_id)
    provider_setzen(client, MockProvider(haeppchen=["new"]))

    refused = client.post(
        ROUTE, json={"chat_id": chat_id, "endpoint_id": "test", "retries": old["id"]}
    )

    assert refused.status_code == 404
    assert _rows(client, chat_id) == before
    # A new answer in its place is what the arrow means there.
    assert _redo(client, chat_id, replaces=old["id"])[-1]["replaced"] == old["id"]


def test_a_report_behind_the_failed_answer_is_in_no_request_of_its_run(mcp_client):
    provider, chat_id, failed = _failed_run(mcp_client)
    mcp_client.app.state.repositories.messages.speichern(
        chat_id=chat_id, role="assistant", content="a later report", art="werkzeugmeldung"
    )

    _redo(mcp_client, chat_id, retries=failed["id"])

    assert provider.requests[4] == provider.requests[3]
    rows = _rows(mcp_client, chat_id)
    assert [row["content"] for row in rows][-1] == "a later report"
    assert rows[1]["zustand"] == "fertig"


# --- The kept part, read off a row ---------------------------------------------


def _row(content="", reasoning="", **stats) -> Message:
    return Message(
        id="answer-1", chat_id="chat-1", role="assistant", content=content,
        created_at="2026-01-01T00:00:00", reasoning=reasoning or None, stats=stats,
        zustand="fehler",
    )


def _call(call_id, round_number, text=None, **more) -> dict:
    entry = {
        "name": "addieren", "server": "", "argumente": {"n": round_number},
        "fehlgeschlagen": False, "ergebnis": f"result of {call_id}", "bild": None,
        "dauer_sekunden": 0.5, "kennung": call_id, "runde": round_number, **more,
    }
    if text is not None:
        entry["text"] = text
    return entry


def _recorded(events: list[dict]) -> SectionLog:
    log = SectionLog()
    for event in events:
        log.record("data: " + json.dumps({"zeitpunkt_ms": 5, **event}))
    return log


def test_the_kept_part_ends_at_the_last_finished_call():
    row = _row(
        content="one two HALF",
        reasoning="aaabbbCCC",
        werkzeuge=[_call("c1", 0, "one "), _call("c2", 1, "two ")],
        sections=[
            {"kind": "reasoning", "length": 3, "begin_ms": 10, "end_ms": 20},
            {"kind": "content", "length": 4},
            {"kind": "tool", "call_id": "c1"},
            {"kind": "reasoning", "length": 3, "begin_ms": 30, "end_ms": 40},
            {"kind": "content", "length": 4},
            {"kind": "tool", "call_id": "c2"},
            {"kind": "reasoning", "length": 3, "begin_ms": 50, "end_ms": 60},
            {"kind": "content", "length": 4},
        ],
    )

    part = answer_replay.kept(row)

    assert (part.content, part.reasoning, part.next_round) == ("one two ", "aaabbb", 2)
    assert [call["kennung"] for call in part.calls] == ["c1", "c2"]
    events = answer_replay.events(part)
    assert [(e["typ"], e.get("text", e.get("aufruf_id")), e.get("zeitpunkt_ms")) for e in events] == [
        ("reasoning", "aaa", 10),
        ("content", "one ", 20),
        ("tool_call", "c1", None),
        ("tool_result", "result of c1", None),
        ("reasoning", "bbb", 30),
        ("content", "two ", 40),
        ("tool_call", "c2", None),
        ("tool_result", "result of c2", None),
    ]
    # Said again, the events add up to the kept strings, section by section.
    assert _recorded(events).stored(part.content, part.reasoning, final=False) == [
        {"kind": "reasoning", "length": 3, "begin_ms": 10, "end_ms": 20},
        {"kind": "content", "length": 4},
        {"kind": "tool", "call_id": "c1"},
        {"kind": "reasoning", "length": 3, "begin_ms": 30, "end_ms": 40},
        {"kind": "content", "length": 4},
        {"kind": "tool", "call_id": "c2"},
    ]
    # And the row as the request carries it holds the kept text alone.
    carried = answer_replay.carried(row, part)
    assert (carried.content, carried.id) == ("one two ", "answer-1")
    assert row.content == "one two HALF"


def test_a_call_the_run_died_in_is_not_kept():
    """Its section is there, its result is not: the round it opened is not
    in the log, and its text goes with it."""
    row = _row(
        content="one two ",
        werkzeuge=[_call("c1", 0, "one ")],
        sections=[
            {"kind": "content", "length": 4},
            {"kind": "tool", "call_id": "c1"},
            {"kind": "content", "length": 4},
            {"kind": "tool", "call_id": "c2"},
        ],
    )

    part = answer_replay.kept(row)

    assert (part.content, part.next_round) == ("one ", 1)
    assert [e["typ"] for e in answer_replay.events(part)] == ["content", "tool_call", "tool_result"]


def test_lengths_are_counted_the_way_the_window_counts_them():
    """A character outside the basic plane is two units in a stored length."""
    row = _row(
        content="a\U0001F600b tail",
        werkzeuge=[_call("c1", 0, "a\U0001F600b")],
        sections=[
            {"kind": "content", "length": 4},
            {"kind": "tool", "call_id": "c1"},
            {"kind": "content", "length": 5},
        ],
    )

    part = answer_replay.kept(row)

    assert part.content == "a\U0001F600b"
    assert answer_replay.events(part)[0]["text"] == "a\U0001F600b"


def test_calls_under_one_id_are_said_again_one_by_one():
    """A server without ids numbers every round from zero."""
    row = _row(
        content="",
        werkzeuge=[_call("", 0, "", ergebnis="first"), _call("", 1, "", ergebnis="second")],
        sections=[{"kind": "tool", "call_id": ""}, {"kind": "tool", "call_id": ""}],
    )

    events = answer_replay.events(answer_replay.kept(row))

    assert [e["text"] for e in events if e["typ"] == "tool_result"] == ["first", "second"]


@pytest.mark.parametrize(
    "sections",
    [
        None,
        [],
        "not a list",
        [{"kind": "content", "length": 3}],  # does not add up to the text
        [{"kind": "tool"}],  # a call without an id field
        [{"kind": "content", "length": True}, {"kind": "tool", "call_id": "c1"}],
    ],
)
def test_a_row_without_usable_sections_keeps_its_rounds_by_their_text(sections):
    row = _row(
        content="one two HALF",
        reasoning="all of it",
        werkzeuge=[_call("c1", 0, "one "), _call("c2", 0), _call("c3", 1, "two ")],
        **({} if sections is None else {"sections": sections}),
    )

    part = answer_replay.kept(row)

    assert (part.content, part.reasoning, part.sections, part.next_round) == (
        "one two ", "all of it", None, 2,
    )
    events = answer_replay.events(part)
    # The fixed order a row without sections is drawn in.
    assert [e["typ"] for e in events] == [
        "reasoning", "tool_call", "tool_result", "tool_call", "tool_result",
        "tool_call", "tool_result", "content",
    ]
    assert _recorded(events).stored(part.content, part.reasoning, final=False) is not None


def test_a_row_from_before_rounds_were_stored_keeps_all_of_its_text():
    old_call = {"name": "addieren", "argumente": {}, "ergebnis": "3"}
    row = _row(content="everything it said", werkzeuge=[old_call])

    part = answer_replay.kept(row)

    assert (part.content, part.next_round) == ("everything it said", 1)


def test_a_row_without_a_finished_call_keeps_nothing():
    row = _row(
        content="half a sentence",
        reasoning="half a thought",
        sections=[{"kind": "reasoning", "length": 14}, {"kind": "content", "length": 15}],
    )

    part = answer_replay.kept(row)

    assert (part.content, part.reasoning, part.calls, part.next_round) == ("", "", [], 0)
    assert answer_replay.events(part) == []


def test_what_a_call_carried_beside_its_result_is_said_again():
    row = _row(
        content="",
        werkzeuge=[
            _call("c1", 0, "", lauf_nummer=7, fehlgeschlagen=True, bild="p.png"),
            _call("c2", 0, auftrag_id="job-1"),
        ],
        sections=[{"kind": "tool", "call_id": "c1"}, {"kind": "tool", "call_id": "c2"}],
        ziel="reached",
    )

    events = answer_replay.events(answer_replay.kept(row), goal="reached")

    first, second = [e for e in events if e["typ"] == "tool_result"]
    assert (first["lauf_nummer"], first["fehlgeschlagen"], first["bild"]) == (7, True, "p.png")
    assert "auftrag_id" not in first and second["auftrag_id"] == "job-1"
    assert events[-1] == {"typ": "ziel", "report": "reached"}


# --- The window ----------------------------------------------------------------


def test_the_window_has_no_way_left_to_delete_a_message():
    """The arrow used to delete the answer before a new one existed. The
    window keeps no call of that route at all: what goes and when is the
    service's to decide."""
    api = WINDOW_API.read_text(encoding="utf-8")
    window = WINDOW.read_text(encoding="utf-8")
    assert "nachrichtLoeschen" not in api
    assert "nachrichtLoeschen" not in window
    # The one DELETE left under a message removes an attachment from it.
    deletes = re.findall(r"`/chats/[^`]*/messages/[^`]*`,\s*\{\s*method:\s*'DELETE'", api)
    assert len(deletes) == 1 and "/anhang?" in deletes[0]
    # And nothing in the window builds such a request by hand.
    assert not re.search(r"messages/[^`'\"]*[`'\"],\s*\{[^}]*DELETE", window)


def test_the_arrow_names_the_answer_and_lets_its_ending_pick_the_request():
    window = WINDOW.read_text(encoding="utf-8")
    press = re.search(r"async function neuErzeugen\(messageId\) \{.*?\n  \}\n", window, re.S)
    assert press, "the arrow's function was not found"
    body = press.group(0)
    assert "answerEnding(antwort) === 'fehler' ? { retries: messageId } : { replaces: messageId }" in body
    # No row is taken off the list before the service has answered.
    assert "splice" not in body and "filter(" not in body
    # Both names reach the request the stream is opened with.
    assert "if (redo?.replaces) koerper.replaces = redo.replaces" in window
    assert "if (redo?.retries) koerper.retries = redo.retries" in window
    # "Send again" under the last question goes the same way.
    again = re.search(r"async function frageNeuSenden\(\) \{.*?\n  \}\n", window, re.S)
    assert again and "await neuErzeugen(letzte.id)" in again.group(0)
    # A picture on the answer keeps it from being replaced, not from being
    # asked again: a repeated call deletes nothing.
    assert "answerEnding(letzte) === 'fehler'" in again.group(0)
    assert "(failedAnswer || (letzte && letzte.id && !traegtBild(letzte)))" in again.group(0)


def test_the_window_takes_the_row_down_that_the_service_names():
    """Which of the two rows is gone is read off ``done``, so a window that
    only attached to the run — after a reload — takes the same one down."""
    window = WINDOW.read_text(encoding="utf-8")
    assert "if (ereignis.replaced) replacedId = ereignis.replaced" in window
    assert "if (ereignis.discarded) discarded = true" in window
    closing = re.search(r"const gone = replacedId.*?splice\(stelle, 1\)", window, re.S)
    assert closing, "the row is no longer taken down at the end of the run"
    text = closing.group(0)
    assert "zustand.nachrichten.find((n) => n.id === replacedId)" in text
    assert "discarded || (redo?.replaces && schlussZustand !== 'fertig')" in text


@pytest.mark.parametrize(
    ("language", "again", "anew"),
    [("en", "Try again", "Regenerate"), ("de", "Erneut versuchen", "Neu erzeugen")],
)
def test_the_arrows_two_labels_come_from_the_catalogue(language, again, anew):
    catalogue = json.loads((ROOT / f"app/locales/{language}.json").read_text(encoding="utf-8"))
    assert catalogue["nachricht"]["erneut_versuchen"] == again
    assert catalogue["nachricht"]["neu_erzeugen"] == anew
    # The sentence for an answer that could not be deleted has no reader.
    assert "nicht_entfernt" not in catalogue["nachricht"]
    bubble = BUBBLE.read_text(encoding="utf-8")
    arrow = re.search(r"\{#if istLetzte && nachricht\.id\}.*?\{/if\}", bubble, re.S)
    assert arrow, "the arrow under the last answer was not found"
    assert re.search(
        r"laufzustand === 'fehler'\s*\? t\('nachricht\.erneut_versuchen'\)\s*"
        r": t\('nachricht\.neu_erzeugen'\)",
        arrow.group(0),
    )
    assert "title={arrowLabel} aria-label={arrowLabel}" in arrow.group(0)
    assert "const laufzustand = $derived(answerEnding(nachricht))" in bubble
    for source in (bubble, WINDOW.read_text(encoding="utf-8")):
        assert "nachricht.nicht_entfernt" not in source


ENDINGS = [
    {"zustand": "fertig", "stats": {}},
    {"zustand": "abgebrochen", "stats": {}},
    {"zustand": "fehler", "stats": {"fehler": "broke"}},
    {"zustand": "laeuft", "stats": {}},
    {"zustand": None, "stats": {"fehler": "broke"}},
    {"zustand": None, "stats": {"abgebrochen": True}},
    {"zustand": None, "stats": {}},
    {"zustand": None, "stats": None},
    {"zustand": "fertig", "stats": {"fehler": "an older reading"}},
    {"stats": {"fehler": "broke", "abgebrochen": True}},
]


@pytest.mark.skipif(shutil.which("node") is None, reason="no node on this machine")
def test_the_window_reads_an_answers_ending_as_the_service_does():
    """One arrow, two readers: the label and the request are picked in the
    window, the request is checked in the service. Both read the same row."""
    module = re.sub(r"^export (?=function )", "", ENDING.read_text(encoding="utf-8"), flags=re.M)
    run = node_script(
        f"{module}\nconsole.log(JSON.stringify("
        f"[...{json.dumps(ENDINGS)}.map(answerEnding), answerEnding(undefined)]))"
    )
    assert run.returncode == 0, f"{run.stderr}\n{run.stdout}"
    window = json.loads(run.stdout.strip().splitlines()[-1])

    service = [
        answer_redo.run_state(_Row(row.get("zustand"), row.get("stats"))) for row in ENDINGS
    ]
    assert window[:-1] == service
    assert window == [
        "fertig", "abgebrochen", "fehler", "laeuft", "fehler", "abgebrochen", None, None,
        "fertig", "fehler", None,
    ]


def test_a_call_without_a_stored_result_is_said_again_as_a_finished_one():
    """A row from before results were stored: its call is finished all the
    same, and the window reads a missing text as a call still running."""
    old_call = {"name": "addieren", "argumente": {}, "kennung": "c1", "runde": 0}
    row = _row(content="", werkzeuge=[old_call], sections=[{"kind": "tool", "call_id": "c1"}])

    result = answer_replay.events(answer_replay.kept(row))[-1]

    assert (result["typ"], result["text"], result["fehlgeschlagen"]) == ("tool_result", "", False)


# --- A fold written down by a run that takes another answer's place ------------


@pytest.mark.parametrize("old_answer_still_there", [True, False])
def test_a_fold_written_down_marks_neither_the_new_answer_nor_the_one_it_replaces(
    client, chat_id, old_answer_still_there
):
    """The summary of a fold inside an answer speaks for the rows of its
    requests. The answer being replaced was in none of them, and the answer
    being written is never one of them — also when the replaced row is gone
    by the time the fold is written down."""
    from app import chatverdichtung, verdichtung

    repositories = client.app.state.repositories
    rows = [
        repositories.messages.speichern(
            chat_id=chat_id, role="user" if number % 2 == 0 else "assistant",
            content=f"turn {number}",
        )
        for number in range(8)
    ]
    old_answer = rows[-1]
    new_answer = repositories.messages.speichern(
        chat_id=chat_id, role="assistant", content="", zustand="laeuft"
    )
    if not old_answer_still_there:
        repositories.messages.loeschen(old_answer.id)

    written = chatverdichtung.faltung_nachtragen(
        chat=repositories.chats.holen(chat_id),
        repositories=repositories,
        zusammenfassung=f"{verdichtung.VORSPANN}\n\nsummary",
        budget=80_000,
        ausser_id=new_answer.id,
        without=old_answer.id,
    )

    assert written, "the fold was not written down"
    folded = {
        row.id for row in repositories.messages.auflisten(chat_id=chat_id) if row.verdichtet_in
    }
    assert rows[3].id in folded and rows[6].id in folded
    assert new_answer.id not in folded
    assert old_answer.id not in folded


# --- The end of a run in the window, driven from the real source ----------------

from tests.test_hausregeln import _p662_lauf, _p662_quelle, p662_braucht_node  # noqa: E402

# A chat on screen with a question, the answer that stood there and the row
# a run was filling under it.
END_OF_RUN = """
    zustand.aktiverChat = 'A'
    zustand.nachrichten = [
      { id: 'u1', role: 'user', content: 'question' },
      { id: 'old', role: 'assistant', content: 'the old answer', zustand: %s, stats: {} },
      { id: 'new', role: 'assistant', content: 'the new answer' },
    ]
    zustand.laeuft.A = { chatId: 'A' }
    zustand.laufenderPlatzhalter.A = zustand.nachrichten[2]
    flushSync()
    %s
    await laufEnde({
      zielChat: 'A', platzhalter: zustand.nachrichten[%d], verdichtetZu: null, %s
    })
    return zustand.nachrichten.map((n) => [n.id, n.zustand ?? null])
"""


def _end_of_run(arguments: str, *, old="'fertig'", before="", row=2) -> list:
    return _p662_lauf(_p662_quelle(), END_OF_RUN % (old, before, row, arguments))


# What the service holds in a case where the window never heard a closing
# event: the question and the answer that stood there, or — the attempt
# stored in the moment the stop landed — the question and the new answer.
SERVICE_OLD_STANDS = (
    "dienst.push({ id: 'u1', role: 'user', content: 'question' }); "
    "dienst.push({ id: 'old', role: 'assistant', content: 'the old answer', zustand: 'fertig' })"
)
SERVICE_NEW_STORED = (
    "dienst.push({ id: 'u1', role: 'user', content: 'question' }); "
    "dienst.push({ id: 'new', role: 'assistant', content: 'the new answer', zustand: 'fertig' })"
)


@p662_braucht_node
@pytest.mark.parametrize(
    ("what", "arguments", "left", "service"),
    [
        (
            "finished: the answer it replaced goes",
            "abgebrochen: false, gescheitert: false, schlussZustand: 'fertig', "
            "redo: { replaces: 'old' }, replacedId: 'old', doneSeen: true",
            ["u1", "new"],
            "",
        ),
        (
            "failed: the attempt goes, the old answer stands",
            "abgebrochen: false, gescheitert: true, schlussZustand: 'fehler', "
            "redo: { replaces: 'old' }, discarded: true, doneSeen: true",
            ["u1", "old"],
            "",
        ),
        (
            "stopped from this window, no closing event came, the attempt was dropped",
            "abgebrochen: true, gescheitert: false, schlussZustand: null, "
            "redo: { replaces: 'old' }",
            ["u1", "old"],
            SERVICE_OLD_STANDS,
        ),
        (
            "stopped from this window in the moment the new answer was stored: it stands, the old one is gone",
            "abgebrochen: true, gescheitert: false, schlussZustand: null, "
            "redo: { replaces: 'old' }",
            ["u1", "new"],
            SERVICE_NEW_STORED,
        ),
        (
            "turned away before it began",
            "abgebrochen: false, gescheitert: true, schlussZustand: null, "
            "redo: { replaces: 'old' }",
            ["u1", "old"],
            SERVICE_OLD_STANDS,
        ),
        (
            "a window that only attached to the run reads the closing event",
            "abgebrochen: false, gescheitert: false, schlussZustand: 'fertig', "
            "replacedId: 'old', doneSeen: true",
            ["u1", "new"],
            "",
        ),
        (
            "and takes the dropped attempt down the same way",
            "abgebrochen: false, gescheitert: true, schlussZustand: 'fehler', "
            "discarded: true, doneSeen: true",
            ["u1", "old"],
            "",
        ),
    ],
)
def test_the_window_takes_down_the_row_that_is_gone_on_the_service(
    what, arguments, left, service
):
    assert [row[0] for row in _end_of_run(arguments, before=service)] == left, what


@p662_braucht_node
def test_a_run_with_its_closing_event_does_not_ask_the_service_again_and_one_without_does():
    """Silence probe for the fetch: a replacing run that was told how it ended
    needs no second question, one that was not told asks exactly once."""

    def asks(arguments, before=""):
        szenario = (END_OF_RUN % ("'fertig'", before, 2, arguments)).replace(
            "return zustand.nachrichten.map((n) => [n.id, n.zustand ?? null])",
            "return protokoll.filter((eintrag) => eintrag === 'api.nachrichten').length",
        )
        return _p662_lauf(_p662_quelle(), szenario)

    told = asks(
        "abgebrochen: false, gescheitert: false, schlussZustand: 'fertig', "
        "redo: { replaces: 'old' }, replacedId: 'old', doneSeen: true"
    )
    not_told = asks(
        "abgebrochen: true, gescheitert: false, schlussZustand: null, "
        "redo: { replaces: 'old' }",
        before=SERVICE_OLD_STANDS,
    )
    assert told == 0
    # One question whether the run is still going, one for the list.
    assert not_told == 2


@p662_braucht_node
def test_a_stop_that_has_not_landed_yet_is_waited_for_before_the_list_is_read():
    """The press goes out as a request of its own. A list fetched while the
    run is still named carries its half-written row beside the old answer —
    asked again until the service lets go of the run, then read."""
    running = (
        "dienst.push({ id: 'u1', role: 'user', content: 'question' }); "
        "dienst.push({ id: 'old', role: 'assistant', content: 'the old answer', zustand: 'fertig' }); "
        "dienst.push({ id: 'new', role: 'assistant', content: 'half', zustand: 'laeuft' }); "
        # First question: still running. Second: the stop has landed and the
        # attempt is dropped — what the list read next shows.
        "globalThis.__claims = ["
        "{ laufend: { generation_id: 'eigen' } }, "
        "{ laufend: null, ersetze: ["
        "{ id: 'u1', role: 'user', content: 'question' }, "
        "{ id: 'old', role: 'assistant', content: 'the old answer', zustand: 'fertig' }] }]"
    )
    rows = _end_of_run(
        "abgebrochen: true, gescheitert: false, schlussZustand: null, "
        "redo: { replaces: 'old' }",
        before=running,
    )
    assert [row[0] for row in rows] == ["u1", "old"]


@p662_braucht_node
def test_a_replacing_run_that_cannot_ask_the_service_drops_its_own_row():
    """Where the service cannot be asked what it stored, the attempt's row
    goes the way it always went — beside the old answer it would stand
    twice until the chat is opened again."""
    rows = _end_of_run(
        "abgebrochen: true, gescheitert: false, schlussZustand: null, "
        "redo: { replaces: 'old' }",
        before="globalThis.__claims = ['offline']",
    )
    assert [row[0] for row in rows] == ["u1", "old"]


@p662_braucht_node
def test_silence_probe_an_ordinary_run_takes_no_row_down():
    rows = _end_of_run("abgebrochen: false, gescheitert: false, schlussZustand: 'fertig'")
    assert [row[0] for row in rows] == ["u1", "old", "new"]
    # Nor does an ordinary run that failed: its row stands and says so.
    rows = _end_of_run("abgebrochen: false, gescheitert: true, schlussZustand: 'fehler'")
    assert rows == [["u1", None], ["old", "fertig"], ["new", "fehler"]]


@p662_braucht_node
def test_the_list_of_another_chat_is_left_alone():
    """The run ended while another chat was on screen: that chat's list is
    not this run's to change, and its own is fetched when it is opened."""
    rows = _end_of_run(
        "abgebrochen: false, gescheitert: false, schlussZustand: 'fertig', "
        "redo: { replaces: 'old' }, replacedId: 'old'",
        before="zustand.aktiverChat = 'B'",
    )
    assert [row[0] for row in rows] == ["u1", "old", "new"]


@p662_braucht_node
@pytest.mark.parametrize(
    ("what", "arguments", "state"),
    [
        (
            "turned away before it began: the failed answer it was",
            "abgebrochen: false, gescheitert: true, schlussZustand: null, begun: false",
            "fehler",
        ),
        (
            "stopped before it began: the same",
            "abgebrochen: true, gescheitert: false, schlussZustand: null, begun: false",
            "fehler",
        ),
        (
            "begun and finished",
            "abgebrochen: false, gescheitert: false, schlussZustand: 'fertig', begun: true",
            "fertig",
        ),
        (
            "begun and stopped from this window",
            "abgebrochen: true, gescheitert: false, schlussZustand: null, begun: true",
            "abgebrochen",
        ),
    ],
)
def test_a_retried_answer_ends_in_the_state_its_run_ended_in(what, arguments, state):
    """The run goes on in the failed answer's own row, so nothing is taken
    off the list — and a request that never became a run leaves the row the
    failed answer it was."""
    rows = _end_of_run(
        "redo: { retries: 'old' }, retried: zustand.nachrichten[1], retriedState: 'fehler', "
        + arguments,
        old="'fehler'",
        before="zustand.nachrichten.pop(); zustand.laufenderPlatzhalter.A = zustand.nachrichten[1]",
        row=1,
    )
    assert rows == [["u1", None], ["old", state]], what


# --- the request of a repeated call ends on a turn the model answers --------


def test_a_repeated_call_without_tools_ends_on_a_turn_the_model_answers(mcp_client):
    """A server that is asked to go on from a turn of the model's own writes
    that text further instead of answering. With no tool offered, the rounds
    of the failed answer go as text — and that text used to close the request
    as a turn of the model."""
    provider, chat_id, failed = _failed_run(mcp_client, half="")
    # The tools have been switched off since the answer failed.
    mcp_client.app.state.config.features.mcp = False

    _redo(mcp_client, chat_id, retries=failed["id"])

    request = provider.requests[4]
    # What goes out: one turn, the user's, and nothing of the model's own
    # behind the question.
    assert [turn[0] for turn in request] == ["user"]
    closing = request[-1][1]
    question = _rows(mcp_client, chat_id)[0]["content"]
    assert question in closing
    assert closing.index(question) < closing.index(faltbitte.KOPFZEILE)
    # The rounds the run had finished are still in it — the same block and
    # the same text, behind the question.
    assert faltbitte.KOPFZEILE in closing
    assert "step 1. " in closing and "step 3. " in closing
    assert closing.count("addieren") == 3


def test_silence_probe_with_tools_the_rounds_still_end_on_their_results(mcp_client):
    provider, chat_id, failed = _failed_run(mcp_client, half="")

    _redo(mcp_client, chat_id, retries=failed["id"])

    assert provider.requests[4][1:] == THREE_ROUNDS
    assert provider.requests[4][-1][0] == "tool"


def test_the_text_of_an_answer_goes_behind_the_question_and_no_turn_is_added():
    from app import replay_as_question
    from app.providers.base import ChatNachricht

    history = [
        ChatNachricht(role="user", content="first"),
        ChatNachricht(role="assistant", content="reply"),
        ChatNachricht(role="user", content="question", bild_urls=["data:image/png;base64,AAAA"]),
    ]
    turns = [ChatNachricht(role="assistant", content="block\n\nkept text")]

    sent = replay_as_question.fold_into_question(history, turns)

    assert [m.role for m in sent] == ["user", "assistant", "user"]
    assert sent[-1].content == "question\n\nblock\n\nkept text"
    # The picture of the question stays on it; the history is not touched.
    assert sent[-1].bild_urls == ["data:image/png;base64,AAAA"]
    assert history[-1].content == "question"


def test_silence_turns_that_end_on_a_result_follow_as_they_are():
    from app import replay_as_question
    from app.providers.base import ChatNachricht

    history = [ChatNachricht(role="user", content="question")]
    turns = [
        ChatNachricht(role="assistant", content="step"),
        ChatNachricht(role="tool", content="3", werkzeugaufruf_id="call-1"),
    ]

    assert replay_as_question.fold_into_question(history, turns) == [*history, *turns]
    assert replay_as_question.fold_into_question(history, []) == history


def test_silence_without_a_user_turn_to_hang_the_text_on_the_turns_follow():
    from app import replay_as_question
    from app.providers.base import ChatNachricht

    history = [ChatNachricht(role="assistant", content="reply")]
    turns = [ChatNachricht(role="assistant", content="block")]

    assert replay_as_question.fold_into_question(history, turns) == [*history, *turns]


def test_the_row_of_a_new_answer_names_the_old_one_while_it_runs_and_not_after(client, chat_id):
    old = _answered_chat(client, chat_id)
    named = []

    class Looking(MockProvider):
        async def streamen(self, anfrage):
            rows = client.app.state.repositories.db.verbindung.execute(
                "SELECT replaces_id FROM messages WHERE zustand = 'laeuft'"
            ).fetchall()
            named.append([row["replaces_id"] for row in rows])
            async for piece in super().streamen(anfrage):
                yield piece

    provider_setzen(client, Looking(haeppchen=["new"]))
    _redo(client, chat_id, replaces=old["id"])

    assert named == [[old["id"]]]
    after = client.app.state.repositories.db.verbindung.execute(
        "SELECT replaces_id FROM messages WHERE role = 'assistant'"
    ).fetchall()
    assert [row["replaces_id"] for row in after] == [None]


def test_silence_probe_an_ordinary_question_writes_no_name_on_its_running_row(client, chat_id):
    named = []

    class Looking(MockProvider):
        async def streamen(self, anfrage):
            rows = client.app.state.repositories.db.verbindung.execute(
                "SELECT replaces_id FROM messages WHERE zustand = 'laeuft'"
            ).fetchall()
            named.append([row["replaces_id"] for row in rows])
            async for piece in super().streamen(anfrage):
                yield piece

    provider_setzen(client, Looking(haeppchen=["answer"]))
    senden(client, chat_id)

    assert named == [[None]]
