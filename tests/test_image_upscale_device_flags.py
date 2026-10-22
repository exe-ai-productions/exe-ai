"""The command that enlarges a picture carries the machine's devices.

Threads, VRAM budget, offloading to RAM, the split and the backend were set
for every picture of the machine and left off the command of an enlargement,
which returned before they were added. The upscaler reads the threads, the
backend, the place of the weights and the VRAM budget (sd.cpp's
``UpscalerGGML``); a switch only a picture has stays off its line.
"""

from __future__ import annotations

from pathlib import Path

from app.bildrunner import Auftrag, Bildrunner


def _runner(tmp_path: Path, monkeypatch) -> Bildrunner:
    monkeypatch.setattr(Bildrunner, "programm", property(lambda self: Path("/fake/sd-cli")))
    return Bildrunner(tmp_path / "data")


def _upscale(**fields) -> Auftrag:
    return Auftrag(
        modell=Path("/m"), prompt="", mode="upscale",
        upscale_model=Path("/u/esrgan.pth"), startbild=Path("/in.png"), **fields,
    )


def test_the_upscale_command_carries_the_machine_values(tmp_path, monkeypatch):
    command = _runner(tmp_path, monkeypatch).befehl(
        _upscale(
            threads=6, vram_limit="4", offload_to_cpu=True, split_mode="layer", backend="cuda0",
        ),
        Path("/out.png"),
    )
    assert command[1:3] == ["-M", "upscale"]
    for flag, value in (("--threads", "6"), ("--max-vram", "4"), ("--split-mode", "layer"),
                        ("--backend", "cuda0")):
        assert command[command.index(flag) + 1] == value
    assert "--offload-to-cpu" in command
    assert command[command.index("-i") + 1] == str(Path("/in.png"))
    assert command[-2:] == ["-o", str(Path("/out.png"))]


def test_values_that_are_unset_stay_off_the_line(tmp_path, monkeypatch):
    command = _runner(tmp_path, monkeypatch).befehl(_upscale(), Path("/out.png"))
    assert command == [
        str(Path("/fake/sd-cli")), "-M", "upscale", "--upscale-model", str(Path("/u/esrgan.pth")),
        "-i", str(Path("/in.png")), "-o", str(Path("/out.png")),
    ]


def test_only_the_switch_the_upscaler_reads_is_carried(tmp_path, monkeypatch):
    command = _runner(tmp_path, monkeypatch).befehl(
        _upscale(switches={"params_backend": "cpu", "conditioning_cache_size": 4, "sage_attn": True}),
        Path("/out.png"),
    )
    assert command[command.index("--params-backend") + 1] == "cpu"
    assert "--conditioning-cache-size" not in command
    assert "--sage-attn" not in command


def test_a_picture_carries_the_same_device_values(tmp_path, monkeypatch):
    runner = _runner(tmp_path, monkeypatch)
    picture = Auftrag(
        modell=Path("/m.safetensors"), prompt="x",
        threads=6, vram_limit="4", offload_to_cpu=True, split_mode="layer", backend="cuda0",
    )
    command = runner.befehl(picture, Path("/out.png"))
    for flag, value in (("--threads", "6"), ("--max-vram", "4"), ("--split-mode", "layer"),
                        ("--backend", "cuda0")):
        assert command[command.index(flag) + 1] == value
    assert "--offload-to-cpu" in command
