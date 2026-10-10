"""A stored answer keeps the order it happened in.

Before, the row held one joined thinking string, and after a reload thinking
-> tool -> thinking stood as one entry above the tools, without a length.
The run now records the sections from the very events the window reads
(app/answer_sections.py) and keeps them in the row's metrics; the window
rebuilds the entries from them (frontend/src/teile/Nachricht.svelte).
"""

from __future__ import annotations

import json
from typing import AsyncIterator

from app.answer_sections import SectionLog, utf16_length
from app.providers import MockProvider, mock_endpunkt
from app.providers.base import Generierungsanfrage, Stueck, Werkzeugaufruf
from app.tools.registry import WerkzeugRegistry
from tests.conftest import provider_setzen


def _event(kind: str, at: int, **fields) -> str:
    return f"data: {json.dumps({'typ': kind, 'zeitpunkt_ms': at, **fields})}\n\n"


def _feed(log: SectionLog, *events: str) -> None:
    for event in events:
        log.record(event)


def test_two_thinking_stretches_stay_two_with_their_ends():
    log = SectionLog()
    _feed(
        log,
        _event("start", 1),
        _event("reasoning", 10, text="First "),
        _event("denktempo", 15),
        _event("reasoning", 20, text="think."),
        _event("tool_call", 30, aufruf_id="a1", name="read_file"),
        _event("tool_result", 40, aufruf_id="a1"),
        _event("reasoning", 50, text="Again."),
        _event("content", 60, text="Done."),
        _event("done", 70),
    )
    assert log.stored("Done.", "First think.Again.", final=True) == [
        # The speed reading is no end; the tool call is.
        {"kind": "reasoning", "length": 12, "begin_ms": 10, "end_ms": 30},
        {"kind": "tool", "call_id": "a1"},
        {"kind": "reasoning", "length": 6, "begin_ms": 50, "end_ms": 60},
        {"kind": "content", "length": 5},
    ]


def test_thinking_that_goes_on_after_a_passing_event_is_one_stretch():
    log = SectionLog()
    _feed(
        log,
        _event("reasoning", 10, text="a"),
        _event("kontext", 15),
        _event("reasoning", 20, text="b"),
    )
    sections = log.stored("", "ab", final=True)
    assert len(sections) == 1
    assert sections[0]["length"] == 2 and sections[0]["begin_ms"] == 10
    # Still open at the closing write: it ends there, not never.
    assert sections[0]["end_ms"] >= 20


def test_an_intermediate_save_keeps_only_ends_events_set():
    """Mid-run the row keeps the last end an event set — a real time — and
    stamps none of its own."""
    log = SectionLog()
    _feed(log, _event("reasoning", 10, text="still"), _event("kontext", 15))
    assert log.stored("", "still", final=False) == [
        {"kind": "reasoning", "length": 5, "begin_ms": 10, "end_ms": 15},
    ]


def test_the_lift_cuts_a_stretch_as_the_window_does():
    """Thinking of two rounds with nothing between them is one stretch; when
    its tail becomes the answer the rest keeps its times (App.svelte,
    liftAnswer), and a stretch left empty is dropped."""
    # As in the service: the closing write comes before `done`, so the
    # stretch is still open and gets its end there, before the lift.
    log = SectionLog()
    _feed(log, _event("reasoning", 10, text="AB"))
    stretch, answer = log.stored("B", "A", final=True, promoted=True)
    assert stretch["length"] == 1 and stretch["begin_ms"] == 10 and stretch["end_ms"] > 10
    assert answer == {"kind": "content", "length": 1}
    log = SectionLog()
    _feed(log, _event("reasoning", 10, text="B"))
    assert log.stored("B", "", final=True, promoted=True) == [
        {"kind": "content", "length": 1},
    ]


def test_the_lift_keeps_text_an_earlier_round_wrote():
    """'Let me look.' before the call stays where it stood; the closing
    thought follows it as the rest of the answer."""
    log = SectionLog()
    _feed(
        log,
        _event("content", 5, text="Let me look."),
        _event("tool_call", 10, aufruf_id="a1"),
        _event("tool_result", 20, aufruf_id="a1"),
        _event("reasoning", 30, text="It says hello."),
        _event("done", 40),
    )
    assert log.stored("Let me look.It says hello.", "", final=True, promoted=True) == [
        {"kind": "content", "length": 12},
        {"kind": "tool", "call_id": "a1"},
        {"kind": "content", "length": 14},
    ]


