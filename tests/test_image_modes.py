"""The modes beside drawing: repairing faces and upscaling a finished
picture, converting a model file, the importance matrix, the devices."""

from __future__ import annotations

import base64
import subprocess
from pathlib import Path

import pytest

from app import bildrunner, bildturbo, model_convert
from app.api.v1 import bild as bildapi
from app.bildrunner import Auftrag, BildFehler, Bildrunner, imatrix_path


@pytest.fixture
def runner(tmp_path: Path, monkeypatch) -> Bildrunner:
    monkeypatch.setattr(bildrunner.shutil, "which", lambda _: "/somewhere/sd-cli")
    return Bildrunner(tmp_path)


def test_upscaling_alone_takes_its_own_command(runner, tmp_path):
    befehl = runner.befehl(
        Auftrag(modell=tmp_path / "m.gguf", prompt="x", mode="upscale",
                upscale_model=tmp_path / "esrgan.pth", startbild=tmp_path / "in.png"),
        tmp_path / "out.png",
    )
    assert befehl == [str(Path("/somewhere/sd-cli")), "-M", "upscale", "--upscale-model",
                      str(tmp_path / "esrgan.pth"), "-i", str(tmp_path / "in.png"),
                      "-o", str(tmp_path / "out.png")]


def test_repairing_faces_alone_runs_the_detailer_mode(runner, tmp_path):
    befehl = runner.befehl(
        Auftrag(modell=tmp_path / "m.gguf", prompt="x", mode="adetailer",
                ad_modell=tmp_path / "face.safetensors", startbild=tmp_path / "in.png",
                staerke=0.4),
        tmp_path / "out.png",
    )
    assert befehl[1:3] == ["-M", "adetailer"]
    assert befehl[befehl.index("--ad-model") + 1] == str(tmp_path / "face.safetensors")
    assert befehl[befehl.index("-i") + 1] == str(tmp_path / "in.png")


def test_a_mode_without_its_parts_is_refused(runner, tmp_path):
    for auftrag in (
        Auftrag(modell=tmp_path / "m", prompt="x", mode="upscale", startbild=tmp_path / "i"),
        Auftrag(modell=tmp_path / "m", prompt="x", mode="adetailer", startbild=tmp_path / "i"),
    ):
        with pytest.raises(BildFehler):
            runner.befehl(auftrag, tmp_path / "o.png")


def test_silence_drawing_stays_as_it_was(runner, tmp_path):
    befehl = runner.befehl(Auftrag(modell=tmp_path / "m.gguf", prompt="x"), tmp_path / "o.png")
    assert "-M" not in befehl and "--imat-out" not in befehl


def test_the_importance_matrix_is_collected_and_continued(runner, tmp_path):
    matrix = imatrix_path(tmp_path / "m.gguf")
    auftrag = Auftrag(modell=tmp_path / "m.gguf", prompt="x", imatrix=matrix)
    befehl = runner.befehl(auftrag, tmp_path / "o.png")
    assert befehl[befehl.index("--imat-out") + 1] == str(matrix)
    assert "--imat-in" not in befehl
    matrix.write_bytes(b"M")
    assert "--imat-in" in runner.befehl(auftrag, tmp_path / "o.png")
    assert bildapi._cli_only_reason(auftrag, False)


def test_converting_calls_convert_with_source_and_target(tmp_path):
    quelle = tmp_path / "model.safetensors"
    befehl = model_convert.command(Path("/sd-cli"), quelle, "q8_0")
    assert befehl == [str(Path("/sd-cli")), "-M", "convert", "-m", str(quelle),
                      "-o", str(tmp_path / "model.q8_0.gguf"), "--type", "q8_0"]
    imatrix_path(quelle).write_bytes(b"M")
    befehl = model_convert.command(Path("/sd-cli"), quelle, "q4_K")
    assert befehl[-2:] == ["--imat-in", str(imatrix_path(quelle))]


