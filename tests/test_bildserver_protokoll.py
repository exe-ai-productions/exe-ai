"""The picture server's log: what sd-server says, for the window's server log.

Finished lines are kept, a redrawn progress bar only as the frame its line
ends on, a replaced server's reader writes nothing, the ring holds a fixed
number of lines, and the route hands the lines out.
"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app import bildturbo
from app.bildturbo import Bildturbo


class _Prozess:
    """Only its identity matters: the reader compares it with the server's."""


def _server(tmp_path: Path) -> tuple[Bildturbo, _Prozess]:
    server = Bildturbo(tmp_path)
    prozess = _Prozess()
    server._prozess = prozess  # type: ignore[assignment]
    return server, prozess


def test_finished_lines_are_kept_and_the_rest_is_handed_back(tmp_path: Path):
    server, prozess = _server(tmp_path)
    rest = server._zeilen_aufnehmen("loading model\nmodel loaded\nlisten", prozess)  # type: ignore[arg-type]
    assert server.protokoll() == ["loading model", "model loaded"]
    assert rest == "listen"
    rest = server._zeilen_aufnehmen(rest + "ing on 127.0.0.1\n", prozess)  # type: ignore[arg-type]
    assert server.protokoll()[-1] == "listening on 127.0.0.1"
    assert rest == ""


def test_a_progress_bar_is_kept_as_its_last_frame(tmp_path: Path):
    server, prozess = _server(tmp_path)
    rest = server._zeilen_aufnehmen("  1/20 |#   |\r  2/20 |##  |\r  3/20 |", prozess)  # type: ignore[arg-type]
    # The unfinished line keeps only the bar's latest frame.
    assert rest == "  3/20 |"
    server._zeilen_aufnehmen(rest + "### |\r 20/20 |####|\n", prozess)  # type: ignore[arg-type]
    assert server.protokoll() == [" 20/20 |####|"]


def test_empty_lines_are_not_kept(tmp_path: Path):
    server, prozess = _server(tmp_path)
    server._zeilen_aufnehmen("\n\n   \nready\n", prozess)  # type: ignore[arg-type]
    assert server.protokoll() == ["ready"]


def test_a_replaced_server_s_reader_writes_nothing(tmp_path: Path):
    server, alt = _server(tmp_path)
    server._prozess = _Prozess()  # type: ignore[assignment]
    server._zeilen_aufnehmen("the old server's last words\n", alt)  # type: ignore[arg-type]
    assert server.protokoll() == []


def test_the_log_keeps_a_fixed_number_of_lines(tmp_path: Path):
    server, prozess = _server(tmp_path)
    text = "".join(f"line {n}\n" for n in range(bildturbo.PROTOKOLL_ZEILEN + 5))
    server._zeilen_aufnehmen(text, prozess)  # type: ignore[arg-type]
    zeilen = server.protokoll()
    assert len(zeilen) == bildturbo.PROTOKOLL_ZEILEN
    assert zeilen[0] == "line 5"


def test_the_route_hands_out_the_lines(client: TestClient):
    server = client.app.state.bildturbo
    prozess = _Prozess()
    server._prozess = prozess
    try:
        server._zeilen_aufnehmen("picture server ready\n", prozess)
        answer = client.get("/api/v1/bild/server/log")
        assert answer.status_code == 200
        assert answer.json()[-1] == "picture server ready"
    finally:
        server._prozess = None
        server._protokoll.clear()
