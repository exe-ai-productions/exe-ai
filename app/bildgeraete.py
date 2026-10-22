"""Memory and devices of the picture generator, set once for every chat.

The VRAM budget, moving the weights to RAM, the threads, how a module that
runs on several devices is split, which device runs which module and the
generator's further memory switches start the generator; none of them is a
value of one picture (sd-cli --help: ``--max-vram``, ``--offload-to-cpu``,
``--threads``, ``--split-mode``, ``--backend``). They belong to the machine
the pictures are drawn on, so they are kept once: the server's start by
hand, every picture of every chat and the drawing tool read them here.

Each field takes what the generator takes: ``--max-vram`` one number of GiB
(0 turns the graph splitting off, a negative number keeps that much free)
or one budget per device (``cuda0=6,vulkan0=4``); ``--split-mode`` one mode
or one per module (``diffusion=row,te=layer``); ``--threads`` any count, a
count of 0 or below being the generator's own choice, as if none was given.
The time limit is a whole number of seconds from 1 on, or nothing: a picture
that takes longer is ended after it, and nothing means no limit — it is
stopped by hand. A value the generator would not read is not kept.

The idle time is whole minutes from 1 on, or nothing: after that long without
a picture the program ends the picture server (it has no switch to free its
model by itself), and the next picture starts it again; nothing means never.

The importance matrix is one switch for every model file, on unless it was
turned off: while it is on, every picture drawn with sd-cli adds to the
matrix beside its model file.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from app import image_switches
from app.feineinstellungen import MAX_IDLE_MINUTES

SCHLUESSEL = "bildgeraete"

# The switches of the picture window's memory block (app/image_switches.py)
# are part of this setting, not of a chat.
GRUPPE = "memory"

# A free text start value is one argument on one line; longer than any
# assignment over every device of one machine.
TEXT_MAX = 500

_NUMBER = r"-?\d+(?:\.\d+)?"
_NAME = r"[A-Za-z0-9_*-]+"
_VRAM = re.compile(rf"(?:{_NUMBER}|{_NAME}={_NUMBER}(?:,{_NAME}={_NUMBER})*)")
SPLIT_MODES = ("layer", "row")
_MODE = "(?:layer|row)"
_SPLIT = re.compile(rf"(?:{_MODE}|{_NAME}={_MODE}(?:,{_NAME}={_MODE})*)")


@dataclass(frozen=True)
class Geraete:
    """What the generator starts with; every default leaves its switch out,
    except the switches of ``START_SWITCHES``."""

    vram_limit: str = ""
    offload_to_cpu: bool = False
    threads: int = -1
    split_mode: str = ""
    backend: str = ""
    switches: dict[str, Any] = field(default_factory=dict)
    # Seconds a picture may take; None means no limit.
    zeitgrenze: int | None = None
    # Every sd-cli picture adds to the importance matrix of its model file.
    imatrix: bool = True
    # Minutes without a picture after which the picture server is ended;
    # None means never.
    idle_minutes: int | None = None


def _text(wert: Any) -> str:
    """One line without spaces, or empty."""
    if not isinstance(wert, str) or len(wert) > TEXT_MAX:
        return ""
    return "".join(wert.split())


def vram_pruefen(wert: Any) -> str:
    return text if _VRAM.fullmatch(text := _text(wert)) else ""


def split_pruefen(wert: Any) -> str:
    return text if _SPLIT.fullmatch(text := _text(wert)) else ""


def threads_pruefen(wert: Any) -> int:
    """A count of threads, or -1: none given, the generator counts itself."""
    if isinstance(wert, bool) or not isinstance(wert, (int, float)):
        return -1
    try:
        anzahl = int(wert)
    except (OverflowError, ValueError):
        return -1
    return anzahl if anzahl > 0 else -1


def zeitgrenze_pruefen(wert: Any) -> int | None:
    """A whole number of seconds from 1 on, or None: no limit. A zero, a
    negative number, a text or a fraction is not a limit."""
    if isinstance(wert, bool) or not isinstance(wert, (int, float)):
        return None
    try:
        sekunden = int(wert)
    except (OverflowError, ValueError):
        return None
    return sekunden if sekunden > 0 and sekunden == wert else None


def idle_pruefen(wert: Any) -> int | None:
    """Whole minutes from 1 up to what the engines' own idle times take, or
    None: never. A zero, a negative number, a text or a fraction is not an
    idle time."""
    if isinstance(wert, bool) or not isinstance(wert, (int, float)):
        return None
    try:
        minuten = int(wert)
    except (OverflowError, ValueError):
        return None
    return minuten if 0 < minuten <= MAX_IDLE_MINUTES and minuten == wert else None


def backend_pruefen(wert: Any) -> str:
    """The generator's own assignment syntax (``clip=cpu,vae=cuda0``) is not
    parsed here; it is kept as one line, and the generator says what it
    cannot read."""
    return _text(wert)


# What the on/off switches of the generator's earlier builds say now: each
# turned a part of the generator on everywhere, and the new switches take the
# same thing by name. A value stored under an old key is read as the new one
# and kept under it the next time it is saved.
_EARLIER_SWITCHES = {
    "fa": ("flash_attn", "on"),
    "diffusion_conv_direct": ("conv_direct", "diffusion=on,controlnet=on"),
    "vae_conv_direct": ("conv_direct", "vae=on"),
}

# What a machine starts with while nothing is stored for the switch: flash
# attention in the diffusion model only, the way the generator was always
# started — drawing a highres fix without it takes about eight times as long.
# `auto` hands the choice to the generator.
# Batched CFG starts off: with it on, build 975 computes the picture and its
# negative in one pass for models built on a UNet (SD 1.5, SDXL), and on Metal
# that pass draws a plain white picture whenever CFG is above 1. Off computes
# them one after the other, as the builds before did; a stored value wins.
START_SWITCHES = {"flash_attn": "off,diffusion=on", "batched_cfg": "off"}


def _read_earlier_keys(wert: dict) -> dict:
    """The stored switches with the old on/off keys read as the new ones; a
    key that is stored under its new name wins over its old spelling."""
    translated: dict[str, Any] = {}
    collected: dict[str, list[str]] = {}
    for key, value in wert.items():
        target = _EARLIER_SWITCHES.get(key) if isinstance(key, str) else None
        if target is None:
            translated[key] = value
        elif value is True:
            collected.setdefault(target[0], []).append(target[1])
    for key, parts in collected.items():
        translated.setdefault(key, ",".join(parts))
    return translated


def switches_pruefen(wert: Any) -> dict[str, Any]:
    """The memory block's switches, each checked against its row; a key of
    another block or a value the row does not take is not kept."""
    if not isinstance(wert, dict):
        return {}
    sauber: dict[str, Any] = {}
    for key, value in _read_earlier_keys(wert).items():
        row = image_switches.get(key) if isinstance(key, str) else None
        if row is None or row.group != GRUPPE:
            continue
        try:
            sauber.update(image_switches.check({key: value}))
        except ValueError:
            continue
    return sauber


def pruefen(wert: Any) -> dict[str, Any]:
    """The settings check: only the known fields, each as it is kept."""
    if not isinstance(wert, dict):
        return {}
    sauber: dict[str, Any] = {}
    if "vram_limit" in wert:
        sauber["vram_limit"] = vram_pruefen(wert["vram_limit"])
    if "offload_to_cpu" in wert:
        sauber["offload_to_cpu"] = wert["offload_to_cpu"] is True
    if "threads" in wert:
        sauber["threads"] = threads_pruefen(wert["threads"])
    if "split_mode" in wert:
        sauber["split_mode"] = split_pruefen(wert["split_mode"])
    if "backend" in wert:
        sauber["backend"] = backend_pruefen(wert["backend"])
    if "switches" in wert:
        sauber["switches"] = switches_pruefen(wert["switches"])
    if "zeitgrenze" in wert:
        sauber["zeitgrenze"] = zeitgrenze_pruefen(wert["zeitgrenze"])
    if "idle_minutes" in wert:
        sauber["idle_minutes"] = idle_pruefen(wert["idle_minutes"])
    if "imatrix" in wert:
        # Only a stored "off" turns it off; anything else is the default.
        sauber["imatrix"] = wert["imatrix"] is not False
    return sauber


def lesen(repositories) -> Geraete:
    """The stored values, each one checked again on the way out."""
    stand = repositories.einstellungen.zusammengefuehrt(SCHLUESSEL, vorgabe={})
    werte = pruefen(stand)
    return Geraete(
        vram_limit=werte.get("vram_limit", ""),
        offload_to_cpu=werte.get("offload_to_cpu", False),
        threads=werte.get("threads", -1),
        split_mode=werte.get("split_mode", ""),
        backend=werte.get("backend", ""),
        switches={**START_SWITCHES, **werte.get("switches", {})},
        zeitgrenze=werte.get("zeitgrenze"),
        imatrix=werte.get("imatrix", True),
        idle_minutes=werte.get("idle_minutes"),
    )


def ohne_speicherschalter(werte: dict) -> dict:
    """A picture's own switches without the memory block's: those are the
    machine's and come from here, whatever a request carries."""
    return {
        key: value for key, value in werte.items()
        if (row := image_switches.get(key)) is None or row.group != GRUPPE
    }