def test_converting_never_overwrites(runner, tmp_path, monkeypatch):
    quelle = tmp_path / "model.safetensors"
    (tmp_path / "model.q8_0.gguf").write_bytes(b"old")
    monkeypatch.setattr(Bildrunner, "run_tool", lambda *a, **k: pytest.fail("ran"))
    with pytest.raises(model_convert.ConvertError):
        model_convert.convert(runner, Path("/sd-cli"), quelle, "q8_0")
    assert (tmp_path / "model.q8_0.gguf").read_bytes() == b"old"


def test_the_device_list_is_read_line_by_line(monkeypatch):
    monkeypatch.setattr(
        model_convert.subprocess, "run",
        lambda *a, **k: subprocess.CompletedProcess(a, 0, stdout="MTL0\tApple M2\nCPU\tApple M2\n", stderr=""),
    )
    assert model_convert.devices(Path("/sd-cli")) == [
        {"name": "MTL0", "description": "Apple M2"}, {"name": "CPU", "description": "Apple M2"},
    ]


def test_upscaling_on_the_server_uses_its_upscale_route(tmp_path, monkeypatch):
    turbo = bildturbo.Bildturbo(tmp_path)
    monkeypatch.setattr(turbo, "laeuft", lambda: True)
    monkeypatch.setattr(turbo, "bereit_abwarten", lambda frist=0, stopped=None: True)
    seen = {}

    class Answer:
        def raise_for_status(self):
            pass

        def json(self):
            return {"images": [{"b64_json": base64.b64encode(b"BIG").decode()}]}

    def post(url, json, timeout):
        seen["url"], seen["body"] = url, json
        return Answer()

    monkeypatch.setattr(bildturbo.httpx, "post", post)
    start = tmp_path / "in.png"
    start.write_bytes(b"SMALL")
    runner = Bildrunner(tmp_path)
    ziel = tmp_path / "out.png"
    bildapi._upscale_on_server(
        runner, turbo,
        Auftrag(modell=tmp_path / "m", prompt="x", mode="upscale", startbild=start,
                upscale_model=tmp_path / "esrgan.pth"),
        ziel,
    )
    assert seen["url"].endswith("/sdcpp/v1/upscale")
    assert seen["body"]["upscaler"] == "esrgan"
    assert base64.b64decode(seen["body"]["image"]) == b"SMALL"
    assert ziel.read_bytes() == b"BIG"
    assert not runner.laeuft()


def test_a_stop_during_upscaling_on_the_server_drops_the_answer(tmp_path, monkeypatch):
    turbo = bildturbo.Bildturbo(tmp_path)
    monkeypatch.setattr(turbo, "laeuft", lambda: True)
    monkeypatch.setattr(turbo, "bereit_abwarten", lambda frist=0, stopped=None: True)

    class Answer:
        def raise_for_status(self):
            pass

        def json(self):
            return {"images": [{"b64_json": base64.b64encode(b"BIG").decode()}]}

    def post(url, json, timeout):
        assert turbo.abbrechen()
        return Answer()

    monkeypatch.setattr(bildturbo.httpx, "post", post)
    with pytest.raises(bildturbo.BildturboFehler) as error:
        turbo.upscale("AAAA", "esrgan")
    assert error.value.grund == "bild.abgebrochen"


def test_a_stop_while_the_server_still_loads_is_heard(tmp_path, monkeypatch):
    turbo = bildturbo.Bildturbo(tmp_path)
    monkeypatch.setattr(turbo, "laeuft", lambda: True)

    def still_loading(frist=0):
        assert turbo.abbrechen()
        return True

    monkeypatch.setattr(turbo, "bereit_abwarten", still_loading)
    monkeypatch.setattr(bildturbo.httpx, "post", lambda *a, **k: pytest.fail("posted"))
    with pytest.raises(bildturbo.BildturboFehler) as error:
        turbo.upscale("AAAA", "esrgan")
    assert error.value.grund == "bild.abgebrochen"
