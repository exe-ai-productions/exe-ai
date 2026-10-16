"""What the picture studio was left standing at.

Its own module for the same reason the sound switch has one: the settings
route only writes what somebody vouches for, and a JSON column cannot vouch
for anything by itself.

Kept ONCE, for the studio, in the global scope — and all of it: every value
of the four tabs — General, Model & components, Face & reference,
Refinement — the style addition, the pictures the studio was given (start
picture, PuLID photo, ControlNet guide) and the mask with its start
picture. The studio belongs to no chat: opening, switching or deleting a
chat changes none of it, and no chat reads it. (Chats that stored a window
of their own before the studio stood apart keep it, unread.)

What is NOT in here, on purpose:

"Memory & devices" — the VRAM budget, offloading, threads, split and
backend, and every further switch of the memory block or marked
``machine`` in app/image_switches.py — and the model's kit
    Those describe the machine the pictures are drawn on and the model,
    the same for every conversation: the picture server keeps them
    (app/bildgeraete.py, app/bildmodellwerte.py).

``breite``, ``hoehe``, ``schritte``, ``sampler`` and ``scheduler`` are here
too: the studio stands as it was left, and only a value it never set starts
from its family's start values (``app/image_families.py``).

The pictures and the mask travel by the NAME the picture route gave them
(``app/api/v1/bilder.py``); the files stay in the pictures folder. A mask
only ever counts together with its start picture, so one stored without a
start picture is dropped.

The prompt limit is the route's own (``app/api/v1/bild.py``): a stored
prompt that the draw route would refuse is worse than no stored prompt,
because it fails at drawing time and looks like the picture is broken
rather than the setting.
"""

from __future__ import annotations

import math
import re
from typing import Any

from app import bildgeraete, image_switches
from app.bildwahlen import (
    LORA_APPLY_MODE_VORGABE, SAMPLER, SCHEDULER, kante_pruefen, schritte_pruefen,
)

SCHLUESSEL = "bildfenster"

# The longest name or short text a field keeps. The prompt and the
# negative have no limit, as the draw route and sd.cpp set none.
PROMPT_HOECHSTLAENGE = 2000

# The seed plan for a series: pick fresh, hold one, or walk up/down from the
# last drawn seed (frontend lib/studiozeichnen.svelte.js).
SEED_MODI = ("zufall", "fest", "plus", "minus")

# sd.cpp's third way to apply a LoRA, which the studio does not offer: it
# merges the LoRA into the weights before the first step.
LORA_MODE_NO_LONGER_OFFERED = "immediately"

# sd.cpp sets no upper limit on the CFG nor on how many pictures are drawn.
CFG_MIN = 0
BILDER_MIN = 1

# The values of the picture studio, by the kind of value it holds them as
# (frontend lib/studio.svelte.js `ANFANG`): every field it can store, and no
# other. The studio checks each field itself; this only makes sure a stored
# value is of a shape the studio can take back. A value it does not store
# is the start value of its model, never one built in here.
#
# PROMPT  a string of any length — the prompt and the negative
# CFG     a number, never negative, kept as the fraction it was set as
# COUNT   how many pictures a run draws: a whole number, at least one
# SEED    digits, or the empty text for "let the generator pick"
# SEED_PLAN  one of the seed plans (``SEED_MODI``)
# TEXT    a string — names, free switches
# WERT    a string or a number — a choice, or a number field whose empty
#         state is ''
# SCHALTER  a yes or no
# STAPEL  a LoRA stack: a list of {name, staerke}
# BILD    a picture the picture route stored, by the name it gave it
# BILDER  a list of such pictures, in order
# EINBETTUNG  a PuLID face embedding's file name (.pulidembd)
# MASSE   the five starting values of the model's class — checked by the
#         same limits the draw route uses (``_check_measures``)
# SWITCH_VALUES  sd.cpp's further switches (app/image_switches.py) by key;
#         each value checked against its row, the machine's own left out
TEXT, WERT, SCHALTER, STAPEL, BILD, BILDER, MASSE, EINBETTUNG, SWITCH_VALUES = (
    "text", "wert", "schalter", "stapel", "bild", "bilder", "masse", "einbettung",
    "switch_values",
)
PROMPT, CFG, COUNT, SEED, SEED_PLAN = "prompt", "cfg", "count", "seed", "seed_plan"

