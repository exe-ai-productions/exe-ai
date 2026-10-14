"""The fixed block is drawn in as many colours as the history above it:
the full ones where the terminal reports them. Everywhere else — a terminal
that reports none, an environment that asks for no colours — it is drawn
the way the screen draws by itself."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import httpx
import pytest

from cli import themes
from tests.cli.program import (
    A_TERMINAL,
    ENTER,
    FULL,
    Run,
    in_full_colours,
    run_client,
    terminal,
)
from tests.cli.stub_service import StubService, eventually

OF_256 = "38;5;"


def accent_in_full_colours() -> str:
    """The accent of the default look as a terminal is sent it in 24 bits."""
    return in_full_colours(themes.DEFAULT_LOOK, "accent")


def block_as_sent(
    stub: StubService,
    http: httpx.Client,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    environment: dict[str, str],
) -> str:
    """Runs the client in a terminal of that environment and returns what
    the fixed block sent it, colour codes included."""
    themes.set_look(themes.DEFAULT_LOOK)
    sent, output = terminal(monkeypatch, environment)

    def drive(run: Run, type_in: Callable[[str], None]) -> None:
        run.parts()
        eventually(lambda: stub.watchers == 1)
        type_in(f"/quit{ENTER}")

    assert run_client(http, tmp_path, monkeypatch, drive, output=output).code == 0
    return sent.getvalue()


def test_the_accent_of_the_default_look_in_full_colours() -> None:
    # The default look has no accent of its own: this is its text colour.
    assert accent_in_full_colours() == "38;2;236;235;230"


def test_where_the_terminal_reports_the_full_colours_the_block_is_drawn_in_them(
    stub: StubService, stub_http: httpx.Client, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    environment = {"TERM": "xterm-256color", "COLORTERM": "truecolor", **A_TERMINAL}
    block = block_as_sent(stub, stub_http, tmp_path, monkeypatch, environment)
    assert accent_in_full_colours() in block
    assert OF_256 not in block


def test_a_terminal_that_reports_no_full_colours_gets_the_block_as_before(
    stub: StubService, stub_http: httpx.Client, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    block = block_as_sent(stub, stub_http, tmp_path, monkeypatch, {"TERM": "xterm", **A_TERMINAL})
    assert FULL not in block
    assert OF_256 in block


def test_an_environment_that_asks_for_no_colours_gets_none_in_the_block(
    stub: StubService, stub_http: httpx.Client, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    environment = {"TERM": "xterm-256color", "COLORTERM": "truecolor", "NO_COLOR": "1", **A_TERMINAL}
    block = block_as_sent(stub, stub_http, tmp_path, monkeypatch, environment)
    assert FULL not in block
    assert OF_256 not in block


def test_a_depth_the_environment_names_itself_is_kept(
    stub: StubService, stub_http: httpx.Client, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    environment = {
        "TERM": "xterm-256color",
        "COLORTERM": "truecolor",
        "PROMPT_TOOLKIT_COLOR_DEPTH": "DEPTH_8_BIT",
        **A_TERMINAL,
    }
    block = block_as_sent(stub, stub_http, tmp_path, monkeypatch, environment)
    assert FULL not in block
    assert OF_256 in block
