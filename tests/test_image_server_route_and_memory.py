"""Which painter draws a picture while the picture server runs, and what the
memory check counts.

The picture server draws everything its own route carries; a picture that
needs something only sd-cli can do goes to sd-cli, with nothing greyed out.
Only one of the two draws at a time: the server steps aside for every sd-cli
picture and comes back on the same model, whatever the memory figures say.
The memory check counts what the server holds and every file of the picture,
and only asks whether the picture fits without the server. The footer names
the control that sends a picture to sd-cli — the service says which.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tests.conftest import sized_file
from app import bildrunner, bildspeicher, systemspeicher
from app.api.v1 import bild as bildapi
from app.bildrunner import Auftrag, Bildrunner
from app.config import Config
from app.i18n import t
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
    paused_for: str | None = None

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

    def _pause_stub(control=None):
        state.sequence.append("pause")
        state.paused_for = control
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
        assert route.send(live_preview="proj") == ["pause", "sd-cli", "resume"]
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
    def kit_file(name: str, gib: float) -> Path:
        return sized_file(tmp_path / name, int(gib * GIB))

    flux = kit_file("flux.gguf", 6)
    job = Auftrag(
        modell=flux, prompt="x", diffusion_model=flux, t5xxl=kit_file("t5.gguf", 5),
        clip_l=kit_file("clip_l.safetensors", 0.25), vae=kit_file("ae.safetensors", 0.25),
    )
    assert bildapi._kit_files_gb(job) == pytest.approx(11.5)


def test_server_steps_aside_for_an_sd_cli_picture_that_does_not_fit_beside_it(
    route: Route, monkeypatch, caplog
):
    """8 GB held, 4 of them by the server, a 2 GB picture on 10 GB: it does
    not fit beside the server (8 + 2 + 2.5), it fits without it (4 + 2 +
    2.5). The server pauses, sd-cli draws, the server comes back — and the
    log names the step with the time it took."""
    _memory(monkeypatch, total=10.0, held=8.0, files=2.0)
    route.server_gb = 4.0
    with caplog.at_level(logging.INFO, logger="app.api.v1.bild"):
        assert route.send(live_preview="proj") == ["pause", "sd-cli", "resume"]
    assert any("Image server steps aside for an sd-cli picture" in s for s in caplog.messages)


def test_server_steps_aside_for_every_sd_cli_picture_whatever_the_memory(
    route: Route, monkeypatch
):
    """Enough room for both: the same model still never lies in memory
    twice, so the server pauses and the control that sent the picture to
    sd-cli goes with it."""
    _memory(monkeypatch, total=64.0, held=8.0, files=2.0)
    route.server_gb = 4.0
    assert route.send(live_preview="proj") == ["pause", "sd-cli", "resume"]
    assert route.paused_for == "bild.live_preview"


def test_server_steps_aside_when_the_model_file_cannot_be_read(route: Route, monkeypatch):
    """No honest figure to add up — and still the server pauses."""
    monkeypatch.setattr(bildapi, "_kit_files_gb", lambda job: None)
    assert route.send(live_preview="proj") == ["pause", "sd-cli", "resume"]


def test_a_picture_the_server_draws_pauses_nothing(route: Route, monkeypatch):
    """Silence probe: what the server draws is drawn by it, and a picture
    drawn while no server runs has no server to pause."""
    _memory(monkeypatch, total=64.0, held=8.0, files=2.0)
    assert route.send() == ["server"]
    route.sequence.clear()
    route.running = False
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

    def pause(control=None):
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


# --- The footer names the control ------------------------------------------


def _asked(route: Route, **values) -> str | None:
    answer = route.client.post(
        "/api/v1/bild/turbo/reason", json={"modell": "base.safetensors", **values}
    )
    assert answer.status_code == 200, answer.text
    return answer.json()["control"]


@pytest.mark.parametrize(
    ("values", "control"),
    [
        ({"live_preview": "proj"}, "bild.live_preview"),
        ({"pulid_weights": "p.safetensors", "pulid_id_embedding": "e.safetensors"}, "bild.pulid"),
        ({"sigmas": "a,b"}, "bild.sigmas"),
        ({"slg_scale": 2.5, "skip_layers": "[7,x]"}, "bild.skip_layers"),
        ({"hires": True, "switches": {"hires_sigmas": "a,b"}}, "bild.sw_hires_sigmas"),
        ({"ref_video": True, "video": True}, "bild.referenzvideo"),
        ({"lora": True, "lora_apply_mode": "auto"}, "bild.lora_modus"),
    ],
)
def test_the_service_names_the_control_that_sends_a_picture_to_sd_cli(
    route: Route, values: dict, control: str
):
    assert _asked(route, **values) == control
    # Every name is a label the window can show, in both languages.
    for language in ("de", "en"):
        assert t(control, language) != control


def test_the_service_names_no_control_for_values_the_server_draws(route: Route):
    """Silence probe: the same questions with the values that stay on the
    server — and with a picture server that does not run, where every
    picture is drawn by sd-cli and there is nothing to name."""
    assert _asked(route) is None
    assert _asked(route, sigmas="14.6,7.8,0", slg_scale=2.5, skip_layers="[7,8,9]") is None
    assert _asked(route, lora=True, lora_apply_mode="at_runtime") is None
    route.running = False
    assert _asked(route, live_preview="proj") is None


def test_the_question_and_the_draw_route_decide_alike(route: Route):
    """The footer's answer and the route's choice come from one rule: a
    value the question names goes to sd-cli, and one it does not stays."""
    assert _asked(route, live_preview="proj") == "bild.live_preview"
    assert route.send(live_preview="proj") == ["pause", "sd-cli", "resume"]
    route.sequence.clear()
    assert _asked(route) is None
    assert route.send() == ["server"]


def _give_second_model(route: Route, tmp_path: Path) -> None:
    """The model's kit brings a second, high-noise diffusion model — a
    model whose family is not read has exactly the parts given to it."""
    from app import bildmodellwerte
    from app.db.repositories.einstellungen import GLOBAL

    (tmp_path / "bildmodelle" / "high.safetensors").write_bytes(b"x")
    route.client.app.state.repositories.einstellungen.zusammenlegen(
        GLOBAL, bildmodellwerte.SCHLUESSEL,
        {"base.safetensors": {
            bildmodellwerte.FAMILY_DETECTION: False,
            "high_noise_diffusion_model": "high.safetensors",
        }},
        pruefen=bildmodellwerte.pruefen,
    )


def test_the_footer_counts_the_values_of_the_second_model_as_the_draw_does(
    route: Route, tmp_path: Path
):
    """A kit with a high-noise model switches its pass's values on: a list
    there that is no list of numbers goes to sd-cli, and the footer says so
    before the picture is drawn — the same words the pause carries."""
    bad = {"high_noise_skip_layers": "[7,x]"}
    # Without the second model the values of its pass are not in play.
    assert _asked(route, video=True, switches=bad) is None
    assert route.send(video=True, switches=bad) == ["server"]
    route.sequence.clear()

    _give_second_model(route, tmp_path)
    assert _asked(route, video=True, switches=bad) == "bild.sw_high_noise_skip_layers"
    assert route.send(video=True, switches=bad) == ["pause", "sd-cli", "resume"]
    assert route.paused_for == "bild.sw_high_noise_skip_layers"
    # Silence probe: a list of numbers there stays on the server, with the
    # second model as without it.
    route.sequence.clear()
    good = {"high_noise_skip_layers": "[7,8,9]"}
    assert _asked(route, video=True, switches=good) is None
    assert route.send(video=True, switches=good) == ["server"]


def test_the_footer_reads_the_kit_only_for_a_value_of_the_second_models_pass(
    route: Route, monkeypatch
):
    """The window asks every few seconds; the kit decides nothing unless a
    value of the high-noise pass is among the studio's."""
    def never(*a, **k):
        raise AssertionError("the kit was read for a question it cannot change")

    monkeypatch.setattr(bildapi, "_kit_has_high_noise", never)
    assert _asked(route) is None
    assert _asked(route, video=True, switches={"eta": 0.5}) is None
    assert _asked(route, live_preview="proj") == "bild.live_preview"


