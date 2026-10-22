"""The live preview of a picture the picture server draws.

The server's job answers with its newest intermediate picture while it
generates. The program keeps that picture with a stamp, tells the window the
stamp through the one progress route, and hands the picture out through the
one preview route, whichever painter draws. What the server cannot do (the
noisy variant, a rhythm below 1, a tiny autoencoder for the preview alone, a
video) still goes to sd-cli.
"""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Any, cast

import pytest
from fastapi import HTTPException

from app import bildturbo
from app.api.v1 import bild as bildapi
from app.api.v1.bild import _cli_only_reason, _turbo_auftrag
from app.bildrunner import Auftrag, Bildrunner
from app.bildturbo import Bildturbo


def _job(**fields) -> Auftrag:
    return Auftrag(modell=Path("/m.safetensors"), prompt="x", schritte=30, **fields)


PNG_A = b"\x89PNG\r\n\x1a\nA\x00\x00\x00\x00IEND\xaeB`\x82"
PNG_B = b"\x89PNG\r\n\x1a\nB\x00\x00\x00\x00IEND\xaeB`\x82"


# --- What the body carries ---------------------------------------------------


def test_the_body_carries_the_kind_and_the_rhythm_of_the_preview():
    body = _turbo_auftrag(_job(live_preview="proj", preview_interval=2))
    assert body["preview"] == "proj"
    assert body["preview_interval"] == 2


def test_the_body_names_no_rhythm_when_none_was_chosen():
    body = _turbo_auftrag(_job(live_preview="vae"))
    assert body["preview"] == "vae"
    assert "preview_interval" not in body


def test_silence_a_picture_without_preview_has_the_body_it_had():
    body = _turbo_auftrag(_job(preview_interval=2))
    assert "preview" not in body
    assert "preview_interval" not in body


# --- Who draws -----------------------------------------------------------------


@pytest.mark.parametrize("fields", [
    {"live_preview": "proj"},
    {"live_preview": "vae"},
    {"live_preview": "proj", "preview_interval": 2},
    # The VAE is a tiny autoencoder already: it paints the preview too.
    {"live_preview": "tae", "taesd": Path("/t.safetensors"), "vae_is_tae": True},
    # A "tae" preview with none chosen has nothing to add beside the VAE.
    {"live_preview": "tae"},
    {},
])
def test_the_server_draws_these_previews(fields):
    assert _cli_only_reason(_job(**fields), False) is None


@pytest.mark.parametrize(("fields", "control", "words"), [
    ({"live_preview": "proj", "preview_noisy": True}, "bild.preview_noisy", "noisy"),
    ({"live_preview": "proj", "preview_interval": 0}, "bild.preview_interval", "rhythm"),
    ({"live_preview": "vae", "preview_interval": -3}, "bild.preview_interval", "rhythm"),
    (
        {"live_preview": "tae", "taesd": Path("/t.safetensors")},
        "bild.taesd", "tiny autoencoder",
    ),
    ({"live_preview": "proj", "video": True}, "bild.live_preview", "video"),
])
def test_sd_cli_keeps_what_the_server_cannot_do(fields, control, words):
    reason = _cli_only_reason(_job(**fields), False)
    assert reason is not None
    assert reason.control == control
    assert words in reason


# --- The preview of a running draw ------------------------------------------------


class _Alive:
    pid = 4242

    def poll(self):
        return None


class _Answer:
    status_code = 200

    def __init__(self, data: dict):
        self._data = data

    def raise_for_status(self):
        pass

    def json(self):
        return self._data


def _generating(picture: bytes | None, step: int | None = None) -> dict:
    job: dict = {"id": "job_1", "status": "generating"}
    if picture is not None:
        job["preview"] = {"b64_json": base64.b64encode(picture).decode()}
        if step is not None:
            job["preview"].update({"pass": 1, "step": step, "total_steps": 30})
    return job


def _completed() -> dict:
    image = base64.b64encode(b"PNG").decode()
    return {
        "id": "job_1", "status": "completed",
        "result": {"images": [{"index": 0, "b64_json": image}]},
    }


def _draw_over(turbo: Bildturbo, monkeypatch, jobs: list[dict]) -> list[tuple]:
    """Draws one picture against a stand-in server that answers the given
    states one after the other, and writes down what the turbo shows at every
    look: its progress stamp and its preview."""
    monkeypatch.setattr(bildturbo, "POLL_INTERVAL", 0.0)
    # Every look follows the one before at once; a clock that ticks coarsely
    # (Windows) would give two previews the same microsecond.
    clock = iter(range(1_000_000_000, 10**12, 1000))
    monkeypatch.setattr(bildturbo.time, "time_ns", lambda: next(clock))
    turbo._prozess = cast(Any, _Alive())
    turbo._war_bereit = True
    looks: list[tuple] = []
    queue = list(jobs)

    def post(url, **kwargs):
        return _Answer({"id": "job_1", "status": "queued"})

    def get(url, **kwargs):
        stand = turbo.fortschritt()
        looks.append((stand["preview"] if stand else None, turbo.preview()))
        return _Answer(queue.pop(0))

    monkeypatch.setattr(bildturbo.httpx, "post", post)
    monkeypatch.setattr(bildturbo.httpx, "get", get)
    turbo.zeichnen({"prompt": "x", "sample_params": {"sample_steps": 30}})
    return looks


