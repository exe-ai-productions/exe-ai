"""A drawing job, written into the chat's little history.

The terminal module shows what happened in a conversation: which commands
ran, and how they ended. A picture ordered from the plus menu belongs in that
list for exactly the same reason a command does — somebody started something
here, it took a while, and it either worked or it did not. That it reaches
the generator over a different route than a tool call is an implementation
detail of the program, not something the reader should have to know.

Its own module because the run registry next door is the shell tool's, and
this is not a shell tool: it borrows the registry the way any other kind of
work may, and keeps its own vocabulary out of it. What the registry learned
for this is one neutral word — `art` — and nothing about pictures.

The prompt travels whole. A run entry is one line, but the line shortens
itself for display the way a long shell command already does — cutting it
here would throw the rest away for good, and the unfolded row is where
somebody looks to find out what was actually asked for.
"""

from __future__ import annotations

import logging
from typing import Any

from app.tools.hintergrund import ABGEBROCHEN, ART_BILD, FEHLER, FERTIG, Lauf, laeufe

log = logging.getLogger(__name__)

# The run list a picture of the studio is filed under: the studio belongs to
# no chat, but its drawing is work somebody watches in the terminal like any
# other. Chat ids are generated and never take this word.
STUDIO = "studio"

# Bookkeeping, not a drawing choice — where a run is filed and which picture
# of a batch this is decide nothing about what the picture looks like, and
# have no business in a list the reader is meant to read as "how was this
# made".
_NICHT_REGLER = {
    "chat_id", "lauf_chat", "von", "nr", "lauf_kennung", "frage_erstellen", "studio",
    # Where a drawn piece goes back into its picture: no dial of the picture.
    "crop_of", "crop_box",
}
# Named once, together with the group they belong to, purely for the
# comment below: these read as facts about ANY picture, set or not — a
# CFG left at its default is still a fact worth a line, unlike a LoRA slot
# nobody filled. The prompt is not among them: the run's own line already
# is the prompt, and a second copy under the dials would only repeat it.
_IMMER_GEZEIGT = {"modell", "breite", "hoehe", "schritte", "cfg", "seed", "sampler", "scheduler"}
# The line of the run itself, so never a dial of it.
_ALS_ZEILE_GEZEIGT = {"prompt"}


def _hat_inhalt(wert: Any) -> bool:
    """Whether a value says anything. A number or a switch always does — a
    CFG of 0 and a switch set to off are choices; an empty text, an empty
    list and a missing value are a line with nothing after its name."""
    if wert is None:
        return False
    if isinstance(wert, str):
        return wert.strip() != ""
    if isinstance(wert, (list, tuple, dict, set)):
        return len(wert) > 0
    return True


def _wirklich_gesetzt(wert: Any) -> bool:
    """Whether a plain value looks chosen — the fallback for a request that
    is not a model and therefore cannot be compared against its own
    defaults (see ``_gewaehlte``).

    Deliberately does NOT treat ``"auto"`` as unset: it is a real, behaviour-
    changing value for several dials, and dropping it would hide exactly the
    switch somebody opens this list to find.

    "Looks chosen" is a WEAKER question than the one the model path asks, and
    the two cannot be made to agree — see ``_gewaehlte`` for why that is a
    property of a bare dict and not a bug to be fixed here.
    """
    if wert is None:
        return False
    if isinstance(wert, bool):
        return wert
    if isinstance(wert, str):
        return wert.strip() != ""
    if isinstance(wert, (int, float)):
        return wert != 0
    if isinstance(wert, (list, dict)):
        return len(wert) > 0
    return bool(wert)


def _gewaehlte(wunsch: Any, werte: dict[str, Any]) -> set[str]:
    """The fields that differ from what the request would have carried on
    its own.

    A drawing request always carries every field, filled with a default the
    moment nobody chose otherwise — so "is it set" cannot be answered by
    looking at the value alone. ``-1`` means "let the class decide" for one
    dial and "leave the CPU alone" for another; ``1.0`` is an img2img
    strength that means nothing without a starting picture. Asking the model
    itself which values are still its defaults answers all of those at once,
    and keeps answering when a new field is added.

    The two branches answer DIFFERENT questions, on purpose, because a bare
    dict cannot answer the first one: it carries no defaults to be compared
    against. So a value that happens to equal its model default — ``"auto"``
    is the one that actually turns up — counts as unset for a model and as
    set for a dict, and the dict caller gets the more generous list.

    That is the only honest reading of a dict, not a divergence to be
    smoothed over: making the model path fall back to "looks filled in" too
    would put every untouched default back on the list, which is precisely
    what this function exists to keep off it. Every caller in the running
    program hands over a model; the dict branch is the door for a caller
    that has none, and ``tests/test_bildlauf.py`` pins both readings so the
    difference stays a decision instead of turning back into a surprise.
    """
    if hasattr(wunsch, "model_dump"):
        return set(wunsch.model_dump(exclude_defaults=True))
    return {name for name, wert in werte.items() if _wirklich_gesetzt(wert)}