FELDER: dict[str, str] = {
    # The prompt bar and the run
    "prompt": PROMPT,
    "negativ": PROMPT,
    "cfg": CFG,
    "bilder_je_lauf": COUNT,
    "seed": SEED,
    "seed_modus": SEED_PLAN,
    # General
    # The style the chat draws through, by its id (app/bildstile.py)
    "stil": TEXT,
    "breite": MASSE,
    "hoehe": MASSE,
    "schritte": MASSE,
    "sampler": MASSE,
    "scheduler": MASSE,
    "stapel": STAPEL,
    "lora_modus": TEXT,
    # Model (the kit — VAE, diffusion model, encoders, further parts — and
    # the memory and devices are the picture server's, not a chat's)
    "modell": TEXT,
    "vae_format": TEXT,
    "clip_skip": WERT,
    "rng": TEXT,
    "weight_type": TEXT,
    "prediction": TEXT,
    "familie": TEXT,
    "guidance": WERT,
    "model_args": TEXT,
    # A video's frames and rate, and the last frame it is drawn towards
    "video_frames": WERT,
    "fps": WERT,
    "end_bild": BILD,
    # Editing with reference images
    "ref_bilder": BILDER,
    "img_cfg": WERT,
    "ref_image_args": TEXT,
    "increase_ref_index": SCHALTER,
    # Face & reference
    "startbild": BILD,
    # The picture that last came from outside — kept on top of the row
    "original": BILD,
    "staerke": WERT,
    "maske": BILD,
    "pm_klasse": TEXT,
    "ad_modell": TEXT,
    "ad_stapel": STAPEL,
    "ad_prompt": TEXT,
    "ad_negativ": TEXT,
    "ad_confidence": WERT,
    "pulid_weights": TEXT,
    # A finished .pulidembd in the PuLID folder, by its file name.
    "pulid_id_embedding": EINBETTUNG,
    "pulid_id_weight": WERT,
    "control_net": TEXT,
    "control_image": BILD,
    "control_strength": WERT,
    "canny": SCHALTER,
    # Refinement
    "hires_wahl": WERT,
    "hires_steps": WERT,
    "hires_denoise": WERT,
    "hires_upscaler": TEXT,
    # The file "Upscale" enlarges a finished picture with; it travels with that
    # wish only, not with a drawing.
    "upscale_model": TEXT,
    "hires_breite": WERT,
    "hires_hoehe": WERT,
    "slg_scale": WERT,
    "skip_layers": TEXT,
    "skip_layer_start": WERT,
    "skip_layer_end": WERT,
    "live_preview": WERT,
    "preview_interval": WERT,
    "preview_noisy": SCHALTER,
    "taesd": TEXT,
    "eta": WERT,
    "flow_shift": WERT,
    "sigmas": TEXT,
    "extra_sample_args": TEXT,
    "switches": SWITCH_VALUES,
}


# The name the picture route gives an upload: 32 hex digits and the type's
# own ending (app/api/v1/bilder.py ``ERLAUBTE_TYPEN`` — written out here
# because that module's package imports this one; a test holds the two
# together). Nothing else is a stored picture, and a name that is anything
# else would travel into a picture address as it is.
BILDENDUNGEN = (".png", ".jpg", ".webp")
BILDNAME = re.compile(
    r"[0-9a-f]{32}(?:" + "|".join(re.escape(e) for e in BILDENDUNGEN) + r")"
)


def _endliche_zahl(wert: Any) -> bool:
    if isinstance(wert, bool) or not isinstance(wert, (int, float)):
        return False
    try:
        return math.isfinite(wert)
    except OverflowError:
        # An integer too large for a float is no value any field can take.
        return False


def _feld_pruefen(art: str, wert: Any) -> tuple[bool, Any]:
    """Whether a value fits its kind, and the value as it is kept. A name
    or short text is cut at the longest a field keeps; a prompt is kept
    whole."""
    if art == PROMPT:
        if isinstance(wert, str):
            return True, wert
    elif art == CFG:
        # A fraction for sd-cli (Flux starts at 1, and 3.5 is a common
        # choice): stored as it was set, never rounded, never negative.
        if _endliche_zahl(wert):
            return True, max(float(CFG_MIN), float(wert))
    elif art == COUNT:
        if _endliche_zahl(wert):
            return True, max(BILDER_MIN, int(round(wert)))
    elif art == SEED:
        # Digits or nothing. The field is text, but only a whole number
        # ever reaches the generator — anything else would be silently
        # ignored there and look like the seed had been taken. Empty is kept
        # as text, not as -1: an empty field says "whatever" more clearly
        # than a magic number.
        if isinstance(wert, str) and (wert == "" or wert.isdigit()):
            return True, wert
    elif art == SEED_PLAN:
        if wert in SEED_MODI:
            return True, wert
    elif art == TEXT:
        if isinstance(wert, str):
            return True, wert[:PROMPT_HOECHSTLAENGE]
    elif art == WERT:
        if isinstance(wert, str):
            return True, wert[:PROMPT_HOECHSTLAENGE]
        if _endliche_zahl(wert):
            return True, wert
    elif art == BILD:
        if isinstance(wert, str) and (wert == "" or BILDNAME.fullmatch(wert)):
            return True, wert
    elif art == EINBETTUNG:
        # What the old picture drop stored here (a photo) is no embedding.
        if isinstance(wert, str) and (wert == "" or wert.endswith(".pulidembd")):
            return True, wert[:PROMPT_HOECHSTLAENGE]
    elif art == BILDER:
        if isinstance(wert, list):
            return True, [
                bild for bild in wert if isinstance(bild, str) and BILDNAME.fullmatch(bild)
            ]
    elif art == SCHALTER:
        if isinstance(wert, bool):
            return True, wert
    elif art == SWITCH_VALUES:
        if isinstance(wert, dict):
            return True, _switch_values(wert)
    elif art == STAPEL:
        if isinstance(wert, list):
            return True, [
                {"name": e["name"][:PROMPT_HOECHSTLAENGE], "staerke": e["staerke"]}
                for e in wert
                if isinstance(e, dict)
                and isinstance(e.get("name"), str)
                and _endliche_zahl(e.get("staerke"))
            ]
    return False, None