def test_an_intermediate_save_claims_no_end():
    """A save mid-run must not stamp an end on a stretch that is still
    running — after a crash the row would report one that never was."""
    log = SectionLog()
    _feed(log, _event("reasoning", 10, text="still going"))
    assert log.stored("", "still going", final=False) == [
        {"kind": "reasoning", "length": 11, "begin_ms": 10},
    ]


def test_lengths_count_as_javascript_counts():
    """An emoji is two units in the window's strings; counted as one, every
    section after it would be cut one character early."""
    log = SectionLog()
    _feed(log, _event("content", 10, text="😀 ok"))
    assert utf16_length("😀 ok") == 5
    assert log.stored("😀 ok", None, final=True) == [{"kind": "content", "length": 5}]


def test_a_lone_surrogate_does_not_end_the_run():
    """JSON lets a lone surrogate through; counting it must not raise inside
    the run that feeds the log."""
    log = SectionLog()
    log.record('data: {"typ": "content", "zeitpunkt_ms": 1, "text": "x\\ud83d"}\n\n')
    assert log.stored("x\ud83d", None, final=True) == [{"kind": "content", "length": 2}]


def test_a_promoted_answer_is_lifted_as_the_window_lifts_it():
    """A run that thought, called a tool, thought again and stopped without a
    visible character has its closing thought moved into the answer
    (app/reasoning.denktext_als_antwort). The sections follow: the first
    stretch stays, the closing one becomes the text."""
    log = SectionLog()
    _feed(
        log,
        _event("reasoning", 10, text="Look first."),
        _event("tool_call", 20, aufruf_id="a1"),
        _event("tool_result", 30, aufruf_id="a1"),
        _event("reasoning", 40, text="It says hello."),
        _event("done", 50),
    )
    assert log.stored("It says hello.", "Look first.", final=True, promoted=True) == [
        {"kind": "reasoning", "length": 11, "begin_ms": 10, "end_ms": 20},
        {"kind": "tool", "call_id": "a1"},
        {"kind": "content", "length": 14},
    ]


def test_blank_streamed_text_is_dropped_by_the_lift():
    """The swap keeps no blank text: the answer is the closing thought alone.
    Cutting it by the blank text's length would split its first letters off
    above the tool."""
    log = SectionLog()
    _feed(
        log,
        _event("content", 5, text="\n\n"),
        _event("tool_call", 10, aufruf_id="a1"),
        _event("tool_result", 20, aufruf_id="a1"),
        _event("reasoning", 30, text="The file says hello."),
        _event("done", 40),
    )
    assert log.stored("The file says hello.", "", final=True, promoted=True) == [
        {"kind": "tool", "call_id": "a1"},
        {"kind": "content", "length": 20},
    ]


def test_sections_that_do_not_add_up_are_not_kept():
    """Strings the stream does not describe, and no swap to explain them,
    would be cut in the wrong places."""
    log = SectionLog()
    _feed(log, _event("content", 10, text="The answer is 4."))
    assert log.stored("The answer", None, final=True) is None
    assert log.stored("The answer is 4. And more.", None, final=True) is None
    # The swap is named, never guessed from lengths.
    _feed(log, _event("reasoning", 20, text="Thought."))
    assert log.stored("The answer is 4.Thought.", "", final=True) is None
    assert SectionLog().stored("", None, final=True) is None


def test_an_unreadable_event_gives_the_order_up_without_raising():
    """A display aid must not end the run: the event is logged, and the row
    is stored without an order."""
    log = SectionLog()
    log.record('data: {"typ": "content", "zeitpunkt_ms": 1, "text": 5}\n\n')
    log.record('data: {"typ": "content", "zeitpunkt_ms": 2, "text": "x"}\n\n')
    assert log.stored("x", None, final=True) is None


def test_a_call_with_only_a_result_still_gets_its_place():
    """A task or question refused before it was put sends no announcing
    event, only its result; its stored log entry needs a section, or a
    reload hides a call the model saw the result of."""
    log = SectionLog()
    _feed(
        log,
        _event("tool_call", 10, aufruf_id="a1"),
        _event("tool_result", 20, aufruf_id="a1"),
        _event("tool_result", 30, aufruf_id="refused"),
    )
    assert log.stored("", None, final=True) == [
        {"kind": "tool", "call_id": "a1"},
        {"kind": "tool", "call_id": "refused"},
    ]


