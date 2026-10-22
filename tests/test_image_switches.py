"""The further sd.cpp switches: every one reaches the command line (or the
picture server) with the chosen value, and an unset one sends nothing."""

from __future__ import annotations

from pathlib import Path

import pytest

from app import bildrunner, image_switches
from app.api.v1 import bild as bildapi
from app.bildrunner import Auftrag, Bildrunner

# A value each kind takes, for the probe below.
_SAMPLE = {"bool": True, "int": 3, "float": 0.5, "text": "a=1", "file": "x.bin", "picture": "p.png"}

# Everything a `needs` can ask for, switched on.
_ALL_ON = {"ad_model": True, "photomaker": True, "hires": True}


def _value(switch: image_switches.Switch):
    if switch.kind == "choice":
        return switch.choices[-1]
    if switch.key in ("vae_tile_size", "vae_relative_tile_size"):
        return "256x128"
    if switch.key == "hires_sigmas":
        return "0.8,0.4,0"
    return _SAMPLE[switch.kind]


def _all_values() -> dict:
    values = {switch.key: _value(switch) for switch in image_switches.SWITCHES}
    values.pop("output_format")
    return values


@pytest.fixture
def runner(tmp_path: Path, monkeypatch) -> Bildrunner:
    monkeypatch.setattr(bildrunner.shutil, "which", lambda _: "/somewhere/sd-cli")
    return Bildrunner(tmp_path)


def _befehl(runner: Bildrunner, tmp_path: Path, values: dict, paths: dict | None = None, **extra):
    auftrag = Auftrag(
        modell=tmp_path / "m.gguf", prompt="x", switches=values, switch_paths=paths or {},
        **extra,
    )
    return runner.befehl(auftrag, tmp_path / "a.png")


@pytest.mark.parametrize(
    "switch", [s for s in image_switches.SWITCHES if s.flag], ids=lambda s: s.key,
)
def test_each_switch_carries_its_value(switch, runner, tmp_path):
    value = _value(switch)
    paths = {switch.key: tmp_path / "f"} if switch.kind in ("file", "picture") else {}
    befehl = _befehl(runner, tmp_path, {switch.key: value}, paths)
    assert switch.flag in befehl
    if switch.kind != "bool":
        expected = str(paths.get(switch.key, value))
        assert befehl[befehl.index(switch.flag) + 1] == expected


@pytest.mark.parametrize(
    "switch", [s for s in image_switches.SWITCHES if s.list_flag], ids=lambda s: s.key,
)
def test_each_list_key_rides_in_its_list(switch, runner, tmp_path):
    value = _value(switch)
    extra = {"ad_modell": tmp_path / "yolo.pt"} if switch.list_flag == "--extra-ad-args" else {}
    befehl = _befehl(runner, tmp_path, {switch.key: value}, **extra)
    assert befehl[befehl.index(switch.list_flag) + 1] == f"{switch.arg}={value}"


def test_silence_unset_switches_send_nothing(runner, tmp_path):
    plain = _befehl(runner, tmp_path, {})
    for switch in image_switches.SWITCHES:
        assert not switch.flag or switch.flag not in plain
    assert "--extra-sample-args" not in plain


def test_lists_join_the_window_field_first(runner, tmp_path):
    befehl = _befehl(
        runner, tmp_path, {"sample_gamma": 0.5, "ad_mask_blur": 4},
        extra_sample_args="base_shift=0.5", ad_modell=tmp_path / "y.pt", ad_confidence=0.3,
    )
    assert befehl[befehl.index("--extra-sample-args") + 1] == "base_shift=0.5,gamma=0.5"
    assert befehl[befehl.index("--extra-ad-args") + 1] == "confidence=0.3,mask_blur=4"
    assert befehl.count("--extra-ad-args") == 1


