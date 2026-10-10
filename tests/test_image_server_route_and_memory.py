"""Which painter draws a picture while the picture server runs, and what the
memory check counts.

The picture server draws everything its own route carries; a picture that
needs something only sd-cli can do goes to sd-cli, with nothing greyed out
and nothing said. The memory check counts what the server holds and every
file of the picture; when an sd-cli picture does not fit beside the server
but fits without it, the server steps aside for that picture and comes back
on the same model.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import bildrunner, bildspeicher, systemspeicher
from app.api.v1 import bild as bildapi
from app.bildrunner import Auftrag, Bildrunner
from app.config import Config
from app.speicherorte import ort

GIB = 1024**3
# The painter's own draw, kept before any fixture stands in for it.
_DRAW = Bildrunner.erzeugen


@dataclass
class Route:
    """A running picture server (stood in for), a painter that records, and
    a sender. ``sequence`` holds which painter drew, and in what order the
    server was paused and resumed around it."""

    client: TestClient
    running: bool = True
    server_gb: float | None = None
    sequence: list[str] = field(default_factory=list)
    body: dict | None = None

    def send(self, status: int = 201, **fields) -> list[str]:
        body = {"prompt": "x", "modell": "base.safetensors", **fields}
        answer = self.client.post("/api/v1/bild", json=body)
        assert answer.status_code == status, answer.text
        return self.sequence


@pytest.fixture
def route(config: Config, client: TestClient, monkeypatch, tmp_path: Path) -> Route:
    config.app.bildmodelle_verzeichnis = str(tmp_path / "bildmodelle")
    image_dir = tmp_path / "bildmodelle"
    image_dir.mkdir(parents=True)
    (image_dir / "base.safetensors").write_bytes(b"x")
    state = Route(client)

    monkeypatch.setattr(Bildrunner, "programm", property(lambda self: Path("/fake/sd-cli")))

    def _draw_cli(self, job, target, **k):
        state.sequence.append("sd-cli")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"PNG")
        return target

    monkeypatch.setattr(Bildrunner, "erzeugen", _draw_cli)

    server = client.app.state.bildturbo

    def _draw_server(body, **k):
        state.sequence.append("server")
        state.body = body
        return b"PNG"

    def _pause_stub():
        state.sequence.append("pause")
        return True

    monkeypatch.setattr(server, "laeuft", lambda: state.running)
    monkeypatch.setattr(server, "passt_zu", lambda *a, **k: True)
    monkeypatch.setattr(server, "belegt_gb", lambda: state.server_gb)
    monkeypatch.setattr(server, "zeichnen", _draw_server)
    monkeypatch.setattr(server, "pause", _pause_stub)
    monkeypatch.setattr(server, "resume", lambda: state.sequence.append("resume"))
    return state


def _memory(monkeypatch, *, total: float, held: float, files: float) -> None:
    monkeypatch.setattr(systemspeicher, "gesamt_gb", lambda: total)
    monkeypatch.setattr(bildspeicher, "gehaltene_gb", lambda app_state: held)
    monkeypatch.setattr(bildapi, "_kit_files_gb", lambda job: files)


# --- Who draws -------------------------------------------------------------


def test_server_draws_without_live_preview(route: Route):
    assert route.send() == ["server"]
    assert route.body is not None
    assert route.body["sample_params"]["sample_steps"] > 0


def test_sd_cli_draws_with_live_preview(route: Route, caplog):
    with caplog.at_level(logging.INFO, logger="app.api.v1.bild"):
        assert route.send(live_preview="proj") == ["sd-cli"]
    assert any("live preview" in line for line in caplog.messages)


def test_sd_cli_draws_everything_without_server(route: Route):
    route.running = False
    assert route.send() == ["sd-cli"]


def test_pulid_and_invalid_lists_go_to_sd_cli():
    """PuLID has no field in the server's body; a list that is no list of
    numbers is left to sd-cli's own message."""
    pulid_job = Auftrag(modell=Path("/m"), prompt="x",
                    pulid_weights=Path("/p"), pulid_id_embedding=Path("/e"))
    assert bildapi._cli_only_reason(pulid_job, False) == "PuLID"
    assert bildapi._cli_only_reason(Auftrag(modell=Path("/m"), prompt="x", sigmas="a,b"), False)
    assert bildapi._cli_only_reason(
        Auftrag(modell=Path("/m"), prompt="x", slg_scale=2.5, skip_layers="[7,x]"), False)