def test_the_same_id_in_two_rounds_is_two_calls():
    """A server without ids numbers every round from zero."""
    log = SectionLog()
    _feed(
        log,
        _event("tool_call", 10, aufruf_id="aufruf_0"),
        _event("tool_result", 20, aufruf_id="aufruf_0"),
        _event("tool_call", 30, aufruf_id="aufruf_0"),
        _event("tool_result", 40, aufruf_id="aufruf_0"),
    )
    assert log.stored("", None, final=True) == [
        {"kind": "tool", "call_id": "aufruf_0"},
        {"kind": "tool", "call_id": "aufruf_0"},
    ]


def test_a_call_left_open_does_not_swallow_the_next_rounds_result():
    """A question that got no result stays open only for its own round; a
    refused call of the next round with the same number still gets its
    place."""
    log = SectionLog()
    _feed(
        log,
        _event("user_ask", 10, aufruf_id="aufruf_0"),
        _event("reasoning", 20, text="Next round."),
        _event("tool_result", 30, aufruf_id="aufruf_0"),
    )
    assert [section["kind"] for section in log.stored("", "Next round.", final=True)] == [
        "tool", "reasoning", "tool",
    ]


class _ThinkToolThink(MockProvider):
    """Thinks, calls a tool, thinks again, answers."""

    def __init__(self) -> None:
        super().__init__(mock_endpunkt("test"))
        self.round = 0

    async def streamen(self, anfrage: Generierungsanfrage) -> AsyncIterator[Stueck]:
        self.alle_anfragen.append(anfrage)
        self.letzte_anfrage = anfrage
        self.round += 1
        if self.round == 1:
            yield Stueck("reasoning", "Look it up first.")
            yield Stueck(
                "tool_call",
                werkzeugaufrufe=[
                    Werkzeugaufruf(id="a1", name="read_file", argumente={"path": "note.txt"})
                ],
            )
        else:
            yield Stueck("reasoning", "Now I know.")
            yield Stueck("content", "It says hello.")
        yield Stueck("stats", daten={"dauer_sekunden": 0.0, "haeppchen": 1, "endpunkt": self.id})


def test_a_stored_answer_keeps_its_sections(client, tmp_path):
    (tmp_path / "note.txt").write_text("hello", encoding="utf-8")
    client.app.state.werkzeuge = WerkzeugRegistry([], shell_an=True)
    client.app.state.config.features.mcp = True
    client.app.state.discovery.zustaende["test"].endpunkt.capabilities.tool_calls = True
    chat = client.post("/api/v1/chats", json={"title": "Sections"}).json()
    client.patch(f"/api/v1/chats/{chat['id']}", json={"working_dirs": [str(tmp_path)]})
    provider_setzen(client, _ThinkToolThink())
    client.post(
        "/api/v1/chat/completions",
        json={"chat_id": chat["id"], "endpoint_id": "test", "content": "What does it say?"},
    )
    rows = client.get(f"/api/v1/chats/{chat['id']}/messages").json()["nachrichten"]
    answer = [row for row in rows if row["role"] == "assistant"][-1]
    sections = answer["stats"]["sections"]
    assert [section["kind"] for section in sections] == [
        "reasoning", "tool", "reasoning", "content",
    ]
    # The lengths cut the stored strings into the stretches as streamed.
    first, tool, second, text = sections
    reasoning = answer["reasoning"]
    assert reasoning[: first["length"]] == "Look it up first."
    assert reasoning[first["length"]:] == "Now I know."
    assert answer["content"][: text["length"]] == "It says hello."
    # Each stretch has its own begin and end, the first one ending at the call.
    assert first["begin_ms"] <= first["end_ms"] <= second["begin_ms"] <= second["end_ms"]
    # The tool section finds its stored entry, which keeps the id as `kennung`.
    assert tool["call_id"] == "a1"
    assert [entry.get("kennung") for entry in answer["stats"]["werkzeuge"]] == ["a1"]


class _Plain(MockProvider):
    async def streamen(self, anfrage: Generierungsanfrage) -> AsyncIterator[Stueck]:
        self.alle_anfragen.append(anfrage)
        self.letzte_anfrage = anfrage
        yield Stueck("content", "Just text.")
        yield Stueck("stats", daten={"dauer_sekunden": 0.0, "haeppchen": 1, "endpunkt": self.id})