def test_flash_attention_direct_convolution_and_batched_cfg_replace_the_on_off_switches():
    """Build 975 reads flash attention and direct convolution as ``auto``,
    ``on``, ``off`` or one value per part, and takes ``--batched-cfg`` on or
    off; the three on/off switches of the earlier build are gone."""
    flash = image_switches.get("flash_attn")
    conv = image_switches.get("conv_direct")
    batched = image_switches.get("batched_cfg")
    assert (flash.kind, flash.flag, flash.group, flash.machine) == ("text", "--flash-attn", "memory", True)
    assert (conv.kind, conv.flag, conv.group, conv.machine) == ("text", "--conv-direct", "memory", True)
    assert (batched.kind, batched.flag, batched.choices, batched.machine) == (
        "choice", "--batched-cfg", ("on", "off"), True)
    for gone in ("fa", "diffusion_conv_direct", "vae_conv_direct"):
        assert image_switches.get(gone) is None
        with pytest.raises(ValueError):
            image_switches.check({gone: True})
    assert image_switches.check({
        "flash_attn": "auto,te=off,vae=on", "conv_direct": "auto,vae=off", "batched_cfg": "off",
    }) == {"flash_attn": "auto,te=off,vae=on", "conv_direct": "auto,vae=off", "batched_cfg": "off"}
    with pytest.raises(ValueError):
        image_switches.check({"batched_cfg": "maybe"})


def test_the_three_switches_travel_as_one_flag_each_and_an_unset_one_not_at_all():
    values = {"flash_attn": "off,diffusion=on", "conv_direct": "auto,vae=on", "batched_cfg": "on"}
    expected = ["--flash-attn", "off,diffusion=on", "--conv-direct", "auto,vae=on", "--batched-cfg", "on"]
    assert image_switches.cli_parts(values, {}) == expected
    assert list(image_switches.server_start_parts(values, {})) == expected
    # Silence: unset, nothing goes out; every other switch is as it was.
    assert image_switches.cli_parts({}, {}) == []
    assert image_switches.cli_parts({"flash_attn": "auto"}, {}) == ["--flash-attn", "auto"]
    assert image_switches.cli_parts({"sage_attn": True}, {}) == ["--sage-attn"]


def test_check_refuses_what_a_row_does_not_take():
    for wrong in (
        {"made_up": 1}, {"cache_mode": "fast"}, {"compression_quality": 101},
        {"timestep_shift": 2.5}, {"sage_attn": "yes"}, {"linear_scale": float("inf")},
        {"cache_option": "a\nb"}, {"ip_adapter": "../x"}, {"qwen_image_layers": -1},
        {"sample_lms_max_order": float("inf")}, {"sample_guidance_schedule": "1.0x2,0.5x3"},
    ):
        with pytest.raises(ValueError):
            image_switches.check(wrong)
    assert image_switches.check({"sage_attn": False, "cache_mode": "", "mmap": None}) == {}


def test_a_switch_without_what_it_needs_is_dropped():
    values = {"ad_mask_blur": 4, "cache_option": "threshold=0.2", "clip_vision": "c.bin",
              "hires_sigmas": "0.8,0", "pm_style_strength": 20.0, "vae_tile_size": "128"}
    assert image_switches.active(values, {}) == {}
    kept = image_switches.active({**values, "cache_mode": "easycache"}, {"hires": True})
    assert set(kept) == {"cache_option", "cache_mode", "hires_sigmas"}


def test_server_body_and_start_flags():
    values = _all_values()
    paths = {key: Path(f"/f/{key}") for key in values
             if image_switches.get(key).kind in ("file", "picture")}
    auftrag = Auftrag(modell=Path("/m"), prompt="x", hires=True, switches=values,
                      switch_paths=paths, ad_modell=Path("/y.pt"))
    start = bildapi._server_start_switches(auftrag)
    for switch in image_switches.SWITCHES:
        if switch.flag and not switch.body and switch.key in values:
            assert switch.flag in start
        if switch.body and switch.flag:
            assert switch.flag not in start


