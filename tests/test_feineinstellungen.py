"""The advanced section's levers, and the command line they turn into."""

from __future__ import annotations

import pytest

from app.feineinstellungen import (
    FA_VORGABE,
    KV_VORGABE,
    MAX_FAEDEN,
    MAX_PARALLEL,
    Feineinstellungen,
    flags,
)


def test_vorgaben_sagen_nichts():
    """A command with nothing set looks as it did before the section existed."""
    assert flags(Feineinstellungen()) == []
    assert flags(None) == []


def test_kv_cache_setzt_beide_haelften():
    zeile = flags(Feineinstellungen(kv_cache="q8_0"))
    assert zeile == ["--cache-type-k", "q8_0", "--cache-type-v", "q8_0"]


def test_kv_cache_vorgabe_bleibt_stumm():
    assert flags(Feineinstellungen(kv_cache=KV_VORGABE)) == []


def test_flash_attention_nur_wenn_abweichend():
    assert flags(Feineinstellungen(flash_attention=FA_VORGABE)) == []
    assert flags(Feineinstellungen(flash_attention="on")) == ["--flash-attn", "on"]
    assert flags(Feineinstellungen(flash_attention="off")) == ["--flash-attn", "off"]


def test_faeden():
    assert flags(Feineinstellungen(faeden=8)) == ["--threads", "8"]
    assert flags(Feineinstellungen(faeden=None)) == []


def test_moe_ohne_zahl_nimmt_alles():
    assert flags(Feineinstellungen(moe_auf_cpu=True)) == ["--cpu-moe"]


def test_moe_mit_zahl_nimmt_die_ersten_schichten():
    zeile = flags(Feineinstellungen(moe_auf_cpu=True, moe_schichten=12))
    assert zeile == ["--n-cpu-moe", "12"]


def test_moe_zahl_ohne_schalter_bleibt_stumm():
    assert flags(Feineinstellungen(moe_schichten=12)) == []


def test_festnageln_nutzt_die_nicht_veraltete_form():
    """`--mlock` is deprecated in the shipped build; this is its replacement."""
    assert flags(Feineinstellungen(festnageln=True)) == ["--load-mode", "mmap+mlock"]


def test_parallel_gesetzt_wird_gesagt():
    assert flags(Feineinstellungen(parallel=4)) == ["--parallel", "4", "--kv-unified"]


def test_parallel_ungesetzt_bleibt_stumm():
    """The silent half: whoever sets nothing keeps the engine's own "auto" —
    the exact command every start produced before this lever existed."""
    assert flags(Feineinstellungen(parallel=None)) == []
    assert "--parallel" not in flags(Feineinstellungen())


def test_alles_zusammen_bleibt_lesbar():
    zeile = flags(Feineinstellungen(
        kv_cache="q8_0", flash_attention="on", faeden=6,
        moe_auf_cpu=True, moe_schichten=4, festnageln=True, parallel=2,
    ))
    assert zeile == [
        "--cache-type-k", "q8_0", "--cache-type-v", "q8_0",
        "--flash-attn", "on",
        "--threads", "6",
        "--n-cpu-moe", "4",
        "--load-mode", "mmap+mlock",
        "--parallel", "2", "--kv-unified",
    ]


# --- What arrives from the window ------------------------------------------


def test_unbekannter_cache_faellt_auf_die_vorgabe():
    """A name that is not a name must never reach the command line."""
    e = Feineinstellungen.aus_daten({"kv_cache": "q1_unfug"})
    assert e.kv_cache == KV_VORGABE
    assert flags(e) == []


def test_unbekannte_flash_wahl_faellt_zurueck():
    assert Feineinstellungen.aus_daten({"flash_attention": "vielleicht"}).flash_attention == FA_VORGABE


@pytest.mark.parametrize("roh,erwartet", [(0, None), ("", None), (None, None), (-3, 1), (99999, MAX_FAEDEN)])
def test_faeden_werden_in_den_bereich_geholt(roh, erwartet):
    assert Feineinstellungen.aus_daten({"faeden": roh}).faeden == erwartet


@pytest.mark.parametrize(
    "roh,erwartet",
    [(0, None), ("", None), (None, None), (-3, 1), (99999, MAX_PARALLEL), ("vier", None)],
)
def test_parallel_wird_in_den_bereich_geholt(roh, erwartet):
    """0 and empty mean "auto" and stay off the command line entirely."""
    assert Feineinstellungen.aus_daten({"parallel": roh}).parallel == erwartet


def test_kaputte_zahlen_werden_zu_nichts():
    e = Feineinstellungen.aus_daten({"faeden": "acht", "moe_schichten": "viele"})
    assert e.faeden is None
    assert e.moe_schichten is None


def test_leere_daten_sind_die_vorgaben():
    assert Feineinstellungen.aus_daten(None).als_daten() == Feineinstellungen().als_daten()


def test_hin_und_zurueck():
    e = Feineinstellungen(kv_cache="q8_0", faeden=4,
                          moe_auf_cpu=True, moe_schichten=2, festnageln=True,
                          parallel=3)
    assert Feineinstellungen.aus_daten(e.als_daten()).als_daten() == e.als_daten()


def test_flash_attention_takes_auto_on_and_off_and_nothing_else():
    for wert in ("auto", "on", "off"):
        assert Feineinstellungen.aus_daten({"flash_attention": wert}).flash_attention == wert
    assert Feineinstellungen.aus_daten({"flash_attention": "erfunden"}).flash_attention == "auto"


def test_flash_off_with_a_smaller_cache_becomes_auto():
    """A quantized cache needs flash attention: the pair that cannot run is
    brought back to a pair that can, never passed to the engine."""
    for kv in ("q8_0", "q5_0", "q4_0"):
        e = Feineinstellungen.aus_daten({"kv_cache": kv, "flash_attention": "off"})
        assert (e.kv_cache, e.flash_attention) == (kv, "auto")
    # With the 16-bit cache "off" stands, and "on" stands with any cache.
    assert Feineinstellungen.aus_daten({"flash_attention": "off"}).flash_attention == "off"
    assert Feineinstellungen.aus_daten({"kv_cache": "q4_0", "flash_attention": "on"}).flash_attention == "on"


def test_all_four_cache_stages_stay_as_stored():
    """A stored q4_0 is 4 bit now — no step is mapped onto another."""
    for kv in ("f16", "q8_0", "q5_0", "q4_0"):
        assert Feineinstellungen.aus_daten({"kv_cache": kv}).kv_cache == kv