def test_a_plain_answer_keeps_one_text_section(client):
    """The quiet case: nothing but text stays one text section, and a row
    without sections (written before they were stored) is drawn as before —
    the window's fallback reads it."""
    chat = client.post("/api/v1/chats", json={"title": "Plain"}).json()
    provider_setzen(client, _Plain(mock_endpunkt("test")))
    client.post(
        "/api/v1/chat/completions",
        json={"chat_id": chat["id"], "endpoint_id": "test", "content": "Hello"},
    )
    rows = client.get(f"/api/v1/chats/{chat['id']}/messages").json()["nachrichten"]
    answer = [row for row in rows if row["role"] == "assistant"][-1]
    assert answer["stats"]["sections"] == [{"kind": "content", "length": 10}]


class _ThinkToolThinkOnly(_ThinkToolThink):
    """As above, but the closing round only thinks — its thought becomes the
    answer when the run is stored."""

    async def streamen(self, anfrage: Generierungsanfrage) -> AsyncIterator[Stueck]:
        self.alle_anfragen.append(anfrage)
        self.letzte_anfrage = anfrage
        self.round += 1
        if self.round == 1:
            yield Stueck("reasoning", "Look it up first.")
            yield Stueck(
                "tool_call",
                werkzeugaufrufe=[
                    Werkzeugaufruf(id="a1", name="read_file", argumente={"path": "note.txt"})
                ],
            )
        else:
            yield Stueck("reasoning", "It says hello.")
        yield Stueck(
            "stats",
            daten={"dauer_sekunden": 0.0, "haeppchen": 1, "endpunkt": self.id, "ende_grund": "stop"},
        )


def test_a_promoted_answer_is_stored_with_its_lifted_order(client, tmp_path):
    (tmp_path / "note.txt").write_text("hello", encoding="utf-8")
    client.app.state.werkzeuge = WerkzeugRegistry([], shell_an=True)
    client.app.state.config.features.mcp = True
    client.app.state.discovery.zustaende["test"].endpunkt.capabilities.tool_calls = True
    chat = client.post("/api/v1/chats", json={"title": "Lifted"}).json()
    client.patch(f"/api/v1/chats/{chat['id']}", json={"working_dirs": [str(tmp_path)]})
    provider_setzen(client, _ThinkToolThinkOnly())
    client.post(
        "/api/v1/chat/completions",
        json={"chat_id": chat["id"], "endpoint_id": "test", "content": "What does it say?"},
    )
    rows = client.get(f"/api/v1/chats/{chat['id']}/messages").json()["nachrichten"]
    answer = [row for row in rows if row["role"] == "assistant"][-1]
    assert answer["stats"].get("denktext_als_antwort") is True
    assert answer["content"] == "It says hello."
    assert answer["reasoning"] == "Look it up first."
    assert [(s["kind"], s.get("length")) for s in answer["stats"]["sections"]] == [
        ("reasoning", 17), ("tool", None), ("content", 14),
    ]


class _WriteToolWrite(MockProvider):
    """Writes an opening, calls a tool, then writes on in a second round.

    ``closing``: what the second round sends, as (kind, text) pieces.
    """

    def __init__(self, opening: str, closing: list[tuple[str, str]]) -> None:
        super().__init__(mock_endpunkt("test"))
        self.round = 0
        self.opening = opening
        self.closing = closing

    async def streamen(self, anfrage: Generierungsanfrage) -> AsyncIterator[Stueck]:
        self.alle_anfragen.append(anfrage)
        self.letzte_anfrage = anfrage
        self.round += 1
        if self.round == 1:
            yield Stueck("content", self.opening)
            yield Stueck(
                "tool_call",
                werkzeugaufrufe=[
                    Werkzeugaufruf(id="a1", name="read_file", argumente={"path": "note.txt"})
                ],
            )
        else:
            for kind, text in self.closing:
                yield Stueck(kind, text)
        yield Stueck(
            "stats",
            daten={"dauer_sekunden": 0.0, "haeppchen": 1, "endpunkt": self.id, "ende_grund": "stop"},
        )


def _run_two_rounds(client, tmp_path, provider: _WriteToolWrite) -> tuple[dict, list[dict]]:
    """The stored answer and the streamed events of one two-round run."""
    (tmp_path / "note.txt").write_text("hello", encoding="utf-8")
    client.app.state.werkzeuge = WerkzeugRegistry([], shell_an=True)
    client.app.state.config.features.mcp = True
    client.app.state.discovery.zustaende["test"].endpunkt.capabilities.tool_calls = True
    chat = client.post("/api/v1/chats", json={"title": "Rounds"}).json()
    client.patch(f"/api/v1/chats/{chat['id']}", json={"working_dirs": [str(tmp_path)]})
    provider_setzen(client, provider)
    response = client.post(
        "/api/v1/chat/completions",
        json={"chat_id": chat["id"], "endpoint_id": "test", "content": "What does it say?"},
    )
    events = [
        json.loads(line[len("data:"):])
        for line in response.text.splitlines()
        if line.startswith("data:")
    ]
    rows = client.get(f"/api/v1/chats/{chat['id']}/messages").json()["nachrichten"]
    return [row for row in rows if row["role"] == "assistant"][-1], events


