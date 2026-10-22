"""The machine's start values of flash attention and batched CFG, and the old on/off keys.

Build 975 reads ``--flash-attn`` as ``auto``, ``on``, ``off`` or one value per
part. The generator was always started with flash attention in the diffusion
model only (the flag ``--diffusion-fa``, fixed in the command line before);
that stays what a machine starts with while nothing is stored, now as the
value ``off,diffusion=on`` of the switch, so it can be seen in the memory
block and changed there — to ``auto`` as well. A layout stored with the three
on/off switches of the earlier build keeps what they said.

Build 975 also computes the picture and its negative in one pass for models
built on a UNet (SD 1.5, SDXL) unless ``--batched-cfg off`` says otherwise;
on Metal that pass draws a plain white picture whenever CFG is above 1. A
machine therefore starts with the switch off, and a stored value wins.
"""

from __future__ import annotations

from app import bildgeraete, image_switches


class _Einstellungen:
    def __init__(self, stand):
        self._stand = stand

    def zusammengefuehrt(self, schluessel, vorgabe):
        return self._stand


class _Repositories:
    def __init__(self, stand):
        self.einstellungen = _Einstellungen(stand)


def _lesen(stand):
    return bildgeraete.lesen(_Repositories(stand)).switches


START = {"flash_attn": "off,diffusion=on", "batched_cfg": "off"}


def test_nothing_stored_starts_with_flash_attention_in_the_diffusion_model_only_and_batched_cfg_off():
    assert _lesen({}) == START
    assert bildgeraete.START_SWITCHES == START


def test_a_stored_value_wins_and_auto_is_a_value_of_its_own():
    assert _lesen({"switches": {"flash_attn": "auto"}}) == {"flash_attn": "auto", "batched_cfg": "off"}
    assert _lesen({"switches": {"flash_attn": "on", "sage_attn": True}}) == {
        "flash_attn": "on", "sage_attn": True, "batched_cfg": "off",
    }
    # Other stored switches do not take the start values away.
    assert _lesen({"switches": {"mmap": True}}) == {**START, "mmap": True}


def test_a_stored_batched_cfg_wins_whatever_it_says():
    assert _lesen({"switches": {"batched_cfg": "on"}}) == {"flash_attn": "off,diffusion=on", "batched_cfg": "on"}
    assert _lesen({"switches": {"batched_cfg": "off"}}) == START


def _command(stand) -> list[str]:
    return image_switches.cli_parts(_lesen(stand), {})


def test_sd_cli_and_the_picture_server_both_start_with_batched_cfg_off():
    values = _lesen({})
    assert image_switches.cli_parts(values, {})[-2:] == ["--batched-cfg", "off"]
    assert "--flash-attn" in image_switches.cli_parts(values, {})
    start = image_switches.server_start_parts(values, {})
    assert start[start.index("--batched-cfg") + 1] == "off"
    assert start.count("--batched-cfg") == 1


def test_silence_a_stored_on_sends_one_batched_cfg_on_and_no_second_off():
    for parts in (_command({"switches": {"batched_cfg": "on"}}),
                  list(image_switches.server_start_parts(_lesen({"switches": {"batched_cfg": "on"}}), {}))):
        assert parts.count("--batched-cfg") == 1
        assert parts[parts.index("--batched-cfg") + 1] == "on"


def test_the_old_on_off_keys_are_read_as_what_they_said():
    assert bildgeraete.switches_pruefen({"fa": True}) == {"flash_attn": "on"}
    assert bildgeraete.switches_pruefen({"diffusion_conv_direct": True}) == {"conv_direct": "diffusion=on,controlnet=on"}
    assert bildgeraete.switches_pruefen({"vae_conv_direct": True}) == {"conv_direct": "vae=on"}
    assert bildgeraete.switches_pruefen({"diffusion_conv_direct": True, "vae_conv_direct": True}) == {
        "conv_direct": "diffusion=on,controlnet=on,vae=on"
    }
    # The old key reaches a start value through the read, and wins over it.
    assert _lesen({"switches": {"fa": True}}) == {"flash_attn": "on", "batched_cfg": "off"}


def test_silence_a_key_in_its_new_name_wins_over_an_old_one_and_a_false_one_says_nothing():
    assert bildgeraete.switches_pruefen({"fa": True, "flash_attn": "auto"}) == {"flash_attn": "auto"}
    assert bildgeraete.switches_pruefen({"fa": False, "vae_conv_direct": False}) == {}
    assert bildgeraete.switches_pruefen({"mmap": True, "made_up": 1}) == {"mmap": True}
