"""The values each picture model starts with, set once by the user.

A family's start values (app/image_families.py) fit the family, not every
model in it: a finetune wants other steps and another CFG, a model trained
on its own tags wants them in every prompt. So each model file can carry its
own: the measures, steps, CFG, guidance, flow shift, sampler and scheduler,
what belongs to the model itself — CLIP skip, prediction type, its trigger
words and a note — and its kit: the VAE and the companion files a kit
family assembles the model from. One place per model, the way InvokeAI keeps
``default_settings`` on the model record; the parts belong to the model and
not to a single picture, so every chat draws the model with the same ones.

Stored as one setting, keyed by the model's file name. A value that is not
set (None) is not the model's own: there the family's start value holds. A
model whose entry is None or missing has no values of its own at all — that
is what "reset" writes.

Read by ``/bild/vorgaben`` (app/api/v1/bild.py): what the picture window
opens a model on, and what ``draw_image`` draws with outside a chat.
"""

from __future__ import annotations

import math
from typing import Any

from app.bildfensterwahl import CFG_MIN, PROMPT_HOECHSTLAENGE
from app.bildwahlen import (
    PREDICTION_WERTE,
    SAMPLER,
    SCHEDULER,
    kante_pruefen,
    schritte_pruefen,
)

SCHLUESSEL = "bildmodellwerte"

# The deepest a CLIP skip can reach: the largest CLIP text encoder any
# family reads, OpenCLIP-H with its 24 layers (app/image_families.py,
# ``clip_layers``). The window offers no more than the model's own family
# has; this is only the outer fence of what is stored.
CLIP_SKIP_MAX = 24

# What a model's file name may be to stand as a key: a name in the picture
# folder, never a path.
NAME_MAX = 255

# The values that replace a family start value, by the name the picture
# window and ``/bild/vorgaben`` give them.
MASSFELDER = (
    "breite", "hoehe", "schritte", "cfg", "guidance", "flow_shift",
    "sampler", "scheduler",
)
# What belongs to the model itself and has no family value: empty is "Auto".
MODELLFELDER = ("clip_skip", "prediction", "trigger", "hinweis")
# The model's kit, each part by the name the draw route takes it under and
# held as a file name in its own folder; unset is the part the folder offers
# for the family by itself (app/api/v1/bild.py ``_model_kit``).
BAUSATZFELDER = (
    "vae", "t5xxl", "clip_l", "clip_g", "llm", "llm_vision", "tokenizer",
    "uncond_diffusion_model", "high_noise_diffusion_model",
    "audio_vae", "audio_encoder", "embeddings_connectors",
)
# Whether the model's family is read from its own file. A switch and no
# value: it is on unless the user switched it off for this model, so only
# "off" is ever something the model holds. Off, no family decides about the
# model's kit: every part can be given, and exactly the given ones are sent.
FAMILY_DETECTION = "family_detection"
# The diffusion model such a model is drawn with, a file of the model
# folder (``--diffusion-model``). Unset, the model's own file goes to sd.cpp
# as ``-m``, the way a model without a family does: a whole checkpoint
# nobody recognises still loads. Read only while the family is not.
DIFFUSION_MODEL = "diffusion_model"


def _zahl(wert: Any) -> float | None:
    if isinstance(wert, bool) or not isinstance(wert, (int, float)):
        return None
    try:
        return float(wert) if math.isfinite(wert) else None
    except OverflowError:
        return None


def _dateiname(wert: Any) -> str | None:
    """A file name in one of the picture folders, or None."""
    if not isinstance(wert, str) or len(wert) > NAME_MAX:
        return None
    if "/" in wert or "\\" in wert or wert in (".", ".."):
        return None
    return wert


