"""A picture server that ends under a drawing says why, as the sd-cli path does.

The connection of a request breaks when its server dies; the sentence "the
picture could not be drawn" then carries the signal that ended the server and
its telling lines, the same last words ``bildrunner.last_words`` makes of the
painter's log. A server that answers with a failure of its own, one that was
stopped and one that still lives keep their words."""

from __future__ import annotations

import subprocess
import sys
import threading
from pathlib import Path

import httpx
import pytest

from app import bildturbo as bt
from app.bildturbo import Bildturbo, BildturboFehler

ERROR_LINE = "[E] Conditioner model tensor 'x' not in model metadata --- model_manager.cpp:763"
ASSERT_LINE = "ggml-metal.m:1234: GGML_ASSERT(false) failed"


class _Prozess:
    """A server process that is alive until the request ends it."""

    pid = 4321

    def __init__(self, code: int = -6) -> None:
        self._code: int | None = None
        self._final = code

    def die(self) -> None:
        self._code = self._final

    def poll(self) -> int | None:
        return self._code


def _turbo(tmp_path: Path, lines: list[str], code: int = -6) -> tuple[Bildturbo, _Prozess]:
    turbo = Bildturbo(tmp_path)
    process = _Prozess(code)
    turbo._prozess = process  # type: ignore[assignment]
    turbo._war_bereit = True
    turbo._protokoll.extend(lines)
    # Only a server that has a reader event is waited for; the setup stays
    # valid for a program without one.
    if hasattr(turbo, "_leser_fertig"):
        turbo._leser_fertig.set()
    return turbo, process


def _post_ends_the_server(monkeypatch, process: _Prozess) -> None:
    def _post(url, **kwargs):
        process.die()
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(bt.httpx, "post", _post)


@pytest.mark.skipif(sys.platform == "win32", reason="the child ends by a POSIX signal")
def test_a_server_that_dies_under_a_drawing_gives_the_signal_and_its_telling_lines(
    tmp_path, monkeypatch
):
    turbo, process = _turbo(tmp_path, ["loading", ERROR_LINE, ASSERT_LINE, "backtrace 0x1"])
    _post_ends_the_server(monkeypatch, process)
    with pytest.raises(BildturboFehler) as failure:
        turbo.zeichnen({"prompt": "x"})
    assert failure.value.grund == "bild.gescheitert"
    said = failure.value.protokoll.split("\n")
    assert said[0] == "[Exe AI] Command terminated by signal 6: SIGABRT (Abort trap)"
    assert said[1:] == [ERROR_LINE, ASSERT_LINE]


@pytest.mark.skipif(sys.platform == "win32", reason="the child ends by a POSIX signal")
def test_without_a_telling_line_the_server_log_shows_no_progress_bar_and_no_control_sequence(
    tmp_path, monkeypatch
):
    """The loading bars the server redraws are no last words: the lines below
    the note are the words that stood around them, without the sequence that
    erased the line."""
    bar = "|" + "#" * 40 + "| 598/626 - 325.55MB/s \x1b[K"
    words = "|" + "#" * 40 + "| 626/626 - 331.15MB/s \x1b[K[I] loading tensors completed, taking 21.39s"
    turbo, process = _turbo(tmp_path, ["[I] loading", bar, words, bar])
    _post_ends_the_server(monkeypatch, process)
    with pytest.raises(BildturboFehler) as failure:
        turbo.zeichnen({"prompt": "x"})
    said = failure.value.protokoll.split("\n")
    assert said[0] == "[Exe AI] Command terminated by signal 6: SIGABRT (Abort trap)"
    assert said[1:] == ["[I] loading", "[I] loading tensors completed, taking 21.39s"]
    assert "\x1b" not in failure.value.protokoll and "[K" not in failure.value.protokoll


@pytest.mark.skipif(sys.platform == "win32", reason="the child ends by a POSIX signal")
def test_a_log_of_nothing_but_bars_leaves_the_signal_alone(tmp_path, monkeypatch):
    bar = "|" + "#" * 40 + "| 598/626 - 325.55MB/s \x1b[K"
    turbo, process = _turbo(tmp_path, [bar, bar])
    _post_ends_the_server(monkeypatch, process)
    with pytest.raises(BildturboFehler) as failure:
        turbo.zeichnen({"prompt": "x"})
    assert failure.value.protokoll == "[Exe AI] Command terminated by signal 6: SIGABRT (Abort trap)"


