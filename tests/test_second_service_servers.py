"""A second service on one data folder uses the servers of the first and starts
and ends none of them.

The model servers keep a note of their process id in a folder under the data
folder, and every server has a port of its own that is the same for two
services. A second service that cleaned those notes up at its start ended the
first one's servers, and one that started a server took its port. While another
service holds the folder, every runner now refuses a start (``server_geteilt``)
and leaves the notes and the processes they name alone; the question is asked
again at every start, because the other service may be gone by then.

The notes of the five servers are written by hand here, naming a process that
stays, so nothing is ended for real: whether a note is still there afterwards
says whether the clean-up ran.
"""

from __future__ import annotations

import http.server
import json
import logging
import os
import socket
import subprocess
import sys
import threading
from contextlib import contextmanager
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import agentenserver, einbettungsserver, modellrunner, sprachserver
from app.main import app_erstellen
from app.modellrunner import Modellrunner, RunnerFehler
from app.speicherorte import ort
from tests.conftest import fake_server
from tests.test_dienst_je_instanz import notiz_legen

_SLEEPER = [sys.executable, "-c", "import time; time.sleep(60)"]


@pytest.fixture
def ordner(tmp_path):
    (tmp_path / "klein.gguf").write_bytes(b"x" * 2000)
    return tmp_path


@pytest.fixture
def falsches_programm(tmp_path):
    return fake_server(tmp_path / "llama-server")


def _with_other_service(port: int | None = 4242):
    return lambda: port


# --- The runner ------------------------------------------------------------


def test_a_start_is_refused_while_another_service_holds_the_folder(ordner, falsches_programm, monkeypatch):
    started = []
    monkeypatch.setattr(modellrunner.subprocess, "Popen", lambda *a, **k: started.append(a))
    runner = Modellrunner(ordner, str(falsches_programm), shared_with=_with_other_service())
    with pytest.raises(RunnerFehler) as refusal:
        runner.starten("klein.gguf")
    assert refusal.value.grund == "server_geteilt"
    assert not runner.laeuft()
    assert started == []
    # Nothing was written either: a note of this runner would be the other
    # service's to read.
    assert not (ordner / modellrunner.PID_DATEI).exists()


def test_the_question_is_asked_again_at_every_start(ordner, falsches_programm):
    answers = [4242, None]
    runner = Modellrunner(ordner, str(falsches_programm), shared_with=lambda: answers.pop(0))
    with pytest.raises(RunnerFehler):
        runner.starten("klein.gguf")
    # The other service has gone since: the second press starts.
    runner.starten("klein.gguf")
    try:
        assert runner.laeuft()
    finally:
        runner.stoppen()


def test_a_clean_up_leaves_the_note_and_the_process_of_the_other_service_alone(ordner):
    sleeper = subprocess.Popen(_SLEEPER, start_new_session=True)
    note = ordner / modellrunner.PID_DATEI
    note.write_text(json.dumps({"pid": sleeper.pid}))
    asked = []
    runner = Modellrunner(ordner, shared_with=_with_other_service())
    try:
        assert runner.aufraeumen(ist_unserer=lambda pid: asked.append(pid) or True) is False
        assert asked == []
        assert note.exists()
        assert sleeper.poll() is None
    finally:
        sleeper.kill()
        sleeper.wait(timeout=5)


def test_alone_on_the_folder_the_clean_up_ends_the_orphan_as_before(ordner):
    """Silence probe: no other service, or none asked for — the same as ever."""
    for runner in (Modellrunner(ordner), Modellrunner(ordner, shared_with=lambda: None)):
        sleeper = subprocess.Popen(_SLEEPER, start_new_session=True)
        (ordner / modellrunner.PID_DATEI).write_text(json.dumps({"pid": sleeper.pid}))
        try:
            assert runner.aufraeumen(ist_unserer=lambda pid: True) is True
            sleeper.wait(timeout=5)
            assert not (ordner / modellrunner.PID_DATEI).exists()
        finally:
            if sleeper.poll() is None:
                sleeper.kill()
                sleeper.wait(timeout=5)