def held_pictures(stored: Any) -> set[str]:
    """The pictures a stored window holds, by the names the picture
    route gave them: every field that keeps a picture or a list of them —
    the start and end picture, the mask, the reference pictures, the guide
    picture — and the pictures its further switches name. Anything that is
    no stored picture's name holds nothing."""
    if not isinstance(stored, dict):
        return set()
    named: list[Any] = []
    for field, kind in FELDER.items():
        value = stored.get(field)
        if kind == BILD:
            named.append(value)
        elif kind == BILDER and isinstance(value, list):
            named.extend(value)
    switches = stored.get("switches")
    if isinstance(switches, dict):
        named.extend(
            value for key, value in switches.items()
            if isinstance(key, str)
            and (switch := image_switches.get(key)) is not None and switch.kind == "picture"
        )
    return {name for name in named if isinstance(name, str) and BILDNAME.fullmatch(name)}


def _switch_values(values: dict) -> dict[str, Any]:
    """The further switches worth keeping: a known key, not the machine's
    nor the memory block's, with a value its row takes. A stale or broken
    one is dropped alone."""
    kept: dict[str, Any] = {}
    for key, value in values.items():
        switch = image_switches.get(key) if isinstance(key, str) else None
        if switch is None or switch.machine or switch.group == bildgeraete.GRUPPE:
            continue
        try:
            kept.update(image_switches.check({key: value}))
        except ValueError:
            continue
    return kept


def wahl_pruefen(wert: Any) -> dict[str, Any] | None:
    """Keeps what is usable, drops the rest. ``None`` deletes the entry."""
    if not isinstance(wert, dict):
        return None
    sauber: dict[str, Any] = {}

    for name, art in FELDER.items():
        if name in wert and art != MASSE:
            passt, gehalten = _feld_pruefen(art, wert[name])
            if passt:
                sauber[name] = gehalten
    # The studio offers two ways to apply a LoRA. A chat left at the third,
    # which it no longer offers, stands at the one it starts with.
    if sauber.get("lora_modus") == LORA_MODE_NO_LONGER_OFFERED:
        sauber["lora_modus"] = LORA_APPLY_MODE_VORGABE
    # Numbers that are no finite number (an infinity, a NaN) never reach
    # the class rules, which would fail on them rather than drop them.
    sauber.update(
        _check_measures({
            name: wert[name]
            for name, art in FELDER.items()
            if art == MASSE
            and name in wert
            and (isinstance(wert[name], str) or _endliche_zahl(wert[name]))
        })
    )

    # The mask belongs to its start picture and means nothing without it.
    if not sauber.get("startbild"):
        sauber.pop("maske", None)

    return sauber or None


def _check_measures(values: dict[str, Any]) -> dict[str, Any]:
    """The five measures, checked against the limits the draw route uses
    (``app/bildwahlen.py``): a stored value the generator would refuse is
    worse than none, because it fails at drawing time. The empty sampler or
    scheduler is a real answer — "whatever the model brings"."""
    checked: dict[str, Any] = {}
    for edge in ("breite", "hoehe"):
        if edge in values:
            number = kante_pruefen(values[edge])
            if number is not None:
                checked[edge] = number
    if "schritte" in values:
        number = schritte_pruefen(values["schritte"])
        if number is not None:
            checked["schritte"] = number
    for name, allowed in (("sampler", SAMPLER), ("scheduler", SCHEDULER)):
        if name in values:
            text = values[name]
            if text == "" or text in allowed:
                checked[name] = text
    return checked
