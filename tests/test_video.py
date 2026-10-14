"""Video: every kind and every video family reaches sd-cli as its command
line and the picture server as its ``vid_gen`` call, the finished video
lands and is served — and a still picture is drawn exactly as before."""

from __future__ import annotations

import base64
import json
import struct
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import bildrunner, bildturbo, image_families, image_switches
from app.api.v1 import bild as bildapi
from app.bildrunner import Auftrag, Bildrunner
from app.config import Config

_VIDEO_FAMILIES = [family for family in image_families.FAMILIES if family.video]


@pytest.fixture
def runner(tmp_path: Path, monkeypatch) -> Bildrunner:
    monkeypatch.setattr(bildrunner.shutil, "which", lambda _: "/somewhere/sd-cli")
    return Bildrunner(tmp_path)


def _befehl(runner: Bildrunner, tmp_path: Path, **fields) -> list[str]:
    fields.setdefault("modell", tmp_path / "m.gguf")
    return runner.befehl(Auftrag(prompt="x", **fields), tmp_path / "a.webm")


def _after(command: list[str], flag: str) -> str:
    return command[command.index(flag) + 1]


# --- sd-cli, kind by kind -----------------------------------------------------


def _wan(tmp_path: Path, **fields) -> dict:
    return dict(
        familie="wan", diffusion_model=tmp_path / "wan.safetensors",
        t5xxl=tmp_path / "umt5.gguf", vae=tmp_path / "wan_vae.safetensors",
        video=True, **fields,
    )


def test_text_to_video_runs_in_video_mode(runner, tmp_path):
    command = _befehl(runner, tmp_path, **_wan(tmp_path, video_frames=33, fps=16))
    assert command[1:3] == ["-M", "vid_gen"]
    assert _after(command, "--video-frames") == "33"
    assert _after(command, "--fps") == "16"
    assert _after(command, "-o") == str(tmp_path / "a.webm")
    assert _after(command, "--diffusion-model") == str(tmp_path / "wan.safetensors")
    assert _after(command, "--t5xxl") == str(tmp_path / "umt5.gguf")
    for absent in ("-i", "--end-img", "--control-video"):
        assert absent not in command


def test_unset_frames_and_rate_leave_sd_cli_its_own(runner, tmp_path):
    command = _befehl(runner, tmp_path, **_wan(tmp_path))
    assert "--video-frames" not in command
    assert "--fps" not in command


def test_image_to_video_starts_from_the_first_frame(runner, tmp_path):
    first = tmp_path / "first.png"
    command = _befehl(runner, tmp_path, **_wan(tmp_path, startbild=first, staerke=0.8))
    assert _after(command, "-i") == str(first)
    assert "--end-img" not in command


def test_first_and_last_frame_carry_both(runner, tmp_path):
    first, last = tmp_path / "first.png", tmp_path / "last.png"
    command = _befehl(runner, tmp_path, **_wan(tmp_path, startbild=first, end_image=last))
    assert _after(command, "-i") == str(first)
    assert _after(command, "--end-img") == str(last)


def test_video_to_video_reads_its_frames_from_one_folder(runner, tmp_path):
    frames = []
    for number in range(3):
        frame = tmp_path / f"{'cba'[number]}{number}.PNG"
        frame.write_bytes(bytes([number]))
        frames.append(frame)
    command = _befehl(runner, tmp_path, **_wan(tmp_path, control_frames=tuple(frames)))
    assert _after(command, "--control-video") == str(runner.frames_folder)
    # The frames in their order, under names that sort in it.
    runner._lay_out_frames(runner.frames_folder, tuple(frames))
    laid = sorted(runner.frames_folder.iterdir())
    assert [p.name for p in laid] == ["00000.png", "00001.png", "00002.png"]
    assert [p.read_bytes() for p in laid] == [b"\x00", b"\x01", b"\x02"]
    # A run without a control video leaves no folder behind.
    runner._lay_out_frames(runner.frames_folder, ())
    assert not runner.frames_folder.exists()