def _feld(name: str, wert: Any) -> Any:
    """One field as it is kept, or None — unset, the family's value holds."""
    if wert is None:
        return None
    if name == FAMILY_DETECTION:
        return wert if isinstance(wert, bool) else None
    # A switch is no number here, though Python counts True as one.
    if isinstance(wert, bool):
        return None
    if name in ("breite", "hoehe"):
        return kante_pruefen(wert)
    if name == "schritte":
        return schritte_pruefen(wert)
    if name == "cfg":
        zahl = _zahl(wert)
        return None if zahl is None else max(float(CFG_MIN), zahl)
    if name == "guidance":
        # No upper limit, like the CFG: sd.cpp sets none.
        zahl = _zahl(wert)
        return None if zahl is None else max(0.0, zahl)
    if name == "flow_shift":
        return _zahl(wert)
    if name == "sampler":
        return wert if wert in SAMPLER else None
    if name == "scheduler":
        return wert if wert == "" or wert in SCHEDULER else None
    if name in BAUSATZFELDER or name == DIFFUSION_MODEL:
        return _dateiname(wert)
    if name == "clip_skip":
        zahl = _zahl(wert)
        return int(zahl) if zahl is not None and 1 <= zahl <= CLIP_SKIP_MAX else None
    if name == "prediction":
        return wert if wert == "" or wert in PREDICTION_WERTE else None
    if name in ("trigger", "hinweis"):
        return wert[:PROMPT_HOECHSTLAENGE] if isinstance(wert, str) else None
    return None


def pruefen(wert: Any) -> dict[str, Any]:
    """The settings check: every model by its file name, each with only the
    fields it knows; a model sent as None loses its own values."""
    if not isinstance(wert, dict):
        return {}
    sauber: dict[str, Any] = {}
    for modell, felder in wert.items():
        if _dateiname(modell) is None or not modell:
            continue
        if felder is None:
            sauber[modell] = None
            continue
        if not isinstance(felder, dict):
            continue
        sauber[modell] = {
            name: _feld(name, felder[name])
            for name in (
                *MASSFELDER, *MODELLFELDER, *BAUSATZFELDER, FAMILY_DETECTION, DIFFUSION_MODEL,
            )
            if name in felder
        }
    return sauber


def eigene(repositories, modell: str) -> dict[str, Any]:
    """The values this model sets itself — only the set ones. The switch
    for reading its family is no value and is asked for on its own
    (``family_detection``)."""
    stand = repositories.einstellungen.zusammengefuehrt(SCHLUESSEL, vorgabe={})
    felder = stand.get(modell) if isinstance(stand, dict) else None
    if not isinstance(felder, dict):
        return {}
    return {
        name: wert for name, wert in pruefen({modell: felder})[modell].items()
        if wert is not None and name != FAMILY_DETECTION
    }


def without_family_detection(repositories) -> set[str]:
    """The models whose family is not read from their file: the ones the
    user switched it off for. Read in one go, for whoever lists a folder."""
    stand = repositories.einstellungen.zusammengefuehrt(SCHLUESSEL, vorgabe={})
    if not isinstance(stand, dict):
        return set()
    return {
        modell for modell, felder in pruefen(stand).items()
        if isinstance(felder, dict) and felder.get(FAMILY_DETECTION) is False
    }


def family_detection(repositories, modell: str) -> bool:
    """Whether this model's family is read from its file — on for every
    model that has not been switched off."""
    return modell not in without_family_detection(repositories)


def set_part(repositories, modell: str, field: str, datei: str, *, keep_own: bool = False) -> None:
    """Ties one kit part to a model under its field (``vae``, ``llm``, …).
    Written the way the settings page writes a model's values, so a name that
    is no file name is dropped and the model's other values stay as they
    were. With ``keep_own`` a part the model already carries stays: a kit
    part that was lying there all along does not replace a choice made by
    hand."""
    from app.db.repositories.einstellungen import GLOBAL

    if field not in BAUSATZFELDER:
        return
    if keep_own and eigene(repositories, modell).get(field):
        return
    repositories.einstellungen.zusammenlegen(
        GLOBAL, SCHLUESSEL, {modell: {field: datei}}, pruefen=pruefen
    )
