"""Value validation for the drawing request (`app/bildwahlen.py`)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app import bildwahlen
from app.bildwahlen import live_preview_pruefen

WURZEL = Path(__file__).resolve().parent.parent


def test_turbo_hand_start_baut_das_gespann_ueber_dieselben_pruefungen():
    """J4: the hand switch (`POST /bild/turbo/start`) omitted `rng`,
    `weight_type`, `threads` and `vram_limit` entirely, leaning on
    `Bildturbo.starten()`'s own Python-level defaults — the SAME neutral
    Gespann the draw path also starts on today, but built by a second,
    independent route. Two places defining "unset" agree only until one
    of them changes alone. The memory and devices come from the one
    setting every picture reads (app/bildgeraete.py).

    Source-text only, matching the fix's own nature: nothing here is
    observable in the started process's argv, since the values resolve
    to the same defaults either way — what changed is that both paths
    now ask the same `bildwahlen` functions instead of one of them
    trusting a function signature to keep matching the other."""
    quelle = (WURZEL / "app/api/v1/bild.py").read_text()
    funktion = re.search(r"def turbo_starten\(.*?\n\n\n", quelle, re.S)
    assert funktion, "turbo_starten not found"
    rumpf = funktion.group(0)
    for aufruf in (
        # The start values come from one function (app/image_start_values.py),
        # which asks the `bildwahlen` validators itself (checked below).
        r"image_start_values\.lesen\(",
        r"rng=anfang\.rng",
        r"weight_type=anfang\.weight_type",
        r"vae_format=anfang\.vae_format",
        r"geraete = bildgeraete\.lesen\(repositories\)",
        r"threads=geraete\.threads",
        r"vram_limit=geraete\.vram_limit",
        r"split_mode=geraete\.split_mode",
        r"backend=geraete\.backend",
        # The start flags that arrived with the refinement fields. Unlike
        # the six above, the upscaler folder is not merely a tidiness
        # question: `passt_zu()` compares it, so a hand start that leaves
        # it unset makes the very next picture -- even one with no
        # upscaler and no highres at all -- look like a different Gespann
        # and pay a full model reload.
        r"upscaler_ordner=_upscaler_ordner\(",
        r"ad_negativ=",
        r"ad_confidence=",
        r"prediction=anfang\.prediction",
    ):
        assert re.search(aufruf, rumpf), (
            f"turbo_starten builds the pair again without {aufruf!r} -- "
            "two ways for the same thing"
        )
    start_values = (WURZEL / "app/image_start_values.py").read_text()
    for aufruf in (
        r"bildwahlen\.rng_pruefen\(",
        r"bildwahlen\.weight_type_pruefen\(",
        r"bildwahlen\.vae_format_pruefen\(",
        r"bildwahlen\.prediction_pruefen\(",
    ):
        assert re.search(aufruf, start_values), f"the start values skip {aufruf!r}"


def test_upscaler_ordner_kommt_aus_einer_einzigen_quelle():
    """The folder `passt_zu()` compares must be resolved in exactly ONE
    place. It was resolved inline in the draw path while the hand switch
    did not resolve it at all, which is the shape of the bug this guards:
    the two disagreed, and the disagreement cost a full model reload on
    the first picture after a hand start.

    Only the two GESPANN paths are guarded here. `bildmodelle()` builds
    the same name a third time on purpose -- that one is the path the
    window's path row shows, and it has to name the folder even before it
    exists, exactly like lora_ordner/vae_ordner beside it."""
    quelle = (WURZEL / "app/api/v1/bild.py").read_text()
    assert re.search(r"def _upscaler_ordner\(", quelle), (
        "the shared helper _upscaler_ordner() is missing"
    )
    for name in ("turbo_starten", "bild_erzeugen"):
        treffer = re.search(rf"def {name}\(.*?\n\n\n", quelle, re.S)
        assert treffer, f"{name} not found"
        rumpf = treffer.group(0)
        assert "/ UPSCALER_ORDNER" not in rumpf, (
            f"{name} resolves the upscaler folder itself again -- "
            "two ways for the same thing, and passt_zu() compares it"
        )
        assert "_upscaler_ordner(config)" in rumpf, (
            f"{name} no longer passes the upscaler folder through -- "
            "the next start by hand pays for a restart again"
        )


@pytest.mark.parametrize("roh, erwartet", [
    ("proj", "proj"), ("tae", "tae"), ("vae", "vae"),
    ("none", ""),  # sd-cli's own word for "off" is not one of ours
    ("nonsense", ""), (None, ""), ("", ""),
])
def test_live_preview_pruefen_kennt_nur_die_drei_methoden(roh, erwartet):
    """`--preview` takes [none, proj, tae, vae] -- this
    window offers "off" as the empty string (same shape as every other
    off-by-default field here), not sd-cli's own word for it."""
    assert live_preview_pruefen(roh) == erwartet


def test_die_anfrage_liest_live_preview_ueber_die_pruefung():
    quelle = (WURZEL / "app/api/v1/bild.py").read_text()
    assert re.search(
        r"live_preview=bildwahlen\.live_preview_pruefen\(wunsch\.live_preview\)", quelle
    ), "the request does not read live_preview through bildwahlen.live_preview_pruefen"


def test_kein_sampler_bleibt_leer():
    """Unset or empty is "no switch": sd.cpp picks the model's own sampler.
    A known one stays; an unknown name keeps the program's own as before."""
    assert bildwahlen.sampler_pruefen(None) == ""
    assert bildwahlen.sampler_pruefen("") == ""
    assert bildwahlen.sampler_pruefen("dpm++2m") == "dpm++2m"
    assert bildwahlen.sampler_pruefen("quatsch") == bildwahlen.SAMPLER_VORGABE
