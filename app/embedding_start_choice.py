"""What the embedding server starts with: the file, the port and how it runs.

The window used to hold the file and the port in the page, so after closing it
or restarting the program the picker stood on the first file of the folder and
the port field on 8081 again. They are stored here, in a row of their own, the
way the speech and clean-up servers' start values are
(app/diktatsprachewahl.py) — written as they are touched, read again when the
window opens, and used at the next start when the request does not name them.

Next to the two stay the values of how it runs: the window (context), the batch
size, the pooling kind, the layers on the graphics card, the CPU threads, the
memory lock, the number of parallel requests and the idle time. Every key is stored only when
it was sent, so the window can write one value without resending the others.
The shipped answers are the ones the server always started with, except for
the pooling kind: shipped, the model's own kind stands (no flag).
"""

from __future__ import annotations

import math
from typing import Any

from app.feineinstellungen import MAX_FAEDEN, MAX_IDLE_MINUTES, MAX_PARALLEL, Feineinstellungen

SCHLUESSEL = "embedding"

NAME_MAX = 200
PORT_MIN, PORT_MAX = 1024, 65535

# The window the server opens: the steps the window offers are 2048, 4096,
# 8192, 16384 and 32768; a stored number between them is a number a hand put
# there and stays, only the ends are bounds.
CONTEXT_MIN, CONTEXT_MAX = 2048, 32768
CONTEXT_DEFAULT = 2048
# The batch size is one number for both `--batch-size` and `--ubatch-size`
# (a text longer than the micro batch is refused by a non-causal model). It
# is at least the shipped 2048 and at most the window.
BATCH_MIN = 2048
BATCH_DEFAULT = 2048
# "" is the model's own kind (no `--pooling` flag); the other three are
# named.
POOLING = ("", "mean", "cls", "last")
LAYERS_MIN, LAYERS_MAX = 0, 999

VORGABE: dict[str, Any] = {
    "model": "",
    "port": None,
    "context": CONTEXT_DEFAULT,
    "batch": BATCH_DEFAULT,
    "pooling": "",
    # None is the engine's own "auto": no layer flag at all.
    "layers": None,
    # 0 is "the engine decides": no thread flag at all.
    "threads": 0,
    "mlock": False,
    # None is "auto": no flag, the engine picks its own count.
    "parallel": None,
    # None is "never": no idle flag, the server keeps its model loaded.
    "idle_minutes": None,
}


def _integer(roh: Any) -> int | None:
    """An integer out of what was sent, or None where it is no integer."""
    if isinstance(roh, bool):
        return None
    if isinstance(roh, int):
        return roh
    if isinstance(roh, float) and math.isfinite(roh) and roh == int(roh):
        return int(roh)
    if isinstance(roh, str):
        try:
            return int(roh.strip())
        except ValueError:
            return None
    return None


def _clamped(roh: Any, minimum: int, maximum: int) -> int | None:
    zahl = _integer(roh)
    return None if zahl is None else max(minimum, min(maximum, zahl))


def _truth(roh: Any) -> bool:
    """A switch out of what was sent: the words that say no say no."""
    if isinstance(roh, str):
        return roh.strip().lower() in ("1", "true", "yes", "on")
    return bool(roh)


def wahl_pruefen(wert: Any) -> dict[str, Any]:
    """The choice before it is stored. A file name is trimmed and bounded; a
    port outside the unprivileged range is not stored at all (the works port
    stands), because clamping it would store a number nobody typed. A number
    of the way it runs is brought into its bounds, a pooling kind nobody
    knows is the model's own, and what is no number at all is not stored."""
    if not isinstance(wert, dict):
        return {}
    sauber: dict[str, Any] = {}
    if "model" in wert:
        roh = wert["model"]
        sauber["model"] = "" if roh is None else str(roh).strip()[:NAME_MAX]
    if "port" in wert:
        roh = wert["port"]
        if isinstance(roh, int) and not isinstance(roh, bool) and PORT_MIN <= roh <= PORT_MAX:
            sauber["port"] = roh
    if "context" in wert:
        zahl = _clamped(wert["context"], CONTEXT_MIN, CONTEXT_MAX)
        if zahl is not None:
            sauber["context"] = zahl
    if "batch" in wert:
        # Only the lower bound here: the window it must not exceed is read
        # with it at the start (`startwerte`), and a batch stored before the
        # window is raised must not be cut by the window of the moment.
        zahl = _clamped(wert["batch"], BATCH_MIN, CONTEXT_MAX)
        if zahl is not None:
            sauber["batch"] = zahl
    if "pooling" in wert:
        art = str(wert["pooling"] or "").strip().lower()
        sauber["pooling"] = art if art in POOLING else ""
    if "layers" in wert:
        roh = wert["layers"]
        if roh in (None, ""):
            sauber["layers"] = None
        elif (zahl := _clamped(roh, LAYERS_MIN, LAYERS_MAX)) is not None:
            sauber["layers"] = zahl
    if "threads" in wert:
        zahl = _clamped(wert["threads"], 0, MAX_FAEDEN)
        if zahl is not None:
            sauber["threads"] = zahl
    if "mlock" in wert:
        sauber["mlock"] = _truth(wert["mlock"])
    if "parallel" in wert:
        roh = wert["parallel"]
        if roh in (None, "", 0):
            sauber["parallel"] = None
        elif (zahl := _clamped(roh, 1, MAX_PARALLEL)) is not None:
            sauber["parallel"] = zahl
    if "idle_minutes" in wert:
        roh = wert["idle_minutes"]
        if roh in (None, "", 0):
            sauber["idle_minutes"] = None
        elif (zahl := _clamped(roh, 1, MAX_IDLE_MINUTES)) is not None:
            sauber["idle_minutes"] = zahl
    return sauber


def wahl(repositories) -> dict[str, Any]:
    """What is stored: ``model`` ("" for none chosen), ``port`` (None for the
    server's own port) and the values of how it runs, each with its shipped
    answer where nothing is stored. Read again through the same check, because
    a row can come from anywhere; the batch is held to the window here, where
    both are at hand."""
    stand = repositories.einstellungen.zusammengefuehrt(SCHLUESSEL, vorgabe={})
    wert = {**VORGABE, **wahl_pruefen(stand if isinstance(stand, dict) else {})}
    wert["batch"] = min(wert["batch"], wert["context"])
    return wert


def startwerte(repositories) -> dict[str, Any]:
    """HOW the server runs, in the words the runner takes: the window, the
    layers (None: no flag), the engine levers for threads, memory lock and
    parallel requests, the batch size and the pooling kind, and the stored
    port. The one answer the start takes, read once."""
    stand = wahl(repositories)
    fein = Feineinstellungen(
        faeden=stand["threads"] or None,
        festnageln=stand["mlock"],
        parallel=stand["parallel"],
        idle_minutes=stand["idle_minutes"],
    )
    return {
        "port": stand["port"],
        "kontext": stand["context"],
        "schichten": stand["layers"],
        "fein": fein,
        "batch": stand["batch"],
        "pooling": stand["pooling"],
    }


__all__ = ["SCHLUESSEL", "startwerte", "wahl", "wahl_pruefen"]