TABLE = "| a | b |\n|---|---|\n| 1 | 2 |"


def test_a_written_round_stands_a_blank_line_below_the_round_before(client, tmp_path):
    """Round one wrote "Ich schaue nach." and called a tool; round two wrote
    a table. Joined as they came, the table stood on the sentence's line and
    was not drawn. The window, the row and the stored sections all get the
    one blank line, and so does the round's own turn: the rounds joined are
    still the stored text, so the next request rebuilds them as sent."""
    provider = _WriteToolWrite("Ich schaue nach.", [("content", TABLE)])
    answer, events = _run_two_rounds(client, tmp_path, provider)

    assert answer["content"] == "Ich schaue nach.\n\n" + TABLE
    # The window draws the same text from the events.
    assert "".join(e["text"] for e in events if e["typ"] == "content") == answer["content"]
    # The section lengths still cut the stored string.
    assert [(s["kind"], s.get("length")) for s in answer["stats"]["sections"]] == [
        ("content", 16), ("tool", None), ("content", len(TABLE) + 2),
    ]
    # The rounds' texts in the tool log join to the stored text.
    rounds = {e["runde"]: e["text"] for e in answer["stats"]["werkzeuge"] if "text" in e}
    assert answer["content"].startswith("".join(rounds.values()))


def test_a_lifted_answer_stands_a_blank_line_below_the_round_before(client, tmp_path):
    """The closing round only thought the table: lifted into the answer, it
    starts one blank line below the opening, and the sections add up."""
    provider = _WriteToolWrite("Ich schaue nach.", [("reasoning", TABLE)])
    answer, _ = _run_two_rounds(client, tmp_path, provider)

    assert answer["stats"].get("denktext_als_antwort") is True
    assert answer["content"] == "Ich schaue nach.\n\n" + TABLE
    assert [(s["kind"], s.get("length")) for s in answer["stats"]["sections"]] == [
        ("content", 16), ("tool", None), ("content", len(TABLE) + 2),
    ]


def test_a_round_that_already_starts_apart_gets_no_second_blank_line(client, tmp_path):
    """Silence probe: an opening that ends with a blank line, and a closing
    round whose first pieces are only line breaks, are joined as written."""
    provider = _WriteToolWrite("Ich schaue nach.\n", [("content", "\n"), ("content", TABLE)])
    answer, _ = _run_two_rounds(client, tmp_path, provider)

    assert answer["content"] == "Ich schaue nach.\n\n" + TABLE
    assert [(s["kind"], s.get("length")) for s in answer["stats"]["sections"]] == [
        ("content", 17), ("tool", None), ("content", len(TABLE) + 1),
    ]


def test_a_real_end_survives_an_intermediate_save():
    """The save before a permission prompt keeps the end the tool call set:
    the wait on a person is no thinking. The log itself is left as it was,
    so the closing write still has every end."""
    log = SectionLog()
    _feed(
        log,
        _event("reasoning", 10, text="Run it."),
        _event("tool_call_laeuft", 20, aufruf_id="a1"),
    )
    expected = [{"kind": "reasoning", "length": 7, "begin_ms": 10, "end_ms": 20}]
    assert log.stored("", "Run it.", final=False) == expected
    _feed(log, _event("kontext", 25))
    assert log.stored("", "Run it.", final=False) == expected
    assert log.stored("", "Run it.", final=True) == expected


def test_a_call_without_an_id_keeps_its_place_between_two_stretches():
    """Some providers send a call with an empty id; the window still draws
    thought, tool, thought — so must the stored order."""
    log = SectionLog()
    _feed(
        log,
        _event("reasoning", 10, text="A"),
        _event("tool_call", 20, aufruf_id=""),
        _event("tool_call", 21),
        _event("tool_result", 30, aufruf_id=""),
        _event("tool_result", 31, aufruf_id=""),
        _event("reasoning", 40, text="B"),
    )
    assert [(s["kind"], s.get("call_id")) for s in log.stored("", "AB", final=True)] == [
        ("reasoning", None), ("tool", ""), ("tool", ""), ("reasoning", None),
    ]