def test_the_builders_pass_the_question_on_to_every_runner(ordner):
    asked = _with_other_service()
    runners = [
        einbettungsserver.runner_bauen(ordner, None, 8083, asked),
        sprachserver.runner_bauen(ordner, None, 8084, asked),
        sprachserver.putzrunner_bauen(ordner, None, 8085, asked),
        agentenserver.runner_bauen(ordner, None, shared_with=asked),
    ]
    for runner in runners:
        assert runner.shared_with is asked
        with pytest.raises(RunnerFehler) as refusal:
            runner.starten("klein.gguf")
        assert refusal.value.grund == "server_geteilt"


# --- The service -----------------------------------------------------------


def _all_notes(config) -> dict[str, object]:
    """The note file of each of the five servers, in the folder its runner
    reads: the model server, the embedding server, the speech server and the
    clean-up model, and the agent slot."""
    models = ort(config, "models")
    speech = ort(config, "speech_models")
    embedding = ort(config, "embedding_models")
    return {
        "model server": models / modellrunner.PID_DATEI,
        "embedding server": embedding / einbettungsserver.PID_DATEI,
        "speech server": speech / sprachserver.PID_DATEI,
        "clean-up model": speech / sprachserver.PUTZ_PID_DATEI,
        "agent slot": models / agentenserver.PID_DATEI,
    }


@contextmanager
def _notes_with_process(config):
    sleeper = subprocess.Popen(_SLEEPER, start_new_session=True)
    notes = _all_notes(config)
    for note in notes.values():
        note.parent.mkdir(parents=True, exist_ok=True)
        note.write_text(json.dumps({"pid": sleeper.pid}))
    try:
        yield notes, sleeper
    finally:
        sleeper.kill()
        sleeper.wait(timeout=5)


class _Zeilen(logging.Handler):
    """The lines of one logger, kept: the service sets up its own logging
    when it is built, which takes the handler of ``caplog`` away."""

    def __init__(self) -> None:
        super().__init__(logging.INFO)
        self.lines: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.lines.append(record.getMessage())


@contextmanager
def _lines_of(name: str):
    handler = _Zeilen()
    logger = logging.getLogger(name)
    logger.addHandler(handler)
    try:
        yield handler.lines
    finally:
        logger.removeHandler(handler)


@contextmanager
def _other_service(config):
    """Another service on this data folder: a note whose writer lives and a
    port that answers."""
    with socket.socket() as fremder:
        fremder.bind(("127.0.0.1", 0))
        fremder.listen()
        port = fremder.getsockname()[1]
        notiz_legen(config, pid=os.getppid(), port=port)
        yield port


START_ROUTES = [
    ("/api/v1/runner/start", {"modell": "klein.gguf"}),
    ("/api/v1/einbettungsserver/start", {"modell": "klein.gguf"}),
    ("/api/v1/sprachserver/start", {"modell": "klein.gguf"}),
    ("/api/v1/bereinigungsserver/start", {"modell": "klein.gguf"}),
    ("/api/v1/agentenmodell/start", {"modell": "klein.gguf"}),
]


def test_a_service_beside_another_keeps_the_notes_and_every_start_route_refuses(config):
    with _notes_with_process(config) as (notes, sleeper), _other_service(config) as port:
        app = app_erstellen(config)
        with _lines_of("app.main") as zeilen:
            with TestClient(app) as client:
                client.headers["X-Sitzungsschluessel"] = app.state.sitzungsschluessel
                # No clean-up of the five servers ran: every note is still there.
                for name, note in notes.items():
                    assert note.exists(), name
                assert sleeper.poll() is None
                # The slot was not started with the program either.
                assert not app.state.agentenrunner.laeuft()
                for url, body in START_ROUTES:
                    answer = client.post(url, json=body)
                    assert answer.status_code == 409, (url, answer.text)
                    assert "Exe-AI-Dienst" in answer.json()["detail"], url
                assert not app.state.modellrunner.laeuft()
        lines = [line for line in zeilen if "starts no model server" in line]
        assert len(lines) == 1 and f"(port {port})" in lines[0], zeilen
        # Leaving the service ended nothing of the other one's.
        assert sleeper.poll() is None
        for name, note in notes.items():
            assert note.exists(), name


