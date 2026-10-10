"""A thinking round on the Anthropic wire goes back with its thinking blocks.

While the tool calls of a round are answered, the Messages API wants that
round's thinking blocks back exactly as it sent them — the thinking text with
its signature, a redacted block with its sealed ``data`` — and in the order
the answer brought them; a missing, changed or moved block is refused with a
400. Three layers are pinned down here:

* the stream reader collects each thinking block whole and reports every
  block in its place (``app/providers/anthropic.py``, ``anthropic_block``);
* both loops — the chat (``app/api/v1/generierung.py``) and the job
  (``app/api/v1/auftraege.py``) — hand a round's blocks to the next round,
  also when the folder check cuts the stream as a call begins;
* the request builder puts them back in front of the round's text and calls,
  only for Anthropic's own host, never with a cache mark on a thinking block.

Silence probes: a round without thinking goes back as text plus calls as
before, and the OpenAI-compatible and Responses wires send no thinking block.
"""

from __future__ import annotations

import json

import pytest

from app.providers import MockProvider, mock_endpunkt
from app.providers.base import ChatNachricht, Generierungsanfrage, Stueck, Werkzeugaufruf
from app.providers.openai_kompatibel import OpenAIKompatiblerProvider
from app.providers.openai_responses import koerper_umbauen
from tests.conftest import provider_setzen
from tests.test_anthropic_provider import bauen, ohne_marken, strom, stuecke

THINKING = {"type": "thinking", "thinking": "Need the time first.", "signature": "sig-abc"}
REDACTED = {"type": "redacted_thinking", "data": "sealed-xyz"}
CALL = Werkzeugaufruf(id="t1", name="no_such_tool", argumente={"ort": "Berlin"})
CALL_BLOCK = {"type": "tool_use", "id": "t1", "name": "no_such_tool", "input": {"ort": "Berlin"}}


def _blocks(chunks) -> list[dict]:
    return [s.daten["block"] for s in chunks if s.sorte == "anthropic_block"]


# --- The stream reader -----------------------------------------------------


@pytest.mark.asyncio
async def test_the_reader_reports_the_thinking_block_whole_with_its_signature():
    chunks = await stuecke(bauen(), strom(
        {"type": "content_block_start", "index": 0,
         "content_block": {"type": "thinking", "thinking": "", "signature": ""}},
        {"type": "content_block_delta", "index": 0,
         "delta": {"type": "thinking_delta", "thinking": "Need the time"}},
        {"type": "content_block_delta", "index": 0,
         "delta": {"type": "thinking_delta", "thinking": " first."}},
        {"type": "content_block_delta", "index": 0,
         "delta": {"type": "signature_delta", "signature": "sig-abc"}},
        {"type": "content_block_stop", "index": 0},
        {"type": "content_block_start", "index": 1,
         "content_block": {"type": "tool_use", "id": "t1", "name": "no_such_tool"}},
        {"type": "content_block_delta", "index": 1,
         "delta": {"type": "input_json_delta", "partial_json": '{"ort": "Berlin"}'}},
        {"type": "content_block_stop", "index": 1},
    ))
    assert _blocks(chunks) == [THINKING, {"type": "tool_use", "id": "t1"}]
    # The thinking still streams as reasoning, as before.
    assert "".join(s.text for s in chunks if s.sorte == "reasoning") == "Need the time first."


@pytest.mark.asyncio
async def test_a_redacted_block_and_the_order_of_the_answer_are_kept():
    """A thinking block after a call stays after it."""
    chunks = await stuecke(bauen(), strom(
        {"type": "content_block_start", "index": 0,
         "content_block": {"type": "text", "text": ""}},
        {"type": "content_block_delta", "index": 0,
         "delta": {"type": "text_delta", "text": "Looking."}},
        {"type": "content_block_stop", "index": 0},
        {"type": "content_block_start", "index": 1,
         "content_block": {"type": "tool_use", "id": "t1", "name": "no_such_tool"}},
        {"type": "content_block_stop", "index": 1},
        {"type": "content_block_start", "index": 2, "content_block": dict(REDACTED)},
        {"type": "content_block_stop", "index": 2},
    ))
    assert _blocks(chunks) == [
        {"type": "text", "id": None},
        {"type": "tool_use", "id": "t1"},
        REDACTED,
    ]