def test_a_reference_video_goes_to_sd_cli_as_its_own_folder(runner, tmp_path):
    """MiniMax-H3 Ref2VA: the reference video's frames are laid into a
    folder of their own beside the control video's, and its sound travels
    with it."""
    frames = []
    for number in range(2):
        frame = tmp_path / f"ref{number}.png"
        frame.write_bytes(bytes([number]))
        frames.append(frame)
    sound = tmp_path / "voice.wav"
    values = image_switches.active(
        image_switches.check({"ref_video_audio": "voice.wav"}), {"video": True, "ref_video": True}
    )
    command = _befehl(
        runner, tmp_path,
        **_wan(tmp_path, ref_video_frames=tuple(frames), switches=values,
               switch_paths={"ref_video_audio": sound}),
    )
    assert _after(command, "--ref-video") == str(runner.ref_frames_folder)
    assert _after(command, "--ref-video-audio") == str(sound)
    assert runner.ref_frames_folder.parent == runner.frames_folder.parent
    assert runner.ref_frames_folder != runner.frames_folder
    runner._lay_out_frames(runner.ref_frames_folder, tuple(frames))
    assert [p.name for p in sorted(runner.ref_frames_folder.iterdir())] == ["00000.png", "00001.png"]
    assert not runner.frames_folder.exists()
    # Only sd-cli draws it: the server's body has no field for the frames.
    job = Auftrag(modell=tmp_path / "m.gguf", prompt="x", video=True, ref_video_frames=tuple(frames))
    assert bildapi._cli_only_reason(job, False) == "a reference video"


def test_silence_without_a_reference_video_nothing_of_it_is_sent(runner, tmp_path):
    """No reference video: no ``--ref-video``, and its sound is dropped —
    sd-cli pairs the two by position. The reference sound and the control
    video go as before."""
    assert image_switches.active(
        image_switches.check({"ref_video_audio": "voice.wav", "ref_audio": "tone.wav"}),
        {"video": True},
    ) == {"ref_audio": "tone.wav"}
    control = tmp_path / "c.png"
    control.write_bytes(b"c")
    tone = tmp_path / "tone.wav"
    command = _befehl(
        runner, tmp_path,
        **_wan(tmp_path, control_frames=(control,), switches={"ref_audio": "tone.wav"},
               switch_paths={"ref_audio": tone}),
    )
    assert "--ref-video" not in command
    assert "--ref-video-audio" not in command
    assert _after(command, "--ref-audio") == str(tone)
    assert _after(command, "--control-video") == str(runner.frames_folder)
    job = Auftrag(modell=tmp_path / "m.gguf", prompt="x", video=True, control_frames=(control,))
    assert bildapi._cli_only_reason(job, False) is None


def test_the_high_noise_model_brings_its_values(runner, tmp_path):
    values = image_switches.active(
        {"high_noise_steps": 8, "high_noise_cfg_scale": 3.5, "high_noise_sampling_method": "euler"},
        {"video": True, "high_noise": True},
    )
    command = _befehl(runner, tmp_path, **_wan(
        tmp_path, high_noise_diffusion_model=tmp_path / "high.gguf", switches=values,
    ))
    assert _after(command, "--high-noise-diffusion-model") == str(tmp_path / "high.gguf")
    assert _after(command, "--high-noise-steps") == "8"
    assert _after(command, "--high-noise-cfg-scale") == "3.5"
    assert _after(command, "--high-noise-sampling-method") == "euler"


def test_high_noise_values_act_only_beside_the_high_noise_model():
    values = {"high_noise_steps": 8, "moe_boundary": 0.9}
    assert image_switches.active(values, {"video": True}) == {"moe_boundary": 0.9}


def test_animatediff_moves_a_checkpoint(runner, tmp_path):
    values = image_switches.active({"motion_module": "mm_sd15_v3.safetensors"}, {"video": True})
    command = _befehl(
        runner, tmp_path, familie="sd15", video=True, video_frames=8, fps=8,
        switches=values, switch_paths={"motion_module": tmp_path / "mm_sd15_v3.safetensors"},
    )
    assert command[1:3] == ["-M", "vid_gen"]
    assert _after(command, "-m") == str(tmp_path / "m.gguf")
    assert _after(command, "--motion-module") == str(tmp_path / "mm_sd15_v3.safetensors")


