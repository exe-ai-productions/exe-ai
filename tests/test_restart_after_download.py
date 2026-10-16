"""A new build of the program, fetched while servers run, reaches those servers.

The servers here are real ``Modellrunner`` objects over stand-in programs
(shell scripts that print the engine's "model loaded" line and stay), and
the builds are real folders under a data folder; only the download is
replaced. What is measured: the servers that run restart once with the values
they ran with, the build that ran until then stays until every model is
loaded, a build that does not start is taken away again, and a server that
did not run stays off.
"""

from __future__ import annotations

import asyncio
import io
import socket
import sys
import tarfile
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from app import modellrunner, server_restart, serverdownload
from app.modellrunner import Modellrunner, RunnerFehler
from app.server_restart import Member, Restart
from app.serverdownload import BUILD, Serverdownload, gefundener_server
from tests.conftest import llama_server_name
from tests.test_serverdownload import FalscherStrom

pytestmark = pytest.mark.skipif(
    sys.platform == "win32", reason="the stand-in servers are shell scripts"
)

NEWER = "b11541"
LOADED = "llama_server: model loaded"


def _script(delay: int = 0) -> str:
    """A server that says which program it is, loads for ``delay`` seconds and
    stays."""
    return f'#!/bin/sh\necho "program $0"\nsleep {delay}\necho "{LOADED}"\nsleep 30\n'


BROKEN = '#!/bin/sh\necho "program $0"\necho "boom"\nexit 1\n'


def _lay_build(data: Path, build: str, script: str) -> Path:
    folder = data / "llama.cpp" / build / "build" / "bin"
    folder.mkdir(parents=True)
    server = folder / llama_server_name()
    server.write_text(script, encoding="utf-8")
    server.chmod(0o755)
    return server


def _archive(script: str) -> bytes:
    content = script.encode()
    memory = io.BytesIO()
    with tarfile.open(fileobj=memory, mode="w:gz") as tar:
        info = tarfile.TarInfo(f"build/bin/{llama_server_name()}")
        info.size = len(content)
        tar.addfile(info, io.BytesIO(content))
    return memory.getvalue()


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def world(tmp_path, monkeypatch):
    """A data folder with the pinned build laid out, the program of every
    runner read from it, quick polling, and the runners to stop at the end."""
    data = tmp_path / "data"
    _lay_build(data, BUILD, _script())
    models = tmp_path / "models"
    models.mkdir()
    (models / "small.gguf").write_bytes(b"x" * 2000)
    monkeypatch.setattr(modellrunner, "programm_finden", lambda vorgabe=None: gefundener_server(data))
    monkeypatch.setattr(server_restart, "POLL_S", 0.02)
    runners: dict[str, Modellrunner] = {}

    def make(name: str) -> Modellrunner:
        runner = Modellrunner(
            models, port=_free_port(), pid_datei=f".{name}.pid",
            schluessel_variable=f"RESTART_TEST_{name.upper()}_KEY",
        )
        runners[name] = runner
        return runner

    yield SimpleNamespace(data=data, models=models, make=make, runners=runners, tmp=tmp_path)
    for runner in runners.values():
        runner.stoppen()


def _wait_loaded(*runners: Modellrunner) -> None:
    end = time.monotonic() + 10
    while time.monotonic() < end and not all(r.bereit() for r in runners):
        time.sleep(0.02)
    assert all(r.bereit() for r in runners)


def _wait_done(download: Serverdownload, limit: float = 20) -> None:
    end = time.monotonic() + limit
    while time.monotonic() < end and download.laeuft():
        time.sleep(0.02)
    assert not download.laeuft()


def _fetch(world, monkeypatch, download: Serverdownload, build: str, script: str) -> None:
    monkeypatch.setattr(serverdownload.httpx, "stream", FalscherStrom(_archive(script)))
    download.starten(build)


def _program_of(runner: Modellrunner) -> str:
    """The program the running server says it is."""
    lines = [line for line in runner.protokoll() if line.startswith("program ")]
    return lines[-1] if lines else ""


def _start_chat_and_cleanup(world):
    chat = world.make("chat")
    chat.starten("small.gguf", kontext=2048, schichten=7, drafter="")
    cleanup = world.make("cleanup")
    cleanup.starten(
        "small.gguf", kontext=1024, schichten=3, drafter="", vision="",
        faeden=2, sampling={"temperature": 0.3, "top_k": 40.0},
    )
    embedding = world.make("embedding")
    _wait_loaded(chat, cleanup)
    members = [Member("chat", chat), Member("cleanup", cleanup), Member("embedding", embedding)]
    return chat, cleanup, embedding, members