@pytest.mark.asyncio
async def test_silence_probe_a_round_without_thinking_reports_no_thinking_block():
    chunks = await stuecke(bauen(), strom(
        {"type": "content_block_start", "index": 0,
         "content_block": {"type": "tool_use", "id": "t1", "name": "no_such_tool"}},
        {"type": "content_block_stop", "index": 0},
    ))
    assert [b["type"] for b in _blocks(chunks)] == ["tool_use"]


# --- The request builder ---------------------------------------------------


def _round(blocks, content="", calls=(CALL,)) -> list[ChatNachricht]:
    return [
        ChatNachricht(role="user", content="How late?"),
        ChatNachricht(
            role="assistant", content=content, werkzeugaufrufe=list(calls),
            anthropic_blocks=blocks,
        ),
        ChatNachricht(role="tool", content="12:00", werkzeugaufruf_id="t1"),
    ]


def _assistant(body) -> list[dict]:
    return ohne_marken(body["messages"])[1]["content"]


def test_the_round_goes_back_beginning_with_its_thinking_block():
    body = bauen()._koerper_bauen(Generierungsanfrage(nachrichten=_round(
        [dict(THINKING), {"type": "text", "id": None}, {"type": "tool_use", "id": "t1"}],
        content="Looking.",
    )))
    assert _assistant(body) == [
        THINKING, {"type": "text", "text": "Looking."}, CALL_BLOCK,
    ]


def test_a_thinking_block_after_a_call_goes_back_after_it():
    body = bauen()._koerper_bauen(Generierungsanfrage(nachrichten=_round(
        [{"type": "tool_use", "id": "t1"}, dict(REDACTED)],
    )))
    assert _assistant(body) == [CALL_BLOCK, REDACTED]


def test_a_call_the_stream_never_finished_stands_at_the_end():
    """The folder check cuts the stream as a call begins and puts its own
    call in its place, under another id."""
    replacement = Werkzeugaufruf(id="cut-1", name="write_file", argumente={})
    body = bauen()._koerper_bauen(Generierungsanfrage(nachrichten=_round(
        [dict(THINKING), {"type": "tool_use", "id": "t9"}], calls=[replacement],
    )))
    assert _assistant(body) == [
        THINKING, {"type": "tool_use", "id": "cut-1", "name": "write_file", "input": {}},
    ]


def test_no_cache_mark_ever_sits_on_a_thinking_block():
    body = bauen()._koerper_bauen(Generierungsanfrage(nachrichten=_round(
        [{"type": "tool_use", "id": "t1"}, dict(REDACTED)],
    )))
    blocks = body["messages"][1]["content"]
    assert "cache_control" not in blocks[1]
    assert "cache_control" in blocks[0]


def test_another_server_of_this_dialect_gets_no_thinking_block():
    body = bauen(base_url="https://proxy.example.net/v1")._koerper_bauen(
        Generierungsanfrage(nachrichten=_round(
            [dict(THINKING), {"type": "tool_use", "id": "t1"}], content="Looking.",
        ))
    )
    assert _assistant(body) == [{"type": "text", "text": "Looking."}, CALL_BLOCK]


def test_silence_probe_a_round_without_thinking_is_text_and_calls_as_before():
    body = bauen()._koerper_bauen(Generierungsanfrage(nachrichten=_round(
        [{"type": "text", "id": None}, {"type": "tool_use", "id": "t1"}], content="Looking.",
    )))
    assert _assistant(body) == [{"type": "text", "text": "Looking."}, CALL_BLOCK]


def test_silence_probe_the_openai_wires_send_no_thinking_block():
    openai = OpenAIKompatiblerProvider(mock_endpunkt("test"))
    body = openai._koerper_bauen(Generierungsanfrage(nachrichten=_round(
        [dict(THINKING), dict(REDACTED), {"type": "tool_use", "id": "t1"}],
    )))
    for sent in (body, koerper_umbauen(body)):
        text = json.dumps(sent)
        assert "sig-abc" not in text
        assert "sealed-xyz" not in text


# --- Both loops ------------------------------------------------------------


class _ThinkingRound(MockProvider):
    """One round that thinks, then calls a tool that does not exist; then an
    answer. The blocks arrive the way the Anthropic reader sends them."""

    BLOCKS: tuple[dict[str, str], ...] = (THINKING, REDACTED)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.histories: list[list] = []

    async def streamen(self, anfrage):
        self.histories.append(list(anfrage.nachrichten))
        if len(self.histories) > 1:
            yield Stueck("content", text="Done.")
            return
        for block in self.BLOCKS:
            yield Stueck("anthropic_block", daten={"block": dict(block)})
        yield Stueck("anthropic_block", daten={"block": {"type": "tool_use", "id": "t1"}})
        yield Stueck("tool_call", werkzeugaufrufe=[CALL])