@pytest.mark.parametrize("family", _VIDEO_FAMILIES, ids=lambda f: f.name)
def test_each_video_family_builds_its_command(runner, tmp_path, family):
    """Every file the family reads rides on its own switch, in video mode."""
    files = {name: tmp_path / f"{name}.bin" for name in (*family.encoders, *family.parts)}
    command = _befehl(
        runner, tmp_path, familie=family.name, diffusion_model=tmp_path / "d.gguf",
        video=True, video_frames=family.start.frames, **files,
    )
    assert command[1:3] == ["-M", "vid_gen"]
    for name, path in files.items():
        flag = {"t5xxl": "--t5xxl", "llm": "--llm", **bildrunner.bildbausatz.PART_SWITCHES}[name]
        assert _after(command, flag) == str(path)
    assert _after(command, "--video-frames") == str(family.start.frames)


def test_every_video_family_names_its_docs_frames():
    for family in _VIDEO_FAMILIES:
        assert family.start.frames is not None, family.name
        assert "frames" in family.start.sources, family.name


def test_a_still_picture_is_drawn_as_before(runner, tmp_path):
    """The silence probe: no video switch, no video mode, no video row."""
    values = image_switches.active(
        {"video_format": "webm", "high_noise_steps": 8, "motion_module": "mm.safetensors",
         "output_format": "jpg"},
        {"high_noise": True},
    )
    assert values == {"output_format": "jpg"}
    command = runner.befehl(Auftrag(modell=tmp_path / "m.gguf", prompt="x", switches=values),
                            tmp_path / "a.jpg")
    for absent in ("-M", "vid_gen", "--video-frames", "--fps", "--end-img", "--control-video",
                   "--motion-module", "--high-noise-steps"):
        assert absent not in command


def test_a_video_is_named_after_its_container():
    assert image_switches.output_suffix({}, video=True) == ".webm"
    assert image_switches.output_suffix({"video_format": "avi"}, video=True) == ".avi"
    assert image_switches.output_suffix({"output_format": "jpg"}, video=True) == ".webm"
    assert image_switches.output_suffix({"video_format": "webp"}) == ".png"


# --- The picture server's vid_gen ---------------------------------------------


def test_the_server_body_of_a_video(tmp_path):
    first, last = tmp_path / "first.png", tmp_path / "last.png"
    frames = (tmp_path / "f0.png", tmp_path / "f1.png")
    for picture in (first, last, *frames):
        picture.write_bytes(picture.name.encode())
    values = image_switches.active(
        {"high_noise_steps": 8, "high_noise_skip_layers": "[7,8,9]", "moe_boundary": 0.9,
         "temporal_tiling": True, "tiling_temporal_tile_frames": 8},
        {"video": True, "high_noise": True},
    )
    body = bildapi._turbo_video_body(Auftrag(
        modell=Path("/m"), prompt="x", video=True, video_frames=33, fps=16,
        startbild=first, end_image=last, control_frames=frames, switches=values,
    ))
    assert body["video_frames"] == 33
    assert body["fps"] == 16
    assert base64.b64decode(body["init_image"]) == b"first.png"
    assert base64.b64decode(body["end_image"]) == b"last.png"
    assert [base64.b64decode(f) for f in body["control_frames"]] == [b"f0.png", b"f1.png"]
    assert body["output_format"] == "webm"
    assert body["moe_boundary"] == 0.9
    assert body["high_noise_sample_params"] == {
        "sample_steps": 8, "guidance": {"slg": {"layers": [7, 8, 9]}},
    }
    assert body["vae_tiling_params"]["temporal_tiling"] is True
    assert body["vae_tiling_params"]["extra_tiling_args"] == "temporal_tile_frames=8"
    for absent in ("embed_image_metadata", "ref_images", "mask_image", "control_image"):
        assert absent not in body