def _values(lauf) -> dict:
    return {
        "modell": lauf.modell, "kontext": lauf.kontext, "schichten": lauf.schichten,
        "port": lauf.port, "drafter": lauf.drafter, "vision": lauf.vision,
        "fein": lauf.fein, "faeden": lauf.faeden, "sampling": lauf.sampling,
    }


def test_a_run_keeps_its_threads_and_generation_values(world):
    runner = world.make("chat")
    runner.starten("small.gguf", faeden=4, sampling={"temperature": 0.2})
    lauf = runner.lauf()
    assert lauf is not None
    assert lauf.faeden == 4 and lauf.sampling == {"temperature": 0.2}


def test_the_servers_that_run_start_again_on_the_new_build_with_their_values(world, monkeypatch):
    chat, cleanup, embedding, members = _start_chat_and_cleanup(world)
    before = {r: _values(r.lauf()) for r in (chat, cleanup)}
    assert BUILD in _program_of(chat)

    download = Serverdownload(world.data, Restart(members))
    _fetch(world, monkeypatch, download, NEWER, _script())
    _wait_done(download)

    stand = download.stand()
    assert stand is not None and stand.fertig and stand.fehler is None
    for runner in (chat, cleanup):
        assert runner.bereit()
        assert NEWER in _program_of(runner)
        assert _values(runner.lauf()) == before[runner]
    # The one that did not run is not started.
    assert not embedding.laeuft() and embedding.protokoll() == []
    assert not (world.data / "llama.cpp" / BUILD).exists()


def test_the_old_build_stays_until_every_model_is_loaded(world, monkeypatch):
    chat, cleanup, embedding, members = _start_chat_and_cleanup(world)
    download = Serverdownload(world.data, Restart(members))
    # The new build loads for a second before it says so.
    _fetch(world, monkeypatch, download, NEWER, _script(delay=1))
    seen_while_loading = False
    end = time.monotonic() + 20
    while download.laeuft() and time.monotonic() < end:
        if (chat.laeuft() or cleanup.laeuft()) and not (chat.bereit() and cleanup.bereit()):
            seen_while_loading = seen_while_loading or (world.data / "llama.cpp" / BUILD).exists()
        time.sleep(0.01)
    assert seen_while_loading
    assert not (world.data / "llama.cpp" / BUILD).exists()


def test_a_build_that_does_not_start_is_taken_away_and_the_servers_run_on_the_old_one(world, monkeypatch):
    chat, cleanup, embedding, members = _start_chat_and_cleanup(world)
    before = {r: _values(r.lauf()) for r in (chat, cleanup)}

    download = Serverdownload(world.data, Restart(members))
    _fetch(world, monkeypatch, download, NEWER, BROKEN)
    _wait_done(download)

    stand = download.stand()
    assert stand is not None and not stand.fertig and stand.fehler == "fehlgeschlagen"
    assert not (world.data / "llama.cpp" / NEWER).exists()
    assert (world.data / "llama.cpp" / BUILD).exists()
    found = gefundener_server(world.data)
    assert found is not None and BUILD in found.parts
    _wait_loaded(chat, cleanup)
    for runner in (chat, cleanup):
        assert BUILD in _program_of(runner)
        assert _values(runner.lauf()) == before[runner]


def test_going_back_to_a_lower_build_restarts_on_it(world, monkeypatch):
    """The way back from an update: the build that starts is the lower one,
    so the higher one must stand aside by more than its number."""
    # The pinned build is laid out by the fixture; the newer one runs.
    _lay_build(world.data, NEWER, _script())
    chat = world.make("chat")
    chat.starten("small.gguf")
    _wait_loaded(chat)
    assert NEWER in _program_of(chat)

    download = Serverdownload(world.data, Restart([Member("chat", chat)]))
    _fetch(world, monkeypatch, download, BUILD, _script())
    _wait_done(download)

    stand = download.stand()
    assert stand is not None and stand.fertig and stand.fehler is None
    assert chat.bereit() and BUILD in _program_of(chat)
    assert not (world.data / "llama.cpp" / NEWER).exists()


def test_with_no_server_running_the_old_build_goes_at_once(world, monkeypatch):
    chat = world.make("chat")
    download = Serverdownload(world.data, Restart([Member("chat", chat)]))
    _fetch(world, monkeypatch, download, NEWER, _script())
    _wait_done(download)
    stand = download.stand()
    assert stand is not None and stand.fertig and stand.fehler is None
    assert not chat.laeuft() and chat.protokoll() == []
    assert not (world.data / "llama.cpp" / BUILD).exists()