def _round_entry(history):
    return next(n for n in history if n.role == "assistant" and n.werkzeugaufrufe)


def _sent_round(history) -> list[dict]:
    """The round as the Anthropic wire would send it in the next request."""
    body = bauen()._koerper_bauen(Generierungsanfrage(nachrichten=history))
    return next(
        n["content"] for n in ohne_marken(body["messages"])
        if n["role"] == "assistant" and isinstance(n["content"], list)
        and any(b.get("type") == "tool_use" for b in n["content"])
    )


def test_chat_round_hands_its_thinking_blocks_to_the_next_round(client, chat_id):
    provider = provider_setzen(client, _ThinkingRound(mock_endpunkt("test")))

    client.post(
        "/api/v1/chat/completions",
        json={"chat_id": chat_id, "endpoint_id": "test", "content": "Frage"},
    ).text

    assert len(provider.histories) == 2
    entry = _round_entry(provider.histories[1])
    assert entry.anthropic_blocks[:2] == [THINKING, REDACTED]
    assert _sent_round(provider.histories[1])[:2] == [THINKING, REDACTED]


def test_job_round_hands_its_thinking_blocks_to_the_next_round(config, client):
    from tests.test_auftraege_api import agent_schreiben, auf_ende_warten

    agent_schreiben(config)
    provider = provider_setzen(client, _ThinkingRound(mock_endpunkt("test")))

    job_id = client.post("/api/v1/jobs", json={"agent": "recherche", "task": "Los"}).json()["id"]
    auf_ende_warten(client, job_id)

    assert len(provider.histories) == 2
    entry = _round_entry(provider.histories[1])
    assert entry.anthropic_blocks[:2] == [THINKING, REDACTED]
    assert _sent_round(provider.histories[1])[:2] == [THINKING, REDACTED]


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
        yield Stueck("anthropic_block", daten={"block": dict(THINKING)})
        yield Stueck("anthropic_block", daten={"block": {"type": "tool_use", "id": "w1"}})
        for chars in range(5):
            yield Stueck(
                "tool_call_laeuft",
                daten={"index": 0, "name": "write_file", "zeichen": chars * 100},
            )
        yield Stueck(
            "tool_call",
            werkzeugaufrufe=[
                Werkzeugaufruf(id="w1", name="write_file", argumente={"path": "a.txt"})
            ],
        )


def _cut_folder(client, chat_id, tmp_path):
    import shutil

    from tests.test_chatordner_boden import _dateiwerkzeuge_an

    _dateiwerkzeuge_an(client)
    shared = tmp_path / "shared"
    shared.mkdir()
    assert client.patch(
        f"/api/v1/chats/{chat_id}", json={"working_dirs": [str(shared)]}
    ).status_code == 200
    shutil.rmtree(shared)


def test_the_blocks_reach_the_round_when_the_folder_check_cuts_the_stream(
    client, chat_id, tmp_path
):
    _cut_folder(client, chat_id, tmp_path)
    provider = provider_setzen(client, _CutByTheFolderCheck(mock_endpunkt("test")))

    client.post(
        "/api/v1/chat/completions",
        json={"chat_id": chat_id, "endpoint_id": "test", "content": "schreib"},
    ).text

    assert len(provider.histories) == 2
    entry = _round_entry(provider.histories[1])
    # The call that stands in the history is the cut one, with no argument.
    assert entry.werkzeugaufrufe[0].argumente == {}
    assert entry.anthropic_blocks[0] == THINKING
    assert _sent_round(provider.histories[1])[0] == THINKING


class _RoundWithoutThinking(_ThinkingRound):
    BLOCKS = ()


def test_silence_probe_a_chat_round_without_thinking_goes_back_as_before(client, chat_id):
    provider = provider_setzen(client, _RoundWithoutThinking(mock_endpunkt("test")))

    client.post(
        "/api/v1/chat/completions",
        json={"chat_id": chat_id, "endpoint_id": "test", "content": "Frage"},
    ).text

    assert _sent_round(provider.histories[1]) == [CALL_BLOCK]