def test_the_state_names_what_the_server_is_paused_for(route: Route, client: TestClient):
    """Between the pause and the start again the process is gone; the state
    still says what it waits for — and says nothing when it was stopped."""
    server = client.app.state.bildturbo
    assert client.get("/api/v1/bild/turbo").json()["paused_for"] is None
    server._start_values = ((), {})
    server._paused_for = "bild.live_preview"
    assert client.get("/api/v1/bild/turbo").json()["paused_for"] == "bild.live_preview"
    server._start_values = None
    assert client.get("/api/v1/bild/turbo").json()["paused_for"] is None


def test_every_control_a_reason_can_name_is_a_label_in_both_languages():
    """The footer shows the label under the key the service names: a key
    that is not in the catalogue would show as a bare key."""
    from app import image_switches

    keys = {
        "bild.nur_hochskalieren", "bild.nur_adetailer", "bild.referenzvideo",
        "bild.live_preview", "bild.pulid", "bild.sigmas", "bild.skip_layers",
        "bild.lora_modus", "bildserver.wichtigkeitsmatrix",
        *(f"bild.sw_{key}" for key in (
            "vae_tile_size", "vae_relative_tile_size", "hires_sigmas",
            "high_noise_skip_layers", "audio", "ref_audio", "ref_video_audio",
        )),
    }
    for key in keys:
        for language in ("de", "en"):
            assert t(key, language) != key, (key, language)
    # And every switch the rule can name is one the table knows.
    for key in ("vae_tile_size", "vae_relative_tile_size", "hires_sigmas",
                "high_noise_skip_layers", "audio", "ref_audio", "ref_video_audio"):
        assert image_switches.get(key) is not None


def test_a_server_that_does_not_come_back_is_off_not_paused(client: TestClient, monkeypatch):
    """The pause ends when the server is asked to come back — even when it
    cannot: the footer must not keep saying 'pauses for' over a server
    that stays down."""
    server = client.app.state.bildturbo
    server._start_values = ((), {})
    server._paused_for = "bild.live_preview"
    assert server.paused_for() == "bild.live_preview"
    monkeypatch.setattr(server, "starten", lambda *a, **k: False)
    assert server.resume() is False
    assert server.paused_for() is None
