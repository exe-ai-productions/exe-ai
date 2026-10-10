"""The picture route, the per-chat store and the drawing tool take what
sd.cpp takes: no upper limit on steps, CFG, pictures per run, prompt length
or LoRAs; edges from 64 to 4096, rounded up onto the grid of 64 the way
sd.cpp rounds them; at least one step, as sd-cli refuses fewer
(app/bildwahlen.py)."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import bildfensterwahl, bildrunner
from app.bildrunner import Bildrunner
from app.config import Config


@pytest.fixture
def senden(config: Config, client: TestClient, monkeypatch, tmp_path: Path):
    """POST /bild with the given fields; returns the response and the sd-cli
    command the picture would have been drawn with."""
    ordner = tmp_path / "bildmodelle"
    config.app.bildmodelle_verzeichnis = str(ordner)
    (ordner / "lora").mkdir(parents=True)
    (ordner / "base.safetensors").write_bytes(b"x")
    (ordner / "lora" / "stil.safetensors").write_bytes(b"x")
    monkeypatch.setattr(Bildrunner, "programm", property(lambda self: Path("/fake/sd-cli")))
    monkeypatch.setattr(bildrunner.shutil, "which", lambda _: "/fake/sd-cli")
    gefangen: dict = {}

    def _erzeugen(self, auftrag, ziel):
        gefangen["befehl"] = self.befehl(auftrag, ziel)
        ziel.parent.mkdir(parents=True, exist_ok=True)
        ziel.write_bytes(b"PNG")
        return ziel

    monkeypatch.setattr(Bildrunner, "erzeugen", _erzeugen)

    def _senden(**felder):
        gefangen.clear()
        antwort = client.post("/api/v1/bild", json={"prompt": "x", "modell": "base.safetensors", **felder})
        return antwort, gefangen.get("befehl")

    return _senden


def _nach(befehl: list[str], schalter: str) -> str:
    return befehl[befehl.index(schalter) + 1]


def test_every_value_beyond_the_old_limits_reaches_sd_cli(senden):
    prompt = "a lighthouse " * 240
    antwort, befehl = senden(
        prompt=prompt, schritte=100, cfg=35, breite=2048, hoehe=1024,
        loras=[{"name": "stil.safetensors", "staerke": -0.5}], von=9, nr=9,
    )
    assert antwort.status_code == 201, antwort.text
    assert _nach(befehl, "--steps") == "100"
    assert float(_nach(befehl, "--cfg-scale")) == 35.0
    assert (_nach(befehl, "-W"), _nach(befehl, "-H")) == ("2048", "1024")
    assert "<lora:stil:-0.5>" in _nach(befehl, "-p")
    assert len(_nach(befehl, "-p")) > 3000


def test_the_chat_keeps_the_same_values():
    gehalten = bildfensterwahl.wahl_pruefen({
        "schritte": 100, "cfg": 35, "breite": 2048, "bilder_je_lauf": 9, "prompt": "x" * 3000,
        "stapel": [{"name": "stil.safetensors", "staerke": -0.5}],
    })
    assert gehalten["schritte"] == 100
    assert gehalten["cfg"] == 35
    assert gehalten["breite"] == 2048
    assert gehalten["bilder_je_lauf"] == 9
    assert len(gehalten["prompt"]) == 3000
    assert gehalten["stapel"] == [{"name": "stil.safetensors", "staerke": -0.5}]


def test_no_step_is_refused_and_an_edge_is_rounded_up_like_sd_cpp(senden):
    """Silence: what sd.cpp does not take is not drawn either, and an edge
    between the steps lands where sd.cpp would put it."""
    antwort, befehl = senden(schritte=0)
    assert antwort.status_code == 422
    assert befehl is None
    antwort, befehl = senden(breite=200, hoehe=260)
    assert antwort.status_code == 201, antwort.text
    assert (_nach(befehl, "-W"), _nach(befehl, "-H")) == ("256", "320")


def test_a_lora_strength_stays_inside_its_range(senden):
    antwort, befehl = senden(loras=[{"name": "stil.safetensors", "staerke": 25}])
    assert antwort.status_code == 201, antwort.text
    assert "<lora:stil:10.0>" in _nach(befehl, "-p")



def test_a_number_that_is_not_finite_is_refused(senden, client):
    """Without an upper limit an infinite CFG would reach sd-cli as 'inf'."""
    senden()  # lays the model folder down
    antwort = client.post(
        "/api/v1/bild", content='{"prompt": "x", "modell": "base.safetensors", "cfg": Infinity}',
        headers={"Content-Type": "application/json"},
    )
    assert antwort.status_code == 422