# --- The sequence itself, on stand-ins for the runners ---------------------


class _Runner:
    """What ``Restart`` asks of a runner."""

    def __init__(self, lauf=None, fail: bool = False, dies: bool = False):
        self._lauf = lauf
        self.fail = fail
        self.dies = dies
        self.starts: list[dict] = []
        self.stops = 0
        self._ready = False
        self._alive = lauf is not None

    def lauf(self):
        return self._lauf if self._alive else None

    def laeuft(self) -> bool:
        return self._alive

    def bereit(self) -> bool:
        return self._alive and self._ready

    def stoppen(self) -> bool:
        self.stops += 1
        was = self._alive
        self._alive = False
        self._ready = False
        return was

    def starten(self, modell, **werte):
        if self.fail:
            raise RunnerFehler("kein_programm")
        self.starts.append({"modell": modell, **werte})
        self._alive = not self.dies
        self._ready = not self.dies
        return self._lauf


def _lauf(**more):
    return modellrunner.Lauf(
        modell="m.gguf", kontext=4096, schichten=None, port=9000, drafter="", vision=None, **more
    )


def test_a_second_stop_ends_the_same_servers_and_remembers_nothing_new():
    first, second = _Runner(_lauf()), _Runner()
    restart = Restart([Member("a", first), Member("b", second)])
    restart.stop()
    assert first.stops == 1 and second.stops == 0
    restart.stop()
    assert first.stops == 2 and second.stops == 0
    assert restart.start()
    assert len(first.starts) == 1 and second.starts == []


def test_a_server_is_started_with_every_value_it_ran_with():
    lauf = _lauf(faeden=3, sampling={"temperature": 0.1})
    runner = _Runner(lauf)
    restart = Restart([Member("a", runner)])
    restart.stop()
    assert restart.start()
    assert runner.starts == [
        {
            "modell": "m.gguf", "kontext": 4096, "schichten": None, "port": 9000,
            "drafter": "", "vision": None, "fein": None, "faeden": 3,
            "sampling": {"temperature": 0.1},
        }
    ]


def test_a_server_that_cannot_start_fails_the_restart_and_announces_nothing():
    said = []
    ok, bad = _Runner(_lauf()), _Runner(_lauf(), fail=True)
    restart = Restart([Member("ok", ok, said.append), Member("bad", bad, said.append)])
    restart.stop()
    assert restart.start() is False
    assert said == []


def test_a_server_that_ends_while_loading_fails_the_restart():
    runner = _Runner(_lauf(), dies=True)
    restart = Restart([Member("a", runner)])
    restart.stop()
    assert restart.start() is False


def test_every_server_that_came_up_is_announced_once():
    said = []
    one, two = _Runner(_lauf()), _Runner(_lauf())
    restart = Restart([Member("one", one, said.append), Member("two", two)])
    restart.stop()
    assert restart.start() is True
    assert len(said) == 1


def test_a_failing_announcement_does_not_undo_the_restart():
    def boom(lauf):
        raise RuntimeError("unreachable")

    restart = Restart([Member("a", _Runner(_lauf()), boom)])
    restart.stop()
    assert restart.start() is True


def test_the_five_servers_of_the_service_are_the_members():
    loop = asyncio.new_event_loop()
    thread = threading.Thread(target=loop.run_forever, daemon=True)
    thread.start()
    try:
        registered = []

        async def anmelden(endpoint):
            registered.append(endpoint.base_url)

        state = SimpleNamespace(
            modellrunner=_Runner(), agentenrunner=_Runner(), einbettungsrunner=_Runner(),
            sprachrunner=_Runner(), sprachputzrunner=_Runner(),
            discovery=SimpleNamespace(anmelden=anmelden),
        )
        members = server_restart.members_of(SimpleNamespace(state=state), loop)
        assert [m.name for m in members] == [
            "model server", "agent model server", "embedding server", "speech server",
            "clean-up server",
        ]
        # Only the two that join the model list announce themselves.
        assert [m.announce is not None for m in members] == [True, True, False, False, False]
        members[0].announce(_lauf())
        members[1].announce(_lauf())
        assert registered == ["http://127.0.0.1:9000/v1", "http://127.0.0.1:9000/v1"]
    finally:
        loop.call_soon_threadsafe(loop.stop)
        thread.join(timeout=5)
        loop.close()