def test_no_window_value_is_dropped_on_the_server():
    """Silence probe for the switch: the values that used to be locked while
    the server ran now travel in its body, so such a picture stays on the
    server and every value arrives."""
    everything = Auftrag(
        modell=Path("/m"), prompt="x", eta=0.0, flow_shift=3.0, sigmas="14.6,7.8,0",
        extra_sample_args="base_shift=0.5", slg_scale=2.5, skip_layers="[7,8,9]",
        guidance=3.5, clip_skip=2, switches={"vae_tiling": True},
    )
    assert bildapi._cli_only_reason(everything, False) is None
    body = bildapi._turbo_auftrag(everything)
    sampler = body["sample_params"]
    assert sampler["eta"] == 0.0
    assert sampler["flow_shift"] == 3.0
    assert sampler["custom_sigmas"] == [14.6, 7.8, 0.0]
    assert sampler["extra_sample_args"] == "base_shift=0.5"
    assert sampler["guidance"]["distilled_guidance"] == 3.5
    assert sampler["guidance"]["slg"] == {
        "scale": 2.5, "layer_start": 0.01, "layer_end": 0.2, "layers": [7, 8, 9],
    }
    assert body["clip_skip"] == 2
    assert body["vae_tiling_params"] == {"enabled": True}


def test_control_image_travels_per_job(tmp_path: Path):
    guide = tmp_path / "guide.png"
    guide.write_bytes(b"LEIT")
    job = Auftrag(
        modell=Path("/m"), prompt="x", control_net=Path("/c/canny.safetensors"),
        control_image=guide, control_strength=0.7, canny=True,
    )
    body = bildapi._turbo_auftrag(job)
    assert body["control_strength"] == 0.7
    assert body["image_preprocess"] == "target=control,canny=true"
    assert "control_net" not in body


# --- Memory ----------------------------------------------------------------


def test_check_counts_every_kit_file(tmp_path: Path):
    """The diffusion model, its encoders, the VAE — not the model file
    alone. Sparse files, so the sizes cost no disk."""
    def sized_file(name: str, gib: float) -> Path:
        path = tmp_path / name
        with open(path, "wb") as f:
            f.truncate(int(gib * GIB))
        return path

    flux = sized_file("flux.gguf", 6)
    job = Auftrag(
        modell=flux, prompt="x", diffusion_model=flux, t5xxl=sized_file("t5.gguf", 5),
        clip_l=sized_file("clip_l.safetensors", 0.25), vae=sized_file("ae.safetensors", 0.25),
    )
    assert bildapi._kit_files_gb(job) == pytest.approx(11.5)


def test_server_steps_aside_for_an_sd_cli_picture_that_does_not_fit(
    route: Route, monkeypatch, caplog
):
    """8 GB held, 4 of them by the server, a 2 GB picture on 10 GB: it does
    not fit beside the server (8 + 2 + 2.5), it fits without it (4 + 2 +
    2.5). The server pauses, sd-cli draws, the server comes back — and the
    log carries the numbers."""
    _memory(monkeypatch, total=10.0, held=8.0, files=2.0)
    route.server_gb = 4.0
    with caplog.at_level(logging.INFO, logger="app.api.v1.bild"):
        assert route.send(live_preview="proj") == ["pause", "sd-cli", "resume"]
    line = next(s for s in caplog.messages if "steps aside" in s)
    assert "8.0 GB held" in line
    assert "4.0 GB of it by the image server" in line
    assert "picture files 2.0 GB" in line


def test_server_stays_when_memory_is_enough(route: Route, monkeypatch):
    """Silence probe: when the picture fits beside the server, nothing
    pauses."""
    _memory(monkeypatch, total=64.0, held=8.0, files=2.0)
    route.server_gb = 4.0
    assert route.send(live_preview="proj") == ["sd-cli"]


def test_refusal_stays_when_it_does_not_fit_without_server(route: Route, monkeypatch):
    _memory(monkeypatch, total=10.0, held=8.0, files=6.0)
    route.server_gb = 4.0
    assert route.send(status=507, live_preview="proj") == []