def test_the_chosen_container_goes_to_the_server():
    values = image_switches.active({"video_format": "webp"}, {"video": True})
    body = bildapi._turbo_video_body(
        Auftrag(modell=Path("/m"), prompt="x", video=True, switches=values)
    )
    assert body["output_format"] == "webp"


def test_a_still_picture_body_carries_no_video_field():
    """The silence probe on the server path."""
    body = bildapi._turbo_auftrag(Auftrag(modell=Path("/m"), prompt="x"))
    for absent in ("video_frames", "fps", "end_image", "control_frames", "high_noise_sample_params"):
        assert absent not in body
    assert body["output_format"] == "png"


class _Answer:
    def __init__(self, data: dict) -> None:
        self._data = data

    def raise_for_status(self) -> None:
        pass

    def json(self) -> dict:
        return self._data


def test_the_server_draws_a_video_over_vid_gen(tmp_path, monkeypatch):
    posted: list[str] = []
    container = b"\x1aE\xdf\xa3webm"

    def post(url, json=None, timeout=None):
        posted.append(url)
        return _Answer({"id": "job_1", "status": "queued"})

    def get(url, timeout=None):
        return _Answer({"id": "job_1", "status": "completed", "result": {
            "output_format": "webm", "mime_type": "video/webm", "fps": 16, "frame_count": 33,
            "b64_json": base64.b64encode(container).decode(),
        }})

    monkeypatch.setattr(bildturbo.httpx, "post", post)
    monkeypatch.setattr(bildturbo.httpx, "get", get)
    turbo = bildturbo.Bildturbo(tmp_path)
    monkeypatch.setattr(turbo, "laeuft", lambda: True)
    monkeypatch.setattr(turbo, "bereit_abwarten", lambda frist=0, stopped=None: True)
    assert turbo.zeichnen({"prompt": "x"}, video=True) == container
    assert [url.rsplit("/", 1)[1] for url in posted] == ["vid_gen"]


def test_the_server_matches_its_video_parts(tmp_path):
    turbo = bildturbo.Bildturbo(tmp_path)
    turbo._video_parts = bildturbo._part_names({"high_noise_diffusion_model": Path("/x/high.gguf")})
    assert turbo._video_parts == (("high_noise_diffusion_model", "high.gguf"),)
    assert bildturbo._part_names({}) == ()


# --- The route, the file and its address ----------------------------------------


def _safetensors(path: Path, shapes: dict[str, list[int]]) -> Path:
    header = {n: {"dtype": "F16", "shape": s, "data_offsets": [0, 0]} for n, s in shapes.items()}
    raw = json.dumps(header).encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(struct.pack("<Q", len(raw)) + raw)
    return path


@pytest.fixture
def picture_folder(config: Config, tmp_path: Path) -> Path:
    folder = tmp_path / "bildmodelle"
    folder.mkdir()
    config.app.bildmodelle_verzeichnis = str(folder)
    return folder


@pytest.fixture
def wan_folder(picture_folder: Path) -> Path:
    _safetensors(picture_folder / "wan.safetensors", {
        "blocks.0.cross_attn.norm_k.weight": [1536],
        "patch_embedding.weight": [1536, 16, 1, 2, 2],
    })
    _safetensors(picture_folder / "text_encoders" / "umt5.safetensors", {
        "encoder.block.0.layer.0.SelfAttention.q.weight": [4096, 4096],
        "shared.weight": [256384, 4096],
    })
    _safetensors(picture_folder / "vae" / "wan_vae.safetensors", {
        "decoder.conv1.weight": [384, 16, 3, 3, 3], "encoder.conv1.weight": [96, 3, 3, 3, 3],
    })
    _safetensors(picture_folder / "vae" / "ae.safetensors", {
        "decoder.conv_in.weight": [512, 16, 3, 3],
    })
    return picture_folder


def test_a_video_model_opens_with_its_parts_and_frames(client: TestClient, wan_folder: Path):
    v = client.get("/api/v1/bild/vorgaben", params={"modell": "wan.safetensors"}).json()
    assert v["family"] == "wan"
    # UMT5, and no VAE by itself: Wan 2.1's video VAE and Qwen-Image's carry
    # the same header, so the model's own setting holds it.
    assert v["parts"] == {"t5xxl": "umt5.safetensors"}
    assert (v["video_frames"], v["fps"], v["breite"], v["hoehe"]) == (81, 16, 832, 480)


