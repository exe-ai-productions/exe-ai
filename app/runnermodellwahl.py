"""How the main model server starts — the user's answer, kept where it counts.

All of this used to live in the browser: the model file, the window, the
layers, the port and the speed and vision modules stood in ``localStorage``
under ``runner:*`` (frontend/src/teile/Modellserver.svelte). That was
defensible while nothing but a hand on a button ever started this server —
the page that kept the numbers was the page that used them.

It stopped being defensible the moment anything else wanted to know. The
program cannot say which file with which settings "the main model" would be,
because at program start there is no browser and nothing to ask. That is the
whole reason the loading table has to read "main model — nobody loads it
automatically": not a decision, a consequence.

So it lives here, in one setting, exactly the way the agent slot's does
(app/agentenmodellwahl.py) — same shape, same rules, and read through the
same kind of call, so a start path that wants to bring this server up does
not have to invent a second idea of where the answer is.

What is deliberately NOT here:

  * **The engine levers** (``fein``). They already stood on the server, in
    their own key (app/feineinstellungenwahl.py) — the one part of the choice
    that had been moved before. Copying them in here would be the second
    place this module exists to prevent; ``startwerte`` reads them from the
    key that owns them and hands them on with the rest, so a caller still
    gets one answer to "how does this server start".
  * **The port number.** The server owns its port (app/modellrunner.py);
    ``None`` here means "not moved by hand" and the runner uses its own. A
    number repeated here would freeze today's default into every stored
    choice, which is the same nailing-down from the other side.

The modules are remembered PER MODEL FILE, and that is the one place this
key's shape differs from the slot's. The slot holds one file and therefore
one speed module; this server is switched between files, and the projector
that belongs to a vision model is nonsense for the one next to it. The
browser keys were per model for the same reason (``runner:drafter:<datei>``),
so this is the old behaviour kept, not a new idea.
"""

from __future__ import annotations

from typing import Any

from app import feineinstellungenwahl
from app.db.repositories.einstellungen import GLOBAL, WriteRefused

SCHLUESSEL = "runnermodell"

# The window the form opens on. Every model server this program starts opens
# on the same one — the agent slot (app/agentenmodellwahl.py) and the runner
# itself (app/modellrunner.py ``starten``) carry this exact number, and three
# different starting points for one question were three answers to it.
# It is a starting point, not a limit: the field stays open, and a value a
# hand puts there is stored and read back before this one is ever reached.
KONTEXT_VORGABE = 16384
# 99 is llama.cpp's own way of saying "all of them".
SCHICHTEN_VORGABE = 99

# The bounds the window's own fields carry, repeated here because a stored
# value can come from anywhere — an old version, a hand-edited database, a
# direct call on the settings route.
KONTEXT_MIN, KONTEXT_MAX = 512, 1_048_576
SCHICHTEN_MIN, SCHICHTEN_MAX = 0, 999
PORT_MIN, PORT_MAX = 1024, 65535

# A file name in the model folder. Bounded like every other stored string:
# the settings column holds JSON and cannot check anything by itself.
NAME_HOECHSTLAENGE = 200
# How many models may carry a remembered module pair. A folder with more
# files than this is not a folder anybody browses; the cap is here so a
# direct call on the settings route cannot grow the row without end. A write
# that would grow the row past it is refused, never shortened: shortening
# would drop an entry without a word (``row_check``).
MODULE_HOECHSTZAHL = 500

VORGABE: dict[str, Any] = {
    # ``None`` means nobody has chosen yet — the window then pre-picks, the
    # way it always did. An empty string is a different answer: a deliberate
    # "no model", which is why the two may not be collapsed.
    "modell": None,
    "kontext": KONTEXT_VORGABE,
    "schichten": SCHICHTEN_VORGABE,
    # ``None`` means "the server's own port" (app/modellrunner.py). The number
    # is not repeated here — see the module header.
    "port": None,
    # ``{datei: {"drafter": …, "vision": …}}``. Inside an entry ``None`` means
    # "never chosen for this file" (the window then offers what the folder
    # manifest declared) and an empty string means "chosen: none".
    "module": {},
    # Whether this server may be brought up by the program itself, ahead of a
    # cron entry that is about to come due (app/modellvorlauf.py). Off means
    # the entry waits visibly until the user has a model running, exactly as
    # it does when the one field points somewhere else.
    #
    # ONE tick box, and it lives in THIS key: the question is how this server
    # starts, which is the one question this key exists to answer. Preloading
    # is a way this server starts, so it belongs next to the window, the
    # layers and the port and not in a key of its own.
    #
    # There is no second one anywhere, and there is nothing for a second one
    # to switch: of the four servers this program can hold, this is the only
    # one that is started ahead of time. The slot starts at every program
    # launch off the one field's own switch (app/agentenmodellwahl.py), the
    # embedding server is never started by the program at all, and the
    # picture server comes up when a picture is asked for.
    #
    # Shipped ON, unlike the switch of the field that reaches this server
    # (app/agentenmodellwahl.py, shipped OFF). Nothing here starts by itself
    # until that field is switched on AND points at ``runner``, and switching
    # it on is the consent — the same switch-on the slot reads as consent to
    # start itself at every program launch. This tick is what takes that
    # consent back for this one server. Defaulting it to off would in
    # addition switch preloading off underneath every installation that has
    # it today, which is not a default but a regression.
    "vorladen": True,
}


