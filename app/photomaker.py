"""PhotoMaker: one person's face, carried into a picture that was never taken.

Three things have to come together, and none of them works alone:

``photomaker/``
    The model that does the carrying. One downloaded file.

``faces/``
    Photos of the person. The user's own pictures — which is why they live in
    a folder of their own and not beside the model: "which of these is the
    model" must never become a question the program has to guess.

a class word in the prompt
    The generator only fires when the prompt names one of four words with
    ``img`` stuck to it — ``a man img, sitting in a café``. Without it the
    model loads, changes nothing, and the picture comes back looking like an
    ordinary run for no visible reason.

The class word is the reason this module exists rather than two more lines in
the runner. Nobody should have to know that rule, and nobody should have to
type it: the window asks who is in the photos, and the word is attached here.

**SDXL only.** On an SD-1.5 model the generator ignores the whole thing.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from app import bildwahlen

# What counts as a photo. Deliberately short: these are the formats a phone
# and a camera produce, and anything else in that folder is not a portrait.
BILDENDUNGEN = (".png", ".jpg", ".jpeg", ".webp")


def modell(bildordner: Path) -> Path | None:
    """The PhotoMaker model, or nothing if none has been put there yet.

    **Safetensors only.** The generator cannot read the official ``.bin``
    release — a converted safetensors build is required. Accepting ``.bin``
    here would find a file, pass it on, and end in a failed run whose reason
    is nowhere near the folder somebody dropped it into.

    The first file wins. There is no picking in the window on purpose — one
    model does one job here, and a choice between two would be a question
    without a meaningful answer.
    """
    ordner = Path(bildordner).expanduser() / bildwahlen.PHOTOMAKER_ORDNER
    if not ordner.is_dir():
        return None
    for datei in sorted(ordner.iterdir()):
        if datei.is_file() and datei.suffix.lower() == ".safetensors":
            return datei
    return None


def gesichter(bildordner: Path) -> Path | None:
    """The folder of photos — only when it actually holds some.

    An empty folder is the same as no folder: the generator would load the
    model, find no face to learn, and draw an ordinary picture. Better to
    leave the flag off entirely than to ask for something that cannot happen.
    """
    ordner = Path(bildordner).expanduser() / bildwahlen.GESICHTER_ORDNER
    if not ordner.is_dir():
        return None
    for datei in ordner.iterdir():
        if datei.is_file() and datei.suffix.lower() in BILDENDUNGEN:
            return ordner
    return None


def fingerabdruck(ordner: Path) -> str:
    """A short stand-in for "these are the current photos". The folder itself never changes — ``gesichter()`` always
    builds the same path from the fixed ``GESICHTER_ORDNER`` name — only
    what a person puts inside it does, and swapping the photos in place is
    the only way anyone ever changes a face. Image-Turbo compares this
    instead of the folder's own name, so a swap restarts the running server
    with the new photos instead of quietly drawing the old face again.

    Sorted (name, size, mtime) of every photo, hashed down to one short
    string — cheap to recompute on every request, and it changes the moment
    a file is added, removed or replaced."""
    eintraege = sorted(
        (datei.name, datei.stat().st_size, datei.stat().st_mtime)
        for datei in Path(ordner).iterdir()
        if datei.is_file() and datei.suffix.lower() in BILDENDUNGEN
    )
    text = "|".join(f"{name}:{groesse}:{zeit}" for name, groesse, zeit in eintraege)
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def klasse_pruefen(wert: str) -> str:
    """The class word, or empty if it is not one of the four.

    Not a matter of taste: the generator was trained on these words. Anything
    else passes through and quietly does nothing, which is the worst kind of
    setting — one that looks accepted and has no effect.
    """
    sauber = str(wert or "").strip().lower()
    return sauber if sauber in bildwahlen.PM_KLASSEN else ""


def prompt_mit_klasse(prompt: str, klasse: str) -> str:
    """The prompt with the trigger word in front, unless it is already there.

    Somebody may have written ``a man img`` themselves — then it stays at one.
    The check looks for the class word followed by ``img`` anywhere in the
    text, because that is the whole condition the generator tests.

    The added part never goes into the field the user types in. What stands
    there is their text; the trigger is mechanics.
    """
    if not klasse:
        return prompt
    if re.search(rf"\b{re.escape(klasse)}\s+img\b", prompt, re.IGNORECASE):
        return prompt
    vorsatz = f"a {klasse} img"
    return f"{vorsatz}, {prompt}" if prompt.strip() else vorsatz