def test_a_video_is_drawn_stored_and_served(client: TestClient, wan_folder: Path, monkeypatch):
    seen: dict = {}

    def _draw(self, job, target):
        seen["job"] = job
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"\x1aE\xdf\xa3webm")
        return target

    def _no_strip(data: bytes) -> bytes:
        raise AssertionError("a video has no picture settings to strip")

    monkeypatch.setattr(Bildrunner, "programm", property(lambda self: Path("/fake/sd-cli")))
    monkeypatch.setattr(Bildrunner, "erzeugen", _draw)
    monkeypatch.setattr(bildapi, "metadaten_entfernen", _no_strip)
    answer = client.post("/api/v1/bild", json={
        "prompt": "x", "modell": "wan.safetensors", "diffusion_model": "wan.safetensors",
        "t5xxl": "umt5.safetensors", "vae": "wan_vae.safetensors", "video_frames": 33,
    })
    assert answer.status_code == 201, answer.text
    name = answer.json()["bild"]
    # A video model draws a video even when the wish does not say so.
    assert name.endswith(".webm")
    assert seen["job"].video is True
    assert seen["job"].video_frames == 33
    served = client.get(f"/api/v1/images/{name}")
    assert served.status_code == 200
    assert served.headers["content-type"] == "video/webm"
    assert served.content == b"\x1aE\xdf\xa3webm"
    # The wall lists pictures one drags into a message, not videos.
    assert name not in client.get("/api/v1/bilder").json()["bilder"]


def test_a_wish_with_a_reference_video_reaches_the_painter(
    client: TestClient, wan_folder: Path, monkeypatch,
):
    """The frames go up as working pictures and are read from there; the
    sound is a file of the audio folder and travels only beside them."""
    from app.speicherorte import scratch_pictures_dir

    seen: list = []

    def _draw(self, job, target):
        seen.append(job)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"\x1aE\xdf\xa3webm")
        return target

    monkeypatch.setattr(Bildrunner, "programm", property(lambda self: Path("/fake/sd-cli")))
    monkeypatch.setattr(Bildrunner, "erzeugen", _draw)
    (wan_folder / "audio").mkdir()
    (wan_folder / "audio" / "voice.wav").write_bytes(b"RIFF")
    frames = [
        client.post(
            "/api/v1/images?scratch=true", content=b"\x89PNG\r\n\x1a\n" + bytes([number]),
            headers={"Content-Type": "image/png"},
        ).json()["bild"]
        for number in range(2)
    ]
    wish = {
        "prompt": "x", "modell": "wan.safetensors", "diffusion_model": "wan.safetensors",
        "t5xxl": "umt5.safetensors", "vae": "wan_vae.safetensors",
        "switches": {"ref_video_audio": "voice.wav"},
    }

    answer = client.post(
        "/api/v1/bild", json={**wish, "ref_video_frames": frames, "steuerbilder": frames[:1]}
    )
    assert answer.status_code == 201, answer.text
    scratch = scratch_pictures_dir(client.app.state.config)
    assert seen[-1].ref_video_frames == tuple(scratch / name for name in frames)
    # A control video's frames are read from the working pictures alike.
    assert seen[-1].control_frames == (scratch / frames[0],)
    assert seen[-1].switches == {"ref_video_audio": "voice.wav"}
    assert seen[-1].switch_paths == {"ref_video_audio": wan_folder / "audio" / "voice.wav"}

    # Silence probe: without the frames the sound is not sent either.
    answer = client.post("/api/v1/bild", json=wish)
    assert answer.status_code == 201, answer.text
    assert seen[-1].ref_video_frames == ()
    assert seen[-1].switches == {}


