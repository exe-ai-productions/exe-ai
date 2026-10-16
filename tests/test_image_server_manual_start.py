"""The server's start by hand carries the start values a picture of the same
model asks for.

A server started by hand with the random source ``cuda``, no VAE format and
no prediction type is another server than the one a picture of the model
asks for (the family starts with ``--rng cpu --vae-format flux``, the model
may carry a prediction of its own): the first picture drew after a second
load of the model. Both read the values from one place
(``app/image_start_values.py``), and what the server compares is what it was
started with.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import image_start_values
from app.api.v1 import bild
from app.bildrunner import Bildrunner
from app.config import Config

MODEL = "pid-model.safetensors"
# What a picture asks the running server about, and what the server was
# started with: the values the two have to agree on.
COMPARED = (
    "rng", "weight_type", "vae_format", "prediction", "extra_start",
    "threads", "vram_limit", "offload_to_cpu", "split_mode", "backend",
)


@pytest.fixture
def server(config: Config, client: TestClient, monkeypatch, tmp_path: Path):
    folder = tmp_path / "bildmodelle"
    folder.mkdir(parents=True)
    (folder / MODEL).write_bytes(b"x")
    # The header of a file of bytes names no family; the model is a PiD one,
    # whose family starts with its own random source and VAE format.
    monkeypatch.setattr(bild.bildinhalt, "family", lambda path: "pid")
    monkeypatch.setattr(Bildrunner, "programm", property(lambda self: Path("/fake/sd-cli")))

    turbo = client.app.state.bildturbo
    state: dict = {"started": None, "asked": None}

    def _start(*args, **kwargs):
        state["started"] = kwargs

    def _asked(*args, **kwargs):
        state["asked"] = kwargs
        return True

    monkeypatch.setattr(turbo, "starten", _start)
    monkeypatch.setattr(turbo, "laeuft", lambda: True)
    monkeypatch.setattr(turbo, "passt_zu", _asked)
    monkeypatch.setattr(turbo, "zeichnen", lambda body, **k: b"PNG")
    monkeypatch.setattr(turbo, "belegt_gb", lambda: None)
    return state


def _hand_start_and_picture(client: TestClient, server: dict, **wish) -> tuple[dict, dict]:
    started = client.post("/api/v1/bild/turbo/start", json={"modell": MODEL})
    assert started.status_code == 200, started.text
    presets = client.get("/api/v1/bild/vorgaben", params={"modell": MODEL}).json()
    # The window's own start values, as it takes them from the answer.
    body = {
        "prompt": "x", "modell": MODEL, "rng": presets["rng"], "vae_format": presets["vae_format"],
        "switches": presets["switches"], "prediction": presets["prediction"], **wish,
    }
    answer = client.post("/api/v1/bild", json=body)
    assert answer.status_code == 201, answer.text
    assert server["started"] is not None and server["asked"] is not None
    return server["started"], server["asked"]


def test_the_values_of_the_family_reach_the_start_by_hand(client: TestClient, server):
    started, asked = _hand_start_and_picture(client, server)
    assert started["rng"] == "cpu"
    assert started["vae_format"] == "flux"
    for name in COMPARED:
        assert started[name] == asked[name], name


def test_the_prediction_of_the_model_reaches_the_start_by_hand(client: TestClient, server):
    client.patch(
        "/api/v1/settings/global/bildmodellwerte", json={"wert": {MODEL: {"prediction": "flux_flow"}}},
    )
    started, asked = _hand_start_and_picture(client, server)
    assert started["prediction"] == "flux_flow"
    for name in COMPARED:
        assert started[name] == asked[name], name


def test_the_start_values_are_read_by_the_validators_of_the_draw_route(client: TestClient):
    values = image_start_values.lesen(client.app.state.repositories, "pid", MODEL)
    assert (values.rng, values.vae_format, values.weight_type, values.prediction) == (
        "cpu", "flux", "", "",
    )


def test_a_model_without_a_family_starts_with_the_programs_own(client: TestClient):
    values = image_start_values.lesen(client.app.state.repositories, "", "plain.safetensors")
    assert (values.rng, values.vae_format, values.weight_type, values.prediction) == (
        "cuda", "", "", "",
    )
    assert values.switches == {}