def test_server_body_fields(tmp_path: Path):
    picture = tmp_path / "p.png"
    picture.write_bytes(b"BILD")
    values = {
        "timestep_shift": 250, "cache_mode": "cache-dit", "cache_option": "Fn=1",
        "scm_mask": "1,0", "scm_policy": "static", "vae_tiling": True,
        "vae_tile_size": "256x128", "vae_tile_overlap": 0.25, "vae_relative_tile_size": "0.5",
        "hires_sigmas": "0.8,0.4,0", "hires_upscale_tile_size": 64, "compression_quality": 80,
        "output_format": "jpg", "qwen_image_layers": 4, "ip_adapter_strength": 0.6,
        "ip_adapter_image": "p.png",
    }
    auftrag = Auftrag(modell=Path("/m"), prompt="x", hires=True, switches=values,
                      switch_paths={"ip_adapter_image": picture})
    body = bildapi._turbo_auftrag(auftrag)
    assert body["sample_params"]["shifted_timestep"] == 250
    assert body["cache_mode"] == "cache-dit"
    assert body["cache_option"] == "Fn=1"
    assert body["scm_mask"] == "1,0"
    assert body["scm_policy_dynamic"] is False
    assert body["vae_tiling_params"] == {
        "enabled": True, "tile_size_w": 256, "tile_size_h": 128, "target_overlap": 0.25,
        "rel_size_w": 0.5, "rel_size_h": 0.5,
    }
    assert body["hires"]["custom_sigmas"] == [0.8, 0.4, 0.0]
    assert body["hires"]["upscale_tile_size"] == 64
    assert body["output_format"] == "jpeg"
    assert body["output_compression"] == 80
    assert body["qwen_image_layers"] == 4
    assert body["ip_adapter_strength"] == 0.6
    assert body["ip_adapter_image"]


def test_silence_server_body_unchanged_without_switches():
    body = bildapi._turbo_auftrag(Auftrag(modell=Path("/m"), prompt="x"))
    assert body["vae_tiling_params"] == {"enabled": False}
    assert body["output_format"] == "png"
    for key in ("cache_mode", "output_compression", "qwen_image_layers", "ip_adapter_image"):
        assert key not in body


def test_a_size_that_is_no_size_goes_to_sd_cli():
    assert image_switches.cli_only({"vae_tile_size": "big"})
    assert image_switches.cli_only({"hires_sigmas": "a,b"})
    assert image_switches.cli_only({"vae_tile_size": "256x128"}) is None


def test_the_sound_of_a_reference_video_is_a_sound_file_for_sd_cli_only():
    switch = image_switches.BY_KEY["ref_video_audio"]
    assert (switch.kind, switch.flag, switch.folder) == (
        "file", "--ref-video-audio", image_switches.AUDIO_FOLDER,
    )
    # The server's body has no field for it: sd-cli draws what carries one.
    assert not switch.body
    assert image_switches.cli_only({"ref_video_audio": "voice.wav"})
    # It acts on a video only, and only beside a reference video.
    values = {"ref_video_audio": "voice.wav"}
    assert image_switches.active(values, {"video": True, "ref_video": True}) == values
    assert image_switches.active(values, {"video": True}) == {}
    assert image_switches.active(values, {"ref_video": True}) == {}


def test_jpeg_names_the_output_file():
    assert image_switches.output_suffix({"output_format": "jpg"}) == ".jpg"
    assert image_switches.output_suffix({}) == ".png"


def test_webp_is_offered_and_names_the_output_file():
    """WebP stands among the output formats, the file ends in .webp, and the
    picture server is asked for it by that name."""
    assert "webp" in image_switches.OUTPUT_FORMATS
    assert image_switches.output_suffix({"output_format": "webp"}) == ".webp"
    assert image_switches.output_suffix({"output_format": "png"}) == ".png"
    assert image_switches.output_suffix({"output_format": "tiff"}) == ".png"
    body: dict = {}
    image_switches.body_fields(body, {"output_format": "webp"}, None)
    assert body["output_format"] == "webp"


def test_every_switch_has_its_texts():
    import json
    root = Path(__file__).resolve().parent.parent / "app/locales"
    for language in ("de", "en"):
        texts = json.loads((root / f"{language}.json").read_text("utf-8"))["bild"]
        for switch in image_switches.SWITCHES:
            assert texts.get(f"sw_{switch.key}"), (language, switch.key)
            assert texts.get(f"info_sw_{switch.key}"), (language, switch.key)


def test_clip_skip_stays_within_the_family():
    assert bildapi._clip_skip("sd15", 20) == 12
    assert bildapi._clip_skip("sd2", 20) == 20
    assert bildapi._clip_skip("sd2", 30) == 24
    assert bildapi._clip_skip("chroma", 2) == -1
    assert bildapi._clip_skip("", 30) == 12
    assert bildapi._clip_skip("sdxl", -1) == -1