def _zahl(roh: Any, tief: int, hoch: int, ersatz: int | None) -> int | None:
    try:
        return max(tief, min(hoch, int(roh)))
    except (TypeError, ValueError):
        return ersatz


def _name(roh: Any) -> str | None:
    """A stored file name, with the difference between the two empties kept.

    ``None`` is "nothing remembered", ``""`` is "remembered as none". Folding
    them together would let a pairing the user switched off walk back in.
    """
    if roh is None:
        return None
    return str(roh).strip()[:NAME_HOECHSTLAENGE]


def wahl_pruefen(wert: Any) -> dict[str, Any]:
    """``runnermodell``: the start choice, before it is stored.

    Each key survives only when it was sent, so the window can write the
    window size without resending the module memory and the other way round.
    Numbers are clamped rather than refused, the same rule the slot's key
    follows: a value out of range is a value to bring into range, and a
    settings write that failed outright would take the whole choice with it.
    The size of the module memory is not checked here but on the whole row
    (``row_check``): what is checked here may be one write's part of it.
    """
    if not isinstance(wert, dict):
        return {}
    sauber: dict[str, Any] = {}
    if "modell" in wert:
        sauber["modell"] = _name(wert["modell"])
    if "vorladen" in wert:
        sauber["vorladen"] = bool(wert["vorladen"])
    # ``None`` survives as ``None`` here, for the same reason the port number
    # is not repeated in this key (see the module header): "nobody has chosen"
    # and "today's default" are different answers, and storing the second for
    # the first nails the current default into somebody's saved choice. What
    # an unset value RUNS as is decided in one place, ``startwerte`` — which
    # is where the fallback belongs, because it is a fallback and not a
    # decision the user made.
    if "kontext" in wert:
        sauber["kontext"] = (
            None if wert["kontext"] is None
            else _zahl(wert["kontext"], KONTEXT_MIN, KONTEXT_MAX, KONTEXT_VORGABE)
        )
    if "schichten" in wert:
        sauber["schichten"] = (
            None if wert["schichten"] is None
            else _zahl(wert["schichten"], SCHICHTEN_MIN, SCHICHTEN_MAX, SCHICHTEN_VORGABE)
        )
    if "port" in wert:
        # None survives as None: "the server's own port" is a real answer
        # here, not a missing one.
        sauber["port"] = (
            None if wert["port"] in (None, "", 0)
            else _zahl(wert["port"], PORT_MIN, PORT_MAX, None)
        )
    if "module" in wert:
        roh = wert["module"] if isinstance(wert["module"], dict) else {}
        module: dict[str, dict[str, str | None]] = {}
        for datei, eintrag in roh.items():
            if not isinstance(eintrag, dict):
                continue
            # Inside an entry the same rule as at the top: only the role that
            # was sent survives. A row writes one of the two, and filling the
            # other in with ``None`` would make "speed module changed" read as
            # "projector never chosen" the moment the two are merged rather
            # than replaced.
            module[str(datei)[:NAME_HOECHSTLAENGE]] = {
                rolle: _name(eintrag[rolle])
                for rolle in ("drafter", "vision")
                if rolle in eintrag
            }
        sauber["module"] = module
    return sauber


def _module_count(row: Any) -> int:
    module = row.get("module") if isinstance(row, dict) else None
    return len(module) if isinstance(module, dict) else 0


def row_check(old: Any, new: Any) -> None:
    """Refuses a row that a write would grow past ``MODULE_HOECHSTZAHL``
    module pairs, by raising ``WriteRefused``; nothing is written then.

    Only growth is refused. A row stored larger before the cap was enforced
    still takes a write that adds no module — a slider, say — so it never
    locks its owner out; it just cannot get any larger.
    """
    count = _module_count(new)
    if count > MODULE_HOECHSTZAHL and count > _module_count(old):
        raise WriteRefused("More module pairs are stored than a row can hold.")


def wahl(repositories) -> dict[str, Any]:
    """What the field says right now — global scope only.

    No model or chat scope: this decides WHICH model runs, and a per-model
    setting for that would be a circle. The same reasoning the slot's key
    stands on.
    """
    stand = repositories.einstellungen.zusammengefuehrt(
        SCHLUESSEL, vorgabe=dict(VORGABE)
    )
    if not isinstance(stand, dict):
        return dict(VORGABE)
    return stand