def test_alone_on_the_folder_the_service_cleans_up_and_the_start_routes_work_as_before(config):
    """Silence probe: every note is taken for an orphan's and goes; a start
    reaches the file check (404: the file is not in the folder) and not the
    refusal."""
    with _notes_with_process(config) as (notes, sleeper):
        app = app_erstellen(config)
        with _lines_of("app.main") as zeilen:
            with TestClient(app) as client:
                client.headers["X-Sitzungsschluessel"] = app.state.sitzungsschluessel
                for name, note in notes.items():
                    assert not note.exists(), name
                for url, body in START_ROUTES:
                    answer = client.post(url, json=body)
                    assert answer.status_code != 409, (url, answer.text)
        assert not [line for line in zeilen if "starts no model server" in line], zeilen


def test_the_other_service_gone_the_next_start_is_no_longer_refused(config, monkeypatch):
    # Some model server must be found for the start to get as far as the
    # model: a machine without one would answer that nothing is installed.
    monkeypatch.setattr(modellrunner, "programm_finden", lambda vorgabe=None: Path(sys.executable))
    fremder = socket.socket()
    fremder.bind(("127.0.0.1", 0))
    fremder.listen()
    notiz_legen(config, pid=os.getppid(), port=fremder.getsockname()[1])
    app = app_erstellen(config)
    try:
        with TestClient(app) as client:
            client.headers["X-Sitzungsschluessel"] = app.state.sitzungsschluessel
            assert client.post("/api/v1/runner/start", json={"modell": "klein.gguf"}).status_code == 409
            # The other service ends: its port is silent from here on, and the
            # next press asks again.
            fremder.close()
            answer = client.post("/api/v1/runner/start", json={"modell": "klein.gguf"})
            assert answer.status_code == 404, answer.text
    finally:
        fremder.close()


# --- What the windows show ------------------------------------------------


class _Health:
    """A server of the other service, as far as a second one can see it: the
    one route ``llama-server`` leaves open, ``/health``, with the answer of the
    moment (200 loaded, 503 loading)."""

    def __init__(self, code: int = 200) -> None:
        self.code = code
        outer = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802 - the name the handler class asks for
                if self.path != "/health":
                    self.send_response(401)
                    self.end_headers()
                    return
                self.send_response(outer.code)
                self.end_headers()
                self.wfile.write(b'{"status": "ok"}')

            def log_message(self, *args):
                pass

        self._server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
        self.port = self._server.server_address[1]
        threading.Thread(target=self._server.serve_forever, daemon=True).start()

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()


def _write_note(runner, port: int, **facts) -> None:
    (runner.ordner / runner._pid_datei).write_text(
        json.dumps({"pid": os.getpid(), "port": port, **facts}), encoding="utf-8"
    )


def test_a_server_of_the_other_service_is_shown_as_it_answers(ordner, falsches_programm):
    gesund = _Health(200)
    try:
        runner = Modellrunner(ordner, str(falsches_programm), port=gesund.port, shared_with=_with_other_service())
        _write_note(runner, gesund.port, modell="klein.gguf", kontext=4096, schichten=99)
        lauf = runner.shown_run()
        assert (lauf.modell, lauf.kontext, lauf.schichten, lauf.port) == ("klein.gguf", 4096, 99, gesund.port)
        # Loading is running too: the server holds its port and a model comes.
        gesund.code = 503
        assert runner.shown_run().port == gesund.port
        # A note that names another port is another server's: the model is not read off it.
        _write_note(runner, gesund.port + 1, modell="klein.gguf")
        assert runner.shown_run().modell == ""
        # No note at all: running, the model unknown.
        (ordner / modellrunner.PID_DATEI).unlink()
        assert runner.shown_run().modell == ""
    finally:
        gesund.close()
    # Nothing answers any more: off.
    assert runner.shown_run() is None


