"""The whole client against the stand-in service: started the way a user
starts it, typed into through a pipe, with nothing replaced between the
keys and the service's addresses.

Each module has tests of its own. What only shows here is whether they
still fit together — a message, an answer that streams in, a tool that asks
for permission, the answer to that, the status line, an event of the
service — and whether the stand-in answers the way the client expects the
service to.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest

from cli import themes
from cli.interfaces import Context
from cli.main import main
from cli.texts import Texts
from test_stream import shown_text
from tests.cli import stub_service as service
from tests.cli.program import Run, run_client
from tests.cli.stub_service import KEY_HEADER, KEY_REFUSAL, StubService, eventually

ENTER = "\r"
ESCAPE = "\x1b"
ADDRESS = "http://stub.test"

# One answer with everything in it: thinking, text, a tool that waits for
# permission, its call and its result, the context count, the numbers.
NOTE = {"path": "note.txt", "content": "Buy seeds"}
ANSWER_WITH_A_TOOL = [
    service.reasoning("The user wants a note."),
    service.content("I will write that down.\n\n"),
    service.tool_confirm("write_file", NOTE, "call-1", reason="Writes a file"),
    service.tool_call("write_file", NOTE, "call-1", server="files"),
    service.tool_result("write_file", "call-1", "Wrote 9 characters to note.txt", seconds=0.2),
    service.context(1234),
    service.content("The note is written.\n"),
    service.stats(dauer_sekunden=2.0, tokens_pro_sekunde=20.0, modell="Local Model"),
    service.done(),
]


@pytest.fixture(autouse=True)
def the_default_look() -> Iterator[None]:
    yield
    themes.set_look(themes.DEFAULT_LOOK)


class Session(Run):
    """One run of the client, driven from the test: what it was started
    with, what it is doing right now, and what it left behind."""

    def __init__(self) -> None:
        super().__init__()
        self.shown = ""
        self.html = ""


def run(
    http: httpx.Client,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    drive: Callable[[Session, Callable[[str], None]], None],
) -> Session:
    """Starts the client in this thread and hands ``drive`` — in a thread of
    its own — the running session and a way to type into it. Returns once
    the client has left, with what it showed."""
    session = Session()
    run_client(http, tmp_path, monkeypatch, drive, run=session)  # type: ignore[arg-type]
    # What was shown, read back from an export of the history.
    target = tmp_path / "shown.html"
    session.parts().screen.export(target)
    session.html = target.read_text(encoding="utf-8")
    session.shown = shown_text(session.html)
    return session


def status_lines(shown: str) -> list[str]:
    """The third status line as it stood each time a line was sent: the
    one that sets a count against the model's window."""
    return [line for line in shown.splitlines() if "/131072" in line]


def status_now(ctx: Context) -> str:
    return "".join(text for _, text in ctx.status.fragments(200))


def carries(sent: dict[str, Any], **fields: Any) -> bool:
    """Whether a request's body says at least this."""
    return all(sent.get(name) == value for name, value in fields.items())


