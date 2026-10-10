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
A value the generator would not read is not kept.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from app import image_switches

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
    """What the generator starts with; every default leaves its switch out."""

    vram_limit: str = ""
    offload_to_cpu: bool = False
    threads: int = -1
    split_mode: str = ""
    backend: str = ""
    switches: dict[str, Any] = field(default_factory=dict)


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


def backend_pruefen(wert: Any) -> str:
    """The generator's own assignment syntax (``clip=cpu,vae=cuda0``) is not
    parsed here; it is kept as one line, and the generator says what it
    cannot read."""
    return _text(wert)


def switches_pruefen(wert: Any) -> dict[str, Any]:
    """The memory block's switches, each checked against its row; a key of
    another block or a value the row does not take is not kept."""
    if not isinstance(wert, dict):
        return {}
    sauber: dict[str, Any] = {}
    for key, value in wert.items():
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
        switches=werte.get("switches", {}),
    )


def ohne_speicherschalter(werte: dict) -> dict:
    """A picture's own switches without the memory block's: those are the
    machine's and come from here, whatever a request carries."""
    return {
        key: value for key, value in werte.items()
        if (row := image_switches.get(key)) is None or row.group != GRUPPE
    }
