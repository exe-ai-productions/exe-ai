"""Inside the window's tab the client follows the look and the language the
window page shows: the service's event stream carries ``window_theme``, and
the client writes its history again in the new colours — like after
``/theme`` — or speaks the new language — like after ``/language`` —
without remembering anything. Outside the window's tab, and for a name it
does not know or already uses, nothing happens."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest

from cli import themes
from cli.texts import Texts
from tests.cli.program import (
    ENTER,
    FULL_COLOURS,
    Run,
    in_full_colours,
    run_client,
    terminal,
)
from tests.cli.stub_service import StubService, eventually

EMPTIED = "\x1b[2J"
ASKED = "What grows in the shade"
ANSWERED = "Hello."


@pytest.fixture(autouse=True)
def the_default_look() -> None:
    themes.set_look(themes.DEFAULT_LOOK)
    yield
    themes.set_look(themes.DEFAULT_LOOK)


def after_one_exchange_announced(
    stub: StubService,
    http: httpx.Client,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    announcements: list[dict],
    *,
    in_window: bool = True,
) -> str:
    """Runs the client, has one message answered, lets the service announce
    each of ``announcements`` in turn and returns what the terminal was sent
    from then on. The client is told to run in the window's tab unless
    ``in_window`` is False."""
    if in_window:
        monkeypatch.setenv(themes.WINDOW_VARIABLE, "1")
    else:
        monkeypatch.delenv(themes.WINDOW_VARIABLE, raising=False)
    sent, output = terminal(monkeypatch, FULL_COLOURS)
    since: list[int] = []

    def drive(run: Run, type_in: Callable[[str], None]) -> None:
        ctx = run.parts()
        eventually(lambda: stub.watchers == 1)
        type_in(ASKED + ENTER)
        eventually(lambda: ANSWERED in sent.getvalue())
        eventually(lambda: stub.running() == 0 and not ctx.session.answering)
        since.append(len(sent.getvalue()))
        for fields in announcements:
            stub.announce("window_theme", **fields)
        # The stream is read by one thread, in order: once a server's word
        # sent behind them has been taken, every announcement before it has
        # been handled — also the ones that change nothing.
        stub.announce("server_state", endpoint_id="sentinel", server_state="idle")
        eventually(lambda: ctx.events._states.get("sentinel") == "idle")  # type: ignore[attr-defined]
        type_in("/quit" + ENTER)

    assert run_client(http, tmp_path, monkeypatch, drive, output=output).code == 0
    return sent.getvalue()[since[0] :]


def test_in_the_window_the_client_follows_the_look_the_page_shows(
    stub: StubService, stub_http: httpx.Client, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    shown = after_one_exchange_announced(
        stub, stub_http, tmp_path, monkeypatch, [{"theme": "pearl"}]
    )
    assert themes.current().name == "pearl"
    # The window is emptied — at once, and again in the turn that writes the
    # history, as for every redraw asked for from outside the client's own
    # turn — and what stands after the last emptying is the whole exchange,
    # once, in the new ink.
    assert shown.count(EMPTIED) >= 1
    again = shown.split(EMPTIED)[-1]
    assert ASKED in again and again.count(ANSWERED) == 1
    assert in_full_colours("pearl", "text") in again
    assert in_full_colours(themes.DEFAULT_LOOK, "text") not in again
    # Nothing is remembered: the window's look is the page's, not the client's.
    assert not (tmp_path / "cli.json").exists()


def test_the_same_name_again_draws_nothing_new(
    stub: StubService, stub_http: httpx.Client, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    shown = after_one_exchange_announced(
        stub, stub_http, tmp_path, monkeypatch, [{"theme": "pearl"}, {"theme": "pearl"}]
    )
    # Once more would be a second history on the same window: what stands
    # after the last emptying is the same exchange, written once.
    assert shown.split(EMPTIED)[-1].count(ANSWERED) == 1
    assert shown.count(EMPTIED) == 2


@pytest.mark.parametrize(
    "fields",
    [{"theme": "neon"}, {"theme": ""}, {"theme": themes.AUTO_LOOK}, {"theme": themes.DEFAULT_LOOK}, {}, {"theme": 7}],
)
def test_a_name_that_is_unknown_empty_auto_or_in_use_changes_nothing(
    stub: StubService,
    stub_http: httpx.Client,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fields: dict,
) -> None:
    shown = after_one_exchange_announced(stub, stub_http, tmp_path, monkeypatch, [fields])
    assert EMPTIED not in shown
    assert themes.current().name == themes.DEFAULT_LOOK
    assert not (tmp_path / "cli.json").exists()


def test_outside_the_windows_tab_the_event_changes_nothing(
    stub: StubService, stub_http: httpx.Client, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    shown = after_one_exchange_announced(
        stub, stub_http, tmp_path, monkeypatch, [{"theme": "pearl"}], in_window=False
    )
    assert EMPTIED not in shown
    assert themes.current().name == themes.DEFAULT_LOOK


def words(language: str, key: str) -> str:
    return Texts(language).t(key)


def test_the_language_of_the_window_becomes_the_clients_in_the_tab(
    stub: StubService, stub_http: httpx.Client, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The client was started in English. The page shows German: the lines
    that stand from now on speak German, and the requests to the service
    name German — without ``cli.json``."""
    monkeypatch.setenv(themes.WINDOW_VARIABLE, "1")
    sent, output = terminal(monkeypatch, FULL_COLOURS)
    seen: dict[str, Any] = {}

    def drive(run: Run, type_in: Callable[[str], None]) -> None:
        ctx = run.parts()
        eventually(lambda: stub.watchers == 1)
        seen["before"] = (ctx.texts.language, ctx.client.language)
        stub.announce("window_theme", language="de")
        eventually(lambda: ctx.texts.language == "de")
        seen["after"] = (ctx.texts.language, ctx.client.language)
        # The client's own lines now come in German: the list of its
        # commands names each one in the new language.
        type_in("/help" + ENTER)
        eventually(lambda: words("de", "cli.cmd_help") in sent.getvalue())
        type_in("/quit" + ENTER)

    assert run_client(stub_http, tmp_path, monkeypatch, drive, output=output).code == 0
    assert seen["before"] == ("en", "en")
    assert seen["after"] == ("de", "de")
    assert not (tmp_path / "cli.json").exists()