def test_the_port_asked_is_the_one_the_window_would_show(ordner, falsches_programm):
    gesund = _Health(200)
    try:
        runner = Modellrunner(ordner, str(falsches_programm), port=1, shared_with=_with_other_service())
        assert runner.shown_run() is None
        assert runner.shown_run(gesund.port).port == gesund.port
    finally:
        gesund.close()


def test_alone_on_the_folder_the_window_shows_only_the_own_server(ordner, falsches_programm):
    """Silence probe: a server answering on the port is nobody's business
    where no other service is on the folder."""
    gesund = _Health(200)
    try:
        for runner in (
            Modellrunner(ordner, str(falsches_programm), port=gesund.port),
            Modellrunner(ordner, str(falsches_programm), port=gesund.port, shared_with=lambda: None),
        ):
            assert runner.shown_run() is None
            runner.refuse_stop_when_shared()
    finally:
        gesund.close()


def test_a_stop_is_refused_while_another_service_holds_the_server_and_a_server_of_its_own_stops(
    ordner, falsches_programm
):
    runner = Modellrunner(ordner, str(falsches_programm), shared_with=_with_other_service())
    with pytest.raises(RunnerFehler) as refusal:
        runner.refuse_stop_when_shared()
    assert refusal.value.grund == "server_geteilt"
    # A server this runner started before the other service came stops as ever.
    answers = [None, 4242]
    own = Modellrunner(ordner, str(falsches_programm), shared_with=lambda: answers.pop(0) if answers else 4242)
    own.starten("klein.gguf")
    try:
        own.refuse_stop_when_shared()
    finally:
        own.stoppen()


def test_every_window_beside_another_service_shows_the_server_that_service_holds_and_every_stop_refuses(config):
    pages = [
        ("/api/v1/runner", "modellrunner"),
        ("/api/v1/agentenmodell", "agentenrunner"),
        ("/api/v1/einbettungsserver", "einbettungsrunner"),
        ("/api/v1/sprachserver", "sprachrunner"),
        ("/api/v1/bereinigungsserver", "sprachputzrunner"),
    ]
    servers = {name: _Health(200) for _, name in pages}
    sleeper = subprocess.Popen(_SLEEPER, start_new_session=True)
    try:
        with _other_service(config):
            app = app_erstellen(config)
            with TestClient(app) as client:
                client.headers["X-Sitzungsschluessel"] = app.state.sitzungsschluessel
                for _, name in pages:
                    getattr(app.state, name)._port = servers[name].port
                for url, name in pages:
                    page = client.get(url).json()
                    assert page["laeuft"] is True, url
                    assert page["port"] == servers[name].port, url
                    stop = client.post(url + "/stop")
                    assert stop.status_code == 409, (url, stop.text)
                    assert "Exe-AI-Dienst" in stop.json()["detail"], url
                assert sleeper.poll() is None
                # The server of the first service ends: the next reading says off.
                for server in servers.values():
                    server.close()
                for url, _ in pages:
                    assert client.get(url).json()["laeuft"] is False, url
    finally:
        sleeper.kill()
        sleeper.wait(timeout=5)
        for server in servers.values():
            try:
                server.close()
            except OSError:
                pass


def test_alone_on_the_folder_the_windows_and_the_stops_are_as_they_were(config):
    pages = ["/api/v1/runner", "/api/v1/agentenmodell", "/api/v1/einbettungsserver",
             "/api/v1/sprachserver", "/api/v1/bereinigungsserver"]
    app = app_erstellen(config)
    with TestClient(app) as client:
        client.headers["X-Sitzungsschluessel"] = app.state.sitzungsschluessel
        for url in pages:
            assert client.get(url).json()["laeuft"] is False, url
            assert client.post(url + "/stop").status_code == 200, url
