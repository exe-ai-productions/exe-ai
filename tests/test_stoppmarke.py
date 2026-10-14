"""The service's side of the request to end it (app/stoppmarke.py)."""

from __future__ import annotations

import asyncio
import signal
from pathlib import Path

from app import stoppmarke


def test_the_marker_lies_beside_the_note_under_the_same_port(tmp_path: Path):
    marker = stoppmarke.marker_file(tmp_path, 8090)
    assert marker == tmp_path / ".dienst-8090.stop"
    # A scan for notes (``.dienst-*.json``) never meets it.
    assert marker.suffix != ".json"


async def test_a_marker_ends_the_service_once_and_is_taken_away(tmp_path: Path):
    marker = stoppmarke.marker_file(tmp_path, 8090)
    ended: list[int] = []
    watch = asyncio.create_task(
        stoppmarke.watch(marker, end=lambda: ended.append(1), interval=0.01)
    )
    await asyncio.sleep(0.05)
    assert ended == [] and not watch.done()

    marker.write_text("stop\n", encoding="utf-8")
    await asyncio.wait_for(watch, timeout=2)

    assert ended == [1]
    assert not marker.exists()


async def test_without_a_marker_nothing_ends(tmp_path: Path):
    """Silence probe: the watch asks for nothing until the file is there."""
    ended: list[int] = []
    watch = asyncio.create_task(
        stoppmarke.watch(stoppmarke.marker_file(tmp_path, 8090), end=lambda: ended.append(1), interval=0.01)
    )
    await asyncio.sleep(0.1)
    watch.cancel()
    assert ended == []


def test_a_leftover_marker_is_cleared_before_the_watch_begins(tmp_path: Path):
    marker = stoppmarke.marker_file(tmp_path, 8090)
    marker.write_text("stop\n", encoding="utf-8")
    stoppmarke.clear(marker)
    assert not marker.exists()
    stoppmarke.clear(marker)  # nothing there: no error


def test_the_request_ends_the_process_the_way_the_window_closing_does(monkeypatch):
    raised: list[int] = []
    monkeypatch.setattr(signal, "raise_signal", lambda sig: raised.append(sig))
    stoppmarke._end_like_a_signal()
    assert raised == [signal.SIGTERM]


def test_the_service_watches_only_where_the_signal_is_the_end_of_the_process():
    """The watch is started on Windows alone, after a leftover marker is
    cleared, and stopped with the service's shutdown."""
    from pathlib import Path as P

    source = (P(__file__).resolve().parent.parent / "app" / "main.py").read_text(encoding="utf-8")
    assert 'if sys.platform == "win32":' in source
    start = source.index("stoppmarke.clear(marker)")
    assert source.index("stoppmarke.watch(marker)") > start
    assert "stop_watch.cancel()" in source