def test_picture_on_loaded_server_needs_no_new_room(
    route: Route, monkeypatch, client: TestClient
):
    """The running server already holds this picture's files; counting them
    again beside the server would refuse a picture that needs nothing new."""
    client.app.state.bildturbo._weights_loaded = True
    _memory(monkeypatch, total=10.0, held=9.0, files=6.0)
    route.server_gb = 6.0
    assert route.send() == ["server"]


def test_a_matching_server_that_has_not_drawn_is_checked(
    route: Route, monkeypatch, client: TestClient
):
    """Started by hand or brought back after a pause, the server holds only
    its graph until the first picture reads the weights — so that picture's
    files are counted like any other."""
    client.app.state.bildturbo._weights_loaded = False
    _memory(monkeypatch, total=10.0, held=9.0, files=6.0)
    route.server_gb = 0.1
    assert route.send(status=507) == []


def test_restart_on_other_model_frees_the_old_room(
    route: Route, monkeypatch, client: TestClient
):
    """A picture that restarts the server frees what the server holds now:
    9 GB held, 6 by the server, a 4 GB picture on 12 GB fits (3 + 4 + 2.5)."""
    server = client.app.state.bildturbo
    monkeypatch.setattr(server, "passt_zu", lambda *a, **k: False)
    monkeypatch.setattr(server, "starten", lambda *a, **k: None)
    monkeypatch.setattr(server, "bereit_abwarten", lambda frist, stopped=None: True)
    _memory(monkeypatch, total=12.0, held=9.0, files=4.0)
    route.server_gb = 6.0
    assert route.send() == ["server"]


# --- A stop before the picture draws -------------------------------------------


def test_a_stop_while_the_server_restarts_ends_the_picture(
    route: Route, monkeypatch, client: TestClient, config: Config,
):
    """A picture on another model: the server restarts for it, and the stop
    comes while it still starts. The stop answers yes, the picture is never
    drawn, no file appears — and the server is left to start."""
    server = client.app.state.bildturbo
    stopped: list[bool] = []
    answers: list[bool] = []

    def wait(frist, stopped=None):
        route.sequence.append("wait")
        answers.append(client.post("/api/v1/bild/stop").json())
        return not stopped()

    monkeypatch.setattr(server, "passt_zu", lambda *a, **k: False)
    monkeypatch.setattr(server, "starten", lambda *a, **k: route.sequence.append("start"))
    monkeypatch.setattr(server, "bereit_abwarten", wait)
    monkeypatch.setattr(server, "stoppen", lambda: stopped.append(True))
    _memory(monkeypatch, total=64.0, held=8.0, files=2.0)
    route.server_gb = 4.0

    assert route.send(status=499) == ["start", "wait"]
    assert answers == [True]
    assert stopped == []
    assert not client.app.state.bildrunner.laeuft()
    pictures = ort(config, "images")
    assert not pictures.exists() or list(pictures.iterdir()) == []
    # The next picture is not stopped by what was asked for the last one.
    monkeypatch.setattr(server, "bereit_abwarten", lambda frist, stopped=None: True)
    route.sequence.clear()
    assert route.send() == ["start", "server"]


def test_a_stop_answered_yes_never_hands_the_finished_picture_back(
    route: Route, monkeypatch, client: TestClient, config: Config,
):
    """The stop falls where neither side draws any more and the picture is
    on its way back: it was answered yes, so the picture is not handed
    back. (After that last look a stop is answered no: the runner's own
    test.)"""
    server = client.app.state.bildturbo
    answers: list[bool] = []

    def draw(body, **k):
        route.sequence.append("server")
        answers.append(client.post("/api/v1/bild/stop").json())
        return b"PNG"

    monkeypatch.setattr(server, "zeichnen", draw)
    assert route.send(status=499) == ["server"]
    assert answers == [True]
    pictures = ort(config, "images")
    assert not pictures.exists() or list(pictures.iterdir()) == []