@pytest.mark.parametrize("fields", [{"language": "en"}, {"language": "xx"}, {"language": ""}, {"language": 7}])
def test_the_language_in_use_or_unknown_changes_nothing(
    stub: StubService,
    stub_http: httpx.Client,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fields: dict,
) -> None:
    monkeypatch.setenv(themes.WINDOW_VARIABLE, "1")
    seen: dict[str, Any] = {}

    def drive(run: Run, type_in: Callable[[str], None]) -> None:
        ctx = run.parts()
        eventually(lambda: stub.watchers == 1)
        stub.announce("window_theme", **fields)
        stub.announce("server_state", endpoint_id="sentinel", server_state="idle")
        eventually(lambda: ctx.events._states.get("sentinel") == "idle")  # type: ignore[attr-defined]
        seen["language"] = (ctx.texts.language, ctx.client.language)
        type_in("/quit" + ENTER)

    assert run_client(stub_http, tmp_path, monkeypatch, drive).code == 0
    assert seen["language"] == ("en", "en")


def test_a_look_change_leaves_the_language_as_it_is_and_the_other_way_round(
    stub: StubService, stub_http: httpx.Client, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(themes.WINDOW_VARIABLE, "1")
    seen: dict[str, Any] = {}

    def drive(run: Run, type_in: Callable[[str], None]) -> None:
        ctx = run.parts()
        eventually(lambda: stub.watchers == 1)
        stub.announce("window_theme", theme="pearl")
        eventually(lambda: themes.current().name == "pearl")
        seen["after_look"] = (ctx.texts.language, themes.current().name)
        stub.announce("window_theme", language="de")
        eventually(lambda: ctx.texts.language == "de")
        seen["after_language"] = (ctx.texts.language, themes.current().name)
        type_in("/quit" + ENTER)

    assert run_client(stub_http, tmp_path, monkeypatch, drive).code == 0
    assert seen["after_look"] == ("en", "pearl")
    assert seen["after_language"] == ("de", "pearl")


def test_outside_the_windows_tab_a_language_event_changes_nothing(
    stub: StubService, stub_http: httpx.Client, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(themes.WINDOW_VARIABLE, raising=False)
    seen: dict[str, Any] = {}

    def drive(run: Run, type_in: Callable[[str], None]) -> None:
        ctx = run.parts()
        eventually(lambda: stub.watchers == 1)
        stub.announce("window_theme", language="de")
        stub.announce("server_state", endpoint_id="sentinel", server_state="idle")
        eventually(lambda: ctx.events._states.get("sentinel") == "idle")  # type: ignore[attr-defined]
        seen["language"] = (ctx.texts.language, ctx.client.language)
        type_in("/quit" + ENTER)

    assert run_client(stub_http, tmp_path, monkeypatch, drive).code == 0
    assert seen["language"] == ("en", "en")