def test_a_message_a_tool_that_asks_and_its_answer_from_the_keys_to_the_service(
    stub: StubService, stub_http: httpx.Client, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stub.script = ANSWER_WITH_A_TOOL
    # The server behind the model is not reachable when the client starts.
    stub.models[0]["server_state"] = "offline"
    words = Texts("en")

    def drive(session: Session, type_in: Callable[[str], None]) -> None:
        ctx = session.parts()
        # The listener stands and has asked for the word of each server.
        eventually(lambda: stub.watchers == 1)
        type_in("Please note: buy seeds" + ENTER)
        # The answer stands still at the tool's question, on both sides.
        eventually(lambda: stub.waiting_calls() == ["call-1"])
        eventually(ctx.asker.pending)
        type_in("1" + ENTER)
        eventually(lambda: stub.running() == 0 and not ctx.session.answering)
        # What the service does by itself, while the client sits idle. The
        # listener takes one event after the other, so once the second
        # shows in the status line the first stands above the input field.
        stub.announce("termin_gefeuert", cronjob_id="cron-1")
        stub.announce("server_state", endpoint_id="local", server_state="idle")
        eventually(lambda: words.t("kopf.bereit") in status_now(ctx))
        assert words.t("cronjobs.gestartet") in ctx.screen.hint_line()  # type: ignore[attr-defined]
        type_in("/quit" + ENTER)

    session = run(stub_http, tmp_path, monkeypatch, drive)
    assert session.code == 0
    shown = session.shown

    # What went to the service.
    assert len(stub.sent) == 1
    assert carries(
        stub.sent[0], chat_id="chat-1", content="Please note: buy seeds", endpoint_id="local"
    )
    assert len(stub.confirmations) == 1
    assert carries(
        stub.confirmations[0],
        generation_id="run-1",
        aufruf_id="call-1",
        erlaubt=True,
        dauerhaft=False,
    )
    # What the history shows: the answer on both sides of the tool, the
    # tool's line and what it brought back.
    assert "I will write that down." in shown
    assert "The note is written." in shown
    assert shown.index("I will write that down.") < shown.index("The note is written.")
    # The call's own line names the tool and the server it belongs to; the
    # question before it and the result after it name only the tool.
    assert [line for line in shown.splitlines() if "write_file" in line and "files" in line], shown
    assert "Wrote 9 characters to note.txt" in shown
    assert service.DECLINED not in shown
    # The service's own event stood above the input field, never in the
    # history.
    assert words.t("cronjobs.gestartet") not in shown

    # The status lines, as they stood when each line was sent: first without
    # a count, then with the one the answer reported.
    first, last = status_lines(shown)
    assert "–/131072" in first and "1234/131072" in last
    lines = shown.splitlines()
    for context_line, server in ((first, words.t("kopf.server_aus")), (last, words.t("kopf.bereit"))):
        at = lines.index(context_line)
        # The chat's line two above it, the mode's line right above it,
        # ending in the connection.
        assert "Local Model" in lines[at - 2] and server in lines[at - 2]
        assert lines[at - 1].rstrip().endswith(words.t("cli.connected"))
        assert context_line.startswith(words.t("cli.context_label"))

    # The export is a page, and it shows the same.
    assert session.html.lstrip().startswith("<!DOCTYPE html>")
    assert "write_file" in session.html and "The note is written." in session.html


def test_a_tool_the_user_declines_comes_back_as_declined(
    stub: StubService, stub_http: httpx.Client, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stub.script = ANSWER_WITH_A_TOOL

    def drive(session: Session, type_in: Callable[[str], None]) -> None:
        ctx = session.parts()
        type_in("Please note: buy seeds" + ENTER)
        eventually(lambda: stub.waiting_calls() == ["call-1"])
        eventually(ctx.asker.pending)
        type_in(ESCAPE)
        eventually(lambda: stub.running() == 0 and not ctx.session.answering)
        type_in("/quit" + ENTER)

    session = run(stub_http, tmp_path, monkeypatch, drive)
    assert session.code == 0
    assert len(stub.confirmations) == 1
    assert carries(stub.confirmations[0], aufruf_id="call-1", erlaubt=False, dauerhaft=False)
    assert service.DECLINED in session.shown
    assert "Wrote 9 characters to note.txt" not in session.shown
    # The answer went on after the refusal, as the service's does.
    assert "The note is written." in session.shown


def test_a_plain_answer_needs_no_question(
    stub: StubService, stub_http: httpx.Client, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stub.script = [service.content("Hello to you.\n"), service.context(42), service.done()]

    def drive(session: Session, type_in: Callable[[str], None]) -> None:
        ctx = session.parts()
        type_in("Please note: nothing today" + ENTER)
        eventually(lambda: stub.sent and stub.running() == 0 and not ctx.session.answering)
        assert not ctx.asker.pending()
        type_in("/quit" + ENTER)

    session = run(stub_http, tmp_path, monkeypatch, drive)
    assert session.code == 0
    assert "Hello to you." in session.shown
    assert stub.confirmations == []
    assert "42/131072" in status_lines(session.shown)[-1]


# --- Without this run's key ------------------------------------------------------


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/v1/health"),
        ("GET", "/api/v1/models"),
        ("GET", "/api/v1/runner"),
        ("POST", "/api/v1/chats"),
        ("GET", "/api/v1/chats"),
        ("POST", "/api/v1/chat/completions"),
        ("POST", "/api/v1/chat/confirm"),
        ("POST", "/api/v1/chat/stop"),
        ("GET", "/api/v1/events/stream"),
        ("GET", "/api/v1/settings/resolved"),
        ("PUT", "/api/v1/settings/global/denken"),
        ("GET", "/api/v1/tools"),
        ("GET", "/api/v1/permissions/always-allow"),
    ],
)
def test_without_the_key_the_stand_in_refuses_the_way_the_service_does(
    stub: StubService, stub_http: httpx.Client, method: str, path: str
) -> None:
    refused = stub_http.request(method, ADDRESS + path)
    assert refused.status_code == 401
    assert refused.json() == {"detail": KEY_REFUSAL}
    wrong = stub_http.request(method, ADDRESS + path, headers={KEY_HEADER: "another-key"})
    assert wrong.status_code == 401


def test_the_key_as_a_query_parameter_opens_the_event_stream_and_nothing_else(
    stub: StubService, stub_http: httpx.Client
) -> None:
    carried = {"schluessel": stub.key}
    assert stub_http.get(ADDRESS + "/api/v1/health", params=carried).status_code == 401
    with stub_http.stream("GET", ADDRESS + "/api/v1/events/stream", params=carried) as opened:
        assert opened.status_code == 200
        assert opened.headers["content-type"].startswith("text/event-stream")
    eventually(lambda: stub.watchers == 0)


def test_the_page_carries_the_key_and_needs_none(stub: StubService, stub_http: httpx.Client) -> None:
    page = stub_http.get(ADDRESS + "/app/")
    assert page.status_code == 200
    assert f'window.__SITZUNGSSCHLUESSEL__="{stub.key}"' in page.text


def test_a_client_whose_key_is_refused_ends_with_the_services_one_sentence(
    stub: StubService,
    stub_http: httpx.Client,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # A page that still carries the key of a run that is over.
    stub.page_key = "the-key-of-an-earlier-run"
    code = main(["--url", ADDRESS, "--lang", "en"], http=stub_http, prefs_path=tmp_path / "cli.json")
    assert code == 1
    said = capsys.readouterr()
    assert said.err.strip() == KEY_REFUSAL
    assert said.out == ""
    # Nothing was done on the service, and nothing is remembered of it.
    assert not any(request.startswith("POST") for request in stub.requests)
    assert not (tmp_path / "cli.json").exists()


def test_a_page_without_a_key_ends_the_client_with_the_sentence_that_names_the_address(
    stub: StubService,
    stub_http: httpx.Client,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    stub.page_key = None
    code = main(["--url", ADDRESS, "--lang", "en"], http=stub_http, prefs_path=tmp_path / "cli.json")
    assert code == 1
    assert capsys.readouterr().err.strip() == Texts("en").t(
        "fehler.dienst_antwortet_nicht", error=ADDRESS
    )
    assert stub.requests == ["GET /app/"]