def test_a_stop_while_the_server_steps_aside_never_starts_sd_cli(
    route: Route, monkeypatch, client: TestClient,
):
    """The server pauses for an sd-cli picture and the stop comes during the
    pause: sd-cli is not started, and the server comes back as after every
    such picture."""
    server = client.app.state.bildturbo
    answers: list[bool] = []
    started: list = []

    def pause():
        route.sequence.append("pause")
        answers.append(client.post("/api/v1/bild/stop").json())
        return True

    monkeypatch.setattr(server, "pause", pause)
    # The painter itself, so its own look for a stop is what is tested.
    monkeypatch.setattr(Bildrunner, "erzeugen", _DRAW)
    monkeypatch.setattr(bildrunner.subprocess, "Popen", lambda *a, **k: started.append(a))
    _memory(monkeypatch, total=10.0, held=8.0, files=2.0)
    route.server_gb = 4.0

    assert route.send(status=499, live_preview="proj") == ["pause", "resume"]
    assert answers == [True]
    assert started == []
    assert not client.app.state.bildrunner.laeuft()


def test_a_stop_without_a_picture_that_waits_answers_no(client: TestClient, monkeypatch):
    """Silence probe: nothing draws and nothing waits to draw — the stop
    answers no and leaves a warm server alone. A hold of the lock that is no
    waiting picture answers no as well."""
    server = client.app.state.bildturbo
    stopped: list[bool] = []
    monkeypatch.setattr(server, "stoppen", lambda: stopped.append(True))
    assert client.post("/api/v1/bild/stop").json() is False
    runner = client.app.state.bildrunner
    runner.reservieren()
    try:
        assert client.post("/api/v1/bild/stop").json() is False
    finally:
        runner.freigeben()
    assert stopped == []


def test_hand_stop_never_acts_under_a_picture(client: TestClient, monkeypatch):
    """While a picture holds the one-picture lock — drawn on the server, or
    drawn by sd-cli while the server stepped aside — the tile's stop answers
    409 and touches nothing (the start: the next test)."""
    server = client.app.state.bildturbo
    stopped: list[bool] = []
    monkeypatch.setattr(server, "stoppen", lambda: stopped.append(True))
    runner = client.app.state.bildrunner
    runner.reservieren()
    try:
        assert client.post("/api/v1/bild/turbo/stop").status_code == 409
    finally:
        runner.freigeben()
    assert stopped == []
    assert client.post("/api/v1/bild/turbo/stop").status_code == 200
    assert stopped == [True]


def test_hand_start_waits_for_a_picture(route: Route, client: TestClient, monkeypatch):
    server = client.app.state.bildturbo
    started: list[bool] = []
    monkeypatch.setattr(server, "starten", lambda *a, **k: started.append(True))
    runner = client.app.state.bildrunner
    runner.reservieren()
    try:
        answer = client.post("/api/v1/bild/turbo/start", json={"modell": "base.safetensors"})
    finally:
        runner.freigeben()
    assert answer.status_code == 409
    assert started == []
    answer = client.post("/api/v1/bild/turbo/start", json={"modell": "base.safetensors"})
    assert answer.status_code == 200
    assert started == [True]


def test_a_server_that_does_not_come_back_keeps_the_picture(
    route: Route, monkeypatch, client: TestClient, caplog
):
    """The sd-cli picture is drawn; a server that cannot start again is only
    slower from then on, and the picture still reaches the chat."""
    def _resume_fails():
        route.sequence.append("resume")
        raise OSError("sd-server is gone")

    monkeypatch.setattr(client.app.state.bildturbo, "resume", _resume_fails)
    _memory(monkeypatch, total=10.0, held=8.0, files=2.0)
    route.server_gb = 4.0
    with caplog.at_level(logging.WARNING, logger="app.api.v1.bild"):
        assert route.send(live_preview="proj") == ["pause", "sd-cli", "resume"]
    assert any("could not start again" in line for line in caplog.messages)
    assert not client.app.state.bildrunner.laeuft()


def test_a_reserved_draw_leaves_the_lock_to_its_caller(tmp_path: Path, monkeypatch):
    """``erzeugen(reserved=True)`` neither takes nor releases the lock —
    the caller that reserved it does."""
    class _Reached(Exception):
        """Raised where the draw builds its command — past the lock."""

    def _command(self, job, target):
        raise _Reached

    runner = Bildrunner(tmp_path)
    monkeypatch.setattr(Bildrunner, "befehl", _command)
    runner.reservieren()
    try:
        with pytest.raises(_Reached):
            runner.erzeugen(Auftrag(modell=Path("/m"), prompt="x"), tmp_path / "a.png",
                            reserved=True)
        assert runner.laeuft()
    finally:
        runner.freigeben()
    assert not runner.laeuft()
