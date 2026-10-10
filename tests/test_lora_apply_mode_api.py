"""The picture window's --lora-apply-mode field, on its way from a request
into the Auftrag that reaches the generator.

Free by house rule (nothing that can be shown is hidden) rather than locked
to the one value proven safe on this Metal build — see
app/bildwahlen.py's own comment on the flag, and
tests/test_photomaker.py for the value actually reaching sd-cli's command
line.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.bildrunner import Auftrag, Bildrunner
from app.config import Config


@pytest.fixture
def wunsch_senden(config: Config, client: TestClient, monkeypatch, tmp_path: Path):
    """Sends a POST /bild and returns the Auftrag that would have reached
    the generator — Bildrunner.erzeugen is mocked so no real sd-cli is
    needed."""
    config.app.bildmodelle_verzeichnis = str(tmp_path / "bildmodelle")
    bildordner = tmp_path / "bildmodelle"
    bildordner.mkdir(parents=True)
    (bildordner / "base.safetensors").write_bytes(b"x")

    monkeypatch.setattr(Bildrunner, "programm", property(lambda self: Path("/fake/sd-cli")))

    aufgerufen: dict = {}

    def _erzeugen(self, auftrag: Auftrag, ziel):
        aufgerufen["auftrag"] = auftrag
        ziel.parent.mkdir(parents=True, exist_ok=True)
        ziel.write_bytes(b"PNG")
        return ziel

    monkeypatch.setattr(Bildrunner, "erzeugen", _erzeugen)

    def _senden(**felder):
        body = {"prompt": "x", "modell": "base.safetensors", **felder}
        antwort = client.post("/api/v1/bild", json=body)
        assert antwort.status_code == 201, antwort.text
        return aufgerufen["auftrag"]

    return _senden


def test_vorgabe_ist_at_runtime(wunsch_senden):
    auftrag = wunsch_senden()
    assert auftrag.lora_apply_mode == "at_runtime"


def test_die_beiden_anderen_werte_kommen_frei_durch(wunsch_senden):
    """Not clamped back to at_runtime — a tinkerer's explicit choice reaches
    the Auftrag exactly as sent, warning label aside."""
    assert wunsch_senden(lora_apply_mode="auto").lora_apply_mode == "auto"
    assert wunsch_senden(lora_apply_mode="immediately").lora_apply_mode == "immediately"


def test_ein_unbekannter_wert_faellt_auf_die_vorgabe_zurueck(wunsch_senden):
    """Same shape as sampler/scheduler: an unknown name is not an error to
    report but a value to bring into range, same as a dragged-out-of-range
    slider — never passed on to sd-cli unchecked."""
    auftrag = wunsch_senden(lora_apply_mode="etwas-erfundenes")
    assert auftrag.lora_apply_mode == "at_runtime"


@pytest.fixture
def turbo_oder_sdcli(config: Config, client: TestClient, monkeypatch, tmp_path: Path):
    """Sends a POST /bild with a RUNNING turbo and reports which painter
    drew it — the fast server or sd-cli."""
    config.app.bildmodelle_verzeichnis = str(tmp_path / "bildmodelle")
    bildordner = tmp_path / "bildmodelle"
    bildordner.mkdir(parents=True)
    (bildordner / "base.safetensors").write_bytes(b"x")
    (bildordner / "lora").mkdir()
    (bildordner / "lora" / "l.safetensors").write_bytes(b"x")

    monkeypatch.setattr(Bildrunner, "programm", property(lambda self: Path("/fake/sd-cli")))

    gesehen: dict = {}

    def _erzeugen(self, auftrag: Auftrag, ziel):
        gesehen["maler"] = "sd-cli"
        gesehen["auftrag"] = auftrag
        ziel.parent.mkdir(parents=True, exist_ok=True)
        ziel.write_bytes(b"PNG")
        return ziel

    monkeypatch.setattr(Bildrunner, "erzeugen", _erzeugen)

    turbo = client.app.state.bildturbo
    monkeypatch.setattr(turbo, "laeuft", lambda: True)
    monkeypatch.setattr(turbo, "passt_zu", lambda *a, **k: True)
    monkeypatch.setattr(turbo, "starten", lambda *a, **k: None)
    monkeypatch.setattr(turbo, "bereit_abwarten", lambda frist, stopped=None: True)

    def _zeichnen(koerper, **k):
        gesehen["maler"] = "turbo"
        gesehen["koerper"] = koerper
        return b"PNG"

    monkeypatch.setattr(turbo, "zeichnen", _zeichnen)

    def _senden(**felder):
        body = {"prompt": "x", "modell": "base.safetensors", **felder}
        antwort = client.post("/api/v1/bild", json=body)
        assert antwort.status_code == 201, antwort.text
        return gesehen

    return _senden


LORA = [{"name": "l.safetensors", "staerke": 1.0}]


def test_ohne_lora_bleibt_jeder_modus_auf_dem_schnellen_weg(turbo_oder_sdcli):
    """The mode only matters with weights to apply — a picture without any
    keeps the fast path whatever the field says."""
    assert turbo_oder_sdcli(lora_apply_mode="auto")["maler"] == "turbo"


def test_mit_lora_bleibt_at_runtime_auf_dem_schnellen_weg(turbo_oder_sdcli):
    assert turbo_oder_sdcli(loras=LORA, lora_apply_mode="at_runtime")["maler"] == "turbo"


def test_mit_lora_geht_auto_ueber_sd_cli(turbo_oder_sdcli):
    """Measured on the pinned build: that combination applies 0 of N tensors
    and then aborts, which on the persistent server kills the SERVER and
    with it every later picture of the session. Drawn by sd-cli instead,
    where an abort costs one process and one picture.
    """
    gesehen = turbo_oder_sdcli(loras=LORA, lora_apply_mode="auto")
    assert gesehen["maler"] == "sd-cli"
    # The choice itself travels on untouched — nothing is silently replaced.
    assert gesehen["auftrag"].lora_apply_mode == "auto"


def test_mit_lora_geht_immediately_ueber_sd_cli(turbo_oder_sdcli):
    gesehen = turbo_oder_sdcli(loras=LORA, lora_apply_mode="immediately")
    assert gesehen["maler"] == "sd-cli"
    assert gesehen["auftrag"].lora_apply_mode == "immediately"


def test_eine_gesichts_lora_zaehlt_genauso(turbo_oder_sdcli):
    """The detailer's stack is weights like any other — the same abort, so
    the same way round it."""
    gesehen = turbo_oder_sdcli(ad_loras=LORA, lora_apply_mode="auto")
    assert gesehen["maler"] == "sd-cli"


def test_die_worte_des_bildservers_stehen_in_der_meldung(
    config: Config, client: TestClient, monkeypatch, tmp_path: Path
):
    """A refused draw reaches the user with the server's own explanation
    below the sentence, not as a bare "could not be drawn"."""
    from app.bildturbo import BildturboFehler

    config.app.bildmodelle_verzeichnis = str(tmp_path / "bildmodelle")
    bildordner = tmp_path / "bildmodelle"
    bildordner.mkdir(parents=True)
    (bildordner / "base.safetensors").write_bytes(b"x")

    monkeypatch.setattr(Bildrunner, "programm", property(lambda self: Path("/fake/sd-cli")))

    turbo = client.app.state.bildturbo
    monkeypatch.setattr(turbo, "laeuft", lambda: True)
    monkeypatch.setattr(turbo, "passt_zu", lambda *a, **k: True)
    monkeypatch.setattr(turbo, "bereit_abwarten", lambda frist, stopped=None: True)

    def _zeichnen(koerper, **k):
        raise BildturboFehler(
            "bild.gescheitert", 'HTTP 400 {"error":"invalid lora path: l.safetensors"}'
        )

    monkeypatch.setattr(turbo, "zeichnen", _zeichnen)

    antwort = client.post(
        "/api/v1/bild", json={"prompt": "x", "modell": "base.safetensors"}
    )
    assert antwort.status_code == 503
    assert "invalid lora path: l.safetensors" in antwort.json()["detail"]