# A field whose own value is not zero/empty can still be nothing more than
# the pass's OWN default — sd-cli always sends hires_scale=2.0, on or off.
# Its group's switch is what actually says whether it was chosen; each
# entry names that switch and the fields it alone decides.
_GRUPPEN = (
    ("hires", ("hires_scale", "hires_steps", "hires_denoise", "hires_upscaler", "hires_width", "hires_height")),
    ("ad_modell", ("ad_prompt", "ad_loras", "ad_negativ", "ad_confidence")),
    ("pulid_weights", ("pulid_id_embedding", "pulid_id_weight")),
    ("control_net", ("control_image", "control_strength", "canny")),
    ("startbild", ("staerke", "maske")),
    ("loras", ("lora_apply_mode",)),
    ("slg_scale", ("skip_layer_start", "skip_layer_end")),
)


def _regler_von(wunsch: Any) -> dict[str, Any]:
    """The dials a picture was actually made with, field by field — the
    whole request handed over, not a hand-picked subset (an unusual field,
    a LoRA slot, is exactly what would be missing from a fixed list). Only
    what was truly chosen stands in the result; the rest would be thirty
    blank lines under a plain snapshot."""
    werte = wunsch.model_dump() if hasattr(wunsch, "model_dump") else dict(wunsch)
    gewaehlt = _gewaehlte(wunsch, werte)
    ergebnis = {
        schluessel: wert
        for schluessel, wert in werte.items()
        if schluessel not in _NICHT_REGLER
        and schluessel not in _ALS_ZEILE_GEZEIGT
        and (schluessel in _IMMER_GEZEIGT or schluessel in gewaehlt)
        and _hat_inhalt(wert)
    }
    for schalter, abhaengige in _GRUPPEN:
        if schalter not in gewaehlt:
            for feld in abhaengige:
                ergebnis.pop(feld, None)
    return ergebnis


# The dials of a picture already running, by (chat, run number) — kept
# beside the run itself rather than on it: `Lauf` is the shell tool's own
# registration and, by its own rule, carries nothing about pictures.
_regler: dict[tuple[str, int], dict[str, Any]] = {}


def _vergessen(chat_id: str) -> None:
    """Drops this chat's dials when its runs go.

    Numbering restarts at 1 for a chat whose runs were forgotten, so an
    entry left behind here would be handed to the NEXT picture of that
    number — a new picture wearing an old one's settings.
    """
    for schluessel in [s for s in _regler if s[0] == chat_id]:
        _regler.pop(schluessel, None)


laeufe.beim_vergessen(_vergessen)


def beginnen(chat_id: str | None, prompt: str, wunsch: Any = None) -> Lauf | None:
    """Opens the entry. Without a chat or the studio there is no list to put
    it in."""
    if not chat_id:
        return None
    try:
        # Full length now, once — the line already shortens itself for
        # display the same way a long shell command does (ModulTerminal.svelte
        # .befehl: ellipsis shut, pre-wrap open), and kurzform()'s own cut
        # was the only place any of it was ever thrown away for good.
        lauf = laeufe.anlegen(chat_id, prompt, art=ART_BILD)
    except Exception:  # noqa: BLE001 - a log line must never break a picture
        log.exception("Picture run could not be created")
        return None
    if wunsch is not None:
        # Inside its own guard, and for the same reason as the one above: by
        # now the run EXISTS and its start has been announced. An error
        # escaping here would leave the caller without a handle to close it
        # with, and the run would sit on "running" until the service
        # restarts. A missing dial list is a smaller loss than that.
        try:
            regler = _regler_von(wunsch)
            _regler[(chat_id, lauf.nummer)] = regler
            # For whoever is watching this chat's terminal right now — a
            # reload gets the same dict from regler_von() below instead,
            # since a snapshot fetch does not replay past events.
            laeufe.melden(chat_id, typ="lauf_regler", lauf=lauf.nummer, regler=regler)
        except Exception:  # noqa: BLE001 - see above
            log.exception("Settings of the picture run could not be stored")
    return lauf


def regler_von(chat_id: str, nummer: int) -> dict[str, Any] | None:
    """What a picture run was called with — None for a run this module
    never opened (an old server restart, a command run misfiled as art
    'bild', which cannot happen but is not this function's to assume)."""
    return _regler.get((chat_id, nummer))


def beenden(
    lauf: Lauf | None, *, gescheitert: bool = False, abgebrochen: bool = False,
    reason: str | None = None,
) -> None:
    """Closes the entry with the outcome the caller saw.

    A picture has no exit code — the state is what says how it went, and a
    stopped one is not a failure but a decision.

    ``reason`` is what the caller is told about a failed picture: the
    sentence and, below it, the painter's last words. It becomes the run's
    output before the run closes, so the terminal still says why once the
    window's message is gone. A finished or a stopped run takes none — it
    has nothing to explain.
    """
    if lauf is None:
        return
    zustand = ABGEBROCHEN if abgebrochen else (FEHLER if gescheitert else FERTIG)
    if reason and zustand == FEHLER:
        # In its own guard: a text that cannot be written must not leave
        # the run open — a red run without words is the smaller loss.
        try:
            laeufe.zeile(lauf, reason, strom="stderr")
        except Exception:  # noqa: BLE001 - same reason as above
            log.exception("Reason of the failed picture run could not be stored")
    try:
        laeufe.beenden(lauf, code=None, zustand=zustand)
    except Exception:  # noqa: BLE001 - same reason as above
        log.exception("Picture run could not be ended")