def test_a_mode_on_a_video_is_refused(client: TestClient, wan_folder: Path, monkeypatch):
    monkeypatch.setattr(Bildrunner, "programm", property(lambda self: Path("/fake/sd-cli")))
    answer = client.post("/api/v1/bild", json={
        "prompt": "x", "modell": "wan.safetensors", "video": True, "mode": "upscale",
    })
    assert answer.status_code == 400


# --- Round-one findings --------------------------------------------------------


def _sd_cli_help() -> str | None:
    """sd-cli's own help, where the program is on the PATH."""
    import shutil
    import subprocess

    program = shutil.which("sd-cli")
    if program is None:
        return None
    run = subprocess.run([program, "--help"], capture_output=True, text=True, timeout=60)
    return run.stdout + run.stderr


def test_every_switch_is_one_sd_cli_knows():
    """A flag sd-cli does not know stops every picture that carries it."""
    import re

    text = _sd_cli_help()
    if text is None:
        pytest.skip("no sd-cli on this machine")
    known = set(re.findall(r"--[a-z0-9_-]+", text))
    flags = {s.flag for s in image_switches.SWITCHES if s.flag}
    flags |= {s.list_flag for s in image_switches.SWITCHES if s.list_flag}
    flags |= set(bildrunner.bildbausatz.PART_SWITCHES.values())
    assert sorted(flags - known) == []


def test_a_sound_file_goes_to_sd_cli():
    """The server reads no sound file; a video with one is drawn by sd-cli."""
    for key in ("audio", "ref_audio", "ref_video_audio"):
        assert image_switches.cli_only({key: "voice.wav"})
    assert image_switches.cli_only({"video_format": "webm"}) is None


def test_hunyuan_video_is_given_no_flux_t5(client: TestClient, picture_folder: Path):
    """Its t5xxl field takes ByT5, which no header tells apart: Flux's
    T5-XXL lying beside it is not proposed."""
    _safetensors(picture_folder / "hy.safetensors", {
        "txt_in.individual_token_refiner.blocks.0.adaLN_modulation.1.weight": [6144, 3072],
    })
    _safetensors(picture_folder / "text_encoders" / "t5.safetensors", {
        "encoder.block.0.layer.0.SelfAttention.q.weight": [4096, 4096],
        "shared.weight": [32128, 4096],
    })
    v = client.get("/api/v1/bild/vorgaben", params={"modell": "hy.safetensors"}).json()
    assert v["family"] == "hunyuan_video"
    assert "t5xxl" not in v["parts"]


@pytest.fixture
def sd15_folder(picture_folder: Path) -> Path:
    _safetensors(picture_folder / "sd15.safetensors", {
        "model.diffusion_model.input_blocks.0.0.weight": [320, 4, 3, 3],
        "model.diffusion_model.middle_block.1.norm.weight": [1280],
        "model.diffusion_model.output_blocks.7.1.norm.weight": [640],
        "cond_stage_model.transformer.text_model.embeddings.token_embedding.weight": [49408, 768],
    })
    (picture_folder / image_switches.MOTION_FOLDER).mkdir()
    (picture_folder / image_switches.MOTION_FOLDER / "mm.safetensors").write_bytes(b"mm")
    return picture_folder


def test_a_video_of_a_checkpoint_needs_its_motion_module(
    client: TestClient, sd15_folder: Path, monkeypatch
):
    seen: dict = {}

    def _draw(self, job, target):
        seen["job"] = job
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"webm")
        return target

    monkeypatch.setattr(Bildrunner, "programm", property(lambda self: Path("/fake/sd-cli")))
    monkeypatch.setattr(Bildrunner, "erzeugen", _draw)
    refused = client.post("/api/v1/bild", json={"prompt": "x", "modell": "sd15.safetensors",
                                                "video": True})
    assert refused.status_code == 400
    assert "job" not in seen
    drawn = client.post("/api/v1/bild", json={
        "prompt": "x", "modell": "sd15.safetensors", "video": True,
        "switches": {"motion_module": "mm.safetensors"},
    })
    assert drawn.status_code == 201, drawn.text
    assert seen["job"].video is True
    assert seen["job"].switch_paths["motion_module"].name == "mm.safetensors"