@pytest.mark.skipif(sys.platform == "win32", reason="the child ends by a POSIX signal")
def test_the_connection_that_breaks_while_the_job_is_looked_at_says_it_too(tmp_path, monkeypatch):
    turbo, process = _turbo(tmp_path, [ERROR_LINE])

    class _Job:
        def raise_for_status(self):
            pass

        def json(self):
            return {"id": "job-1"}

    monkeypatch.setattr(bt.httpx, "post", lambda url, **kwargs: _Job())

    def _get(url, **kwargs):
        process.die()
        raise httpx.ReadError("closed")

    monkeypatch.setattr(bt.httpx, "get", _get)
    monkeypatch.setattr(bt.time, "sleep", lambda seconds: None)
    with pytest.raises(BildturboFehler) as failure:
        turbo.zeichnen({"prompt": "x"})
    assert failure.value.protokoll.endswith(ERROR_LINE)
    assert "SIGABRT" in failure.value.protokoll


def test_without_a_telling_line_the_last_lines_stand_below_the_note(tmp_path, monkeypatch):
    turbo, process = _turbo(tmp_path, ["one", "two"])
    _post_ends_the_server(monkeypatch, process)
    with pytest.raises(BildturboFehler) as failure:
        turbo.zeichnen({"prompt": "x"})
    assert failure.value.protokoll.split("\n")[1:] == ["one", "two"]


@pytest.mark.skipif(sys.platform == "win32", reason="the child ends by a POSIX signal")
def test_an_enlarging_that_loses_its_server_says_so_too(tmp_path, monkeypatch):
    turbo, process = _turbo(tmp_path, [ERROR_LINE])
    _post_ends_the_server(monkeypatch, process)
    with pytest.raises(BildturboFehler) as failure:
        turbo.upscale("AAAA", "x4")
    assert failure.value.grund == "bild.gescheitert"
    assert "SIGABRT" in failure.value.protokoll and ERROR_LINE in failure.value.protokoll


def test_silence_a_server_that_still_lives_leaves_the_sentence_alone(tmp_path, monkeypatch):
    monkeypatch.setattr(bt, "ABSTURZ_WARTE_SEKUNDEN", 0.2, raising=False)
    turbo, _ = _turbo(tmp_path, [ERROR_LINE])

    def _post(url, **kwargs):
        raise httpx.ConnectError("busy")

    monkeypatch.setattr(bt.httpx, "post", _post)
    with pytest.raises(BildturboFehler) as failure:
        turbo.zeichnen({"prompt": "x"})
    assert failure.value.protokoll is None


def test_silence_a_job_that_failed_keeps_its_own_message(tmp_path, monkeypatch):
    turbo, _ = _turbo(tmp_path, [ERROR_LINE])

    class _Answer:
        def __init__(self, body):
            self._body = body

        def raise_for_status(self):
            pass

        def json(self):
            return self._body

    monkeypatch.setattr(bt.httpx, "post", lambda url, **kwargs: _Answer({"id": "j"}))
    monkeypatch.setattr(
        bt.httpx, "get",
        lambda url, **kwargs: _Answer({"status": "failed", "error": {"message": "out of memory"}}),
    )
    with pytest.raises(BildturboFehler) as failure:
        turbo.zeichnen({"prompt": "x"})
    assert failure.value.protokoll == "out of memory"


def test_silence_a_stopped_drawing_stays_the_quiet_stop(tmp_path, monkeypatch):
    turbo, process = _turbo(tmp_path, [ERROR_LINE])

    def _post(url, **kwargs):
        turbo._abgebrochen = True
        process.die()
        raise httpx.ConnectError("ended under it")

    monkeypatch.setattr(bt.httpx, "post", _post)
    with pytest.raises(BildturboFehler) as failure:
        turbo.zeichnen({"prompt": "x"})
    assert failure.value.grund == "bild.abgebrochen"
    assert failure.value.protokoll is None


@pytest.mark.skipif(sys.platform == "win32", reason="the child ends by a POSIX signal")
def test_a_real_process_that_aborts_is_read_to_its_last_line(tmp_path, monkeypatch):
    """The reader thread, the event and the exit code of a child that prints
    its reason and aborts, nothing of it faked but the HTTP call."""
    script = (
        "import os, sys\n"
        f"print({ERROR_LINE!r}, flush=True)\n"
        f"print({ASSERT_LINE!r}, flush=True)\n"
        "os.abort()\n"
    )
    turbo = Bildturbo(tmp_path)
    child = subprocess.Popen(
        [sys.executable, "-c", script], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    turbo._prozess = child
    turbo._war_bereit = True
    threading.Thread(
        target=turbo._zaehler_lesen, args=(child, getattr(turbo, "_leser_fertig", None)), daemon=True
    ).start()

    def _post(url, **kwargs):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(bt.httpx, "post", _post)
    # The child is alive at the door of the draw, as the server is when its
    # request goes out; it ends a moment later.
    monkeypatch.setattr(Bildturbo, "laeuft", lambda self: True)
    with pytest.raises(BildturboFehler) as failure:
        turbo.zeichnen({"prompt": "x"})
    said = failure.value.protokoll.split("\n")
    assert said[0].startswith("[Exe AI] Command terminated by signal 6: SIGABRT")
    assert said[1:] == [ERROR_LINE, ASSERT_LINE]