def test_the_newest_preview_comes_with_a_stamp_that_moves(tmp_path: Path, monkeypatch):
    turbo = Bildturbo(tmp_path)
    looks = _draw_over(turbo, monkeypatch, [
        {"id": "job_1", "status": "queued"},
        _generating(None),
        _generating(PNG_A),
        _generating(PNG_A),
        _generating(PNG_B),
        _completed(),
    ])
    # Before the first preview: stamp 0 and no picture.
    assert looks[0] == (0, None) and looks[1] == (0, None) and looks[2] == (0, None)
    stamp_a, picture_a = looks[3]
    assert picture_a == PNG_A and stamp_a > 0
    # The same picture twice keeps its stamp: the window fetches it once.
    assert looks[4] == (stamp_a, PNG_A)
    stamp_b, picture_b = looks[5]
    assert picture_b == PNG_B and stamp_b > stamp_a


def test_a_new_step_is_a_new_preview_even_when_it_looks_the_same(tmp_path: Path, monkeypatch):
    turbo = Bildturbo(tmp_path)
    looks = _draw_over(turbo, monkeypatch, [
        _generating(PNG_A, step=2),
        _generating(PNG_A, step=2),
        _generating(PNG_A, step=4),
        _generating(PNG_A, step=4),
        _completed(),
    ])
    stamp_first = looks[1][0]
    assert looks[2][0] == stamp_first
    assert looks[3][0] > stamp_first
    assert looks[4][0] == looks[3][0]


def test_the_preview_is_empty_before_and_after_every_picture(tmp_path: Path, monkeypatch):
    turbo = Bildturbo(tmp_path)
    _draw_over(turbo, monkeypatch, [_generating(PNG_A), _generating(PNG_B), _completed()])
    assert turbo.preview() is None
    assert turbo.fortschritt() is None
    # The next picture starts with none of the last one's.
    looks = _draw_over(turbo, monkeypatch, [_generating(None), _completed()])
    assert looks[0] == (0, None)


def test_a_failed_picture_leaves_no_preview_behind(tmp_path: Path, monkeypatch):
    turbo = Bildturbo(tmp_path)
    with pytest.raises(bildturbo.BildturboFehler):
        _draw_over(turbo, monkeypatch, [
            _generating(PNG_A), {"id": "job_1", "status": "failed", "error": {"message": "x"}},
        ])
    assert turbo.preview() is None


def test_a_preview_that_does_not_decode_does_not_end_the_picture(tmp_path: Path, monkeypatch):
    turbo = Bildturbo(tmp_path)
    broken = {"id": "job_1", "status": "generating", "preview": {"b64_json": "@@@"}}
    looks = _draw_over(turbo, monkeypatch, [broken, _generating(PNG_A), _completed()])
    assert looks[2][1] == PNG_A


# --- The routes --------------------------------------------------------------------


class _Request:
    def __init__(self, runner: Bildrunner, turbo: Bildturbo):
        self.app = type("App", (), {})()
        self.app.state = type("State", (), {"bildrunner": runner, "bildturbo": turbo})()


def test_the_preview_route_hands_out_the_servers_picture_and_then_none(tmp_path: Path):
    runner, turbo = Bildrunner(tmp_path), Bildturbo(tmp_path)
    request = _Request(runner, turbo)
    turbo._prozess = cast(Any, _Alive())
    turbo._zeichnet = True
    turbo._fortschritt = {"anteil": 0.5, "schritt": 15, "gesamt": 30}
    turbo._preview = (7, PNG_A)
    assert bildapi.live_preview_picture(request, "en").body == PNG_A
    assert bildapi.bild_fortschritt(request).preview == 7
    # The draw is over: the route answers not found, the progress none.
    turbo._zeichnet = False
    turbo._preview = None
    with pytest.raises(HTTPException) as error:
        bildapi.live_preview_picture(request, "en")
    assert error.value.status_code == 404
    assert bildapi.bild_fortschritt(request).laeuft is False


def test_silence_sd_cli_keeps_its_own_preview_route(tmp_path: Path):
    runner, turbo = Bildrunner(tmp_path), Bildturbo(tmp_path)
    request = _Request(runner, turbo)
    runner.reservieren()
    try:
        runner.preview_path.write_bytes(PNG_B)
        assert bildapi.live_preview_picture(request, "en").body == PNG_B
    finally:
        runner.freigeben()
