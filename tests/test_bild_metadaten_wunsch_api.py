"""Whether a drawn picture keeps the settings sd.cpp writes into its file.

One switch says so for every picture (app/bildschutz.py, Settings › Memory):
on, the finished file is stripped; off, it keeps its prompt and values. The
draw route has no field of its own for it. ``Bildrunner.erzeugen`` is mocked
to write a real PNG carrying a text chunk, so the strip is proven on actual
bytes rather than assumed from a value.
"""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.bildrunner import Bildrunner
from app.bildschutz import SCHLUESSEL
from app.config import Config


def _block(typ: bytes, koerper: bytes) -> bytes:
    pruef = zlib.crc32(typ + koerper) & 0xFFFFFFFF
    return struct.pack(">I", len(koerper)) + typ + koerper + struct.pack(">I", pruef)


def _png_mit_prompt() -> bytes:
    """A real, parseable PNG carrying a text chunk with a prompt to strip."""
    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = _block(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
    text = _block(b"tEXt", b"parameters\x00ein geheimer Prompt")
    idat = _block(b"IDAT", zlib.compress(b"\x00\x11\x22\x33"))
    iend = _block(b"IEND", b"")
    return sig + ihdr + text + idat + iend


PNG = _png_mit_prompt()


@pytest.fixture
def bild_senden(config: Config, client: TestClient, monkeypatch, tmp_path: Path):
    """Sends a POST /bild and returns the bytes the picture was stored as.
    The switch ships on; ``switch`` sets it for the one request."""
    config.app.bildmodelle_verzeichnis = str(tmp_path / "bildmodelle")
    bildordner = tmp_path / "bildmodelle"
    bildordner.mkdir(parents=True)
    (bildordner / "base.safetensors").write_bytes(b"x")

    monkeypatch.setattr(Bildrunner, "programm", property(lambda self: Path("/fake/sd-cli")))

    def _erzeugen(self, auftrag, ziel):
        ziel.parent.mkdir(parents=True, exist_ok=True)
        ziel.write_bytes(PNG)
        return ziel

    monkeypatch.setattr(Bildrunner, "erzeugen", _erzeugen)

    def _senden(switch: bool):
        client.app.state.repositories.einstellungen.setzen("global", SCHLUESSEL, {"an": switch})
        antwort = client.post("/api/v1/bild", json={"prompt": "x", "modell": "base.safetensors"})
        assert antwort.status_code == 201, antwort.text
        name = antwort.json()["bild"]
        return client.get(f"/api/v1/images/{name}").content

    return _senden


def test_with_the_switch_off_the_picture_keeps_its_prompt(bild_senden):
    inhalt = bild_senden(switch=False)
    assert b"tEXt" in inhalt
    assert b"Prompt" in inhalt


def test_with_the_switch_on_the_picture_loses_its_prompt(bild_senden):
    inhalt = bild_senden(switch=True)
    assert b"tEXt" not in inhalt
    assert b"Prompt" not in inhalt


def test_the_draw_route_has_no_metadata_field_of_its_own(bild_senden, client):
    """A request cannot say it: the route refuses the old field instead of
    taking it silently and doing nothing with it."""
    bild_senden(switch=False)
    antwort = client.post(
        "/api/v1/bild", json={"prompt": "x", "modell": "base.safetensors", "metadaten": False},
    )
    assert antwort.status_code == 422, antwort.text


def test_the_switch_strips_a_picture_drawn_by_the_server_too(config, client, monkeypatch, tmp_path):
    """The strip sits after the runner/turbo branch, applying to both — but
    that is a claim about control flow, and this run mocks Bildrunner alone.
    Every other test in this file would pass unchanged if the strip sat
    inside the runner-only branch instead: this one actually goes through
    Image-Turbo's own path (see test_bild_bausatz_api.py's
    bausatz_turbo_senden for the same mocking shape) to prove the claim."""
    client.app.state.repositories.einstellungen.setzen("global", SCHLUESSEL, {"an": True})
    config.app.bildmodelle_verzeichnis = str(tmp_path / "bildmodelle")
    bildordner = tmp_path / "bildmodelle"
    bildordner.mkdir(parents=True)
    (bildordner / "base.safetensors").write_bytes(b"x")
    monkeypatch.setattr(Bildrunner, "programm", property(lambda self: Path("/fake/sd-cli")))

    turbo = client.app.state.bildturbo
    turbo._prozess = object()  # laeuft() sagt ja
    monkeypatch.setattr(turbo, "laeuft", lambda: True)
    monkeypatch.setattr(turbo, "belegt_gb", lambda: None)
    monkeypatch.setattr(turbo, "passt_zu", lambda *a, **k: True)  # kein Neustart noetig
    monkeypatch.setattr(turbo, "zeichnen", lambda *a, **k: PNG)

    antwort = client.post(
        "/api/v1/bild",
        json={"prompt": "x", "modell": "base.safetensors"},
    )
    assert antwort.status_code == 201, antwort.text
    inhalt = client.get(f"/api/v1/images/{antwort.json()['bild']}").content
    assert b"tEXt" not in inhalt
    assert b"Prompt" not in inhalt