def modell(repositories) -> str | None:
    """The file this server would load — or ``None`` when nobody has chosen.

    The question the program could not answer before this key existed, and
    the reason the loading table said "main model — nobody loads it
    automatically". An empty stored string is a chosen "no model" and comes
    back as ``None`` too: neither one names a file to load.
    """
    return str(wahl(repositories).get("modell") or "").strip() or None


def vorladen_erlaubt(repositories) -> bool:
    """Whether the program may start this server by itself before a due time.

    Asked on every tick and not once at startup: the tick the user moves the
    tick box is the tick it has to take effect on, whether that means the
    next due moment preloads or that a stand-down already running stops
    mattering.

    Off is not a smaller preload, it is the program before preloading existed — the
    entry waits visibly and runs the moment a model is there.
    """
    return bool(wahl(repositories).get("vorladen", VORGABE["vorladen"]))


def modulwahl(repositories, datei: str) -> dict[str, str | None]:
    """What was last chosen for exactly this file — speed module, projector.

    ``None`` per entry means "never chosen", which is not the same as
    "chosen: none": the window offers the folder manifest's pairing for the
    first and an empty row for the second.
    """
    module = wahl(repositories).get("module")
    eintrag = module.get(datei) if isinstance(module, dict) else None
    if not isinstance(eintrag, dict):
        return {"drafter": None, "vision": None}
    return {"drafter": _name(eintrag.get("drafter")), "vision": _name(eintrag.get("vision"))}


def startwerte(repositories, datei: str) -> dict[str, Any]:
    """HOW this server runs — everything but the file itself.

    The one answer every start path takes, so no two of them can bring the
    same server up differently. Today that is the button on the page and the
    catalogue's "start" (app/api/v1/runner.py); the point of putting it here
    is that a path with no browser behind it — a restart, a tick that sees a
    run coming — asks the same question and gets the same answer.

    ``datei`` decides which remembered module pair applies, because the pair
    belongs to the file and not to the server.

    The two empties travel on as they are: ``None`` is "never chosen" and lets
    the runner take the folder manifest's pairing, ``""`` is "chosen: none"
    and stops it. Collapsing them here was the one place in this key where
    that difference did not reach the process — a projector switched off by
    hand came back on the command line, attached by the name heuristic. It
    was faithful to the form's old ``drafter || null``, and it was wrong
    there too.
    """
    stand = wahl(repositories)
    modul = modulwahl(repositories, datei)
    return {
        "kontext": _zahl(
            stand.get("kontext"), KONTEXT_MIN, KONTEXT_MAX, KONTEXT_VORGABE
        ),
        "schichten": _zahl(
            stand.get("schichten"), SCHICHTEN_MIN, SCHICHTEN_MAX, SCHICHTEN_VORGABE
        ),
        "port": (
            None if stand.get("port") in (None, "", 0)
            else _zahl(stand.get("port"), PORT_MIN, PORT_MAX, None)
        ),
        "drafter": modul["drafter"],
        "vision": modul["vision"],
        # From the key that owns them. They were the one part of this choice
        # that already lived on the server, and reading them here rather than
        # copying them in is what keeps that true.
        "fein": feineinstellungenwahl.gewaehlt(repositories),
    }


def modell_merken(repositories, datei: str) -> None:
    """Records the file that was just started as the chosen one.

    The window writes the choice the moment it is picked, which covers the
    page. This covers every other way a start happens — the catalogue's
    button above all, which used to start a file and leave the remembered
    choice pointing at the previous one. One record, written where all of
    them pass.

    Written key by key, never as a whole object. A start and a slider are two
    writers on one row, on two threads with a connection each: reading the
    row, changing one key and writing it all back drops whatever landed in
    between — the window, the layers, the module picked for the file. The
    merge is the repository's, and it is the only writer holding the lock.
    """
    stand = repositories.einstellungen.holen(GLOBAL, SCHLUESSEL)
    if isinstance(stand, dict) and stand.get("modell") == datei:
        return
    repositories.einstellungen.zusammenlegen(
        GLOBAL, SCHLUESSEL, {"modell": _name(datei)}
    )


def vorgaben() -> dict[str, Any]:
    """What an unset field falls back to, for the window to be told.

    Sent in the server's answer rather than written into the page, so there
    is exactly one place that decides these — the same arrangement the slot's
    page already has. The choice itself is not in here: that is answered by
    the field, not by a fallback.
    """
    return {
        name: wert for name, wert in VORGABE.items() if name not in ("modell", "module")
    }


__all__ = [
    "SCHLUESSEL",
    "VORGABE",
    "KONTEXT_VORGABE",
    "SCHICHTEN_VORGABE",
    "modell",
    "modell_merken",
    "modulwahl",
    "startwerte",
    "vorgaben",
    "vorladen_erlaubt",
    "wahl",
    "row_check",
    "wahl_pruefen",
]
