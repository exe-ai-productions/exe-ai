"""Tying a kit's part to the picture models it belongs to.

A picture model of a kit family is drawn with its parts: its text encoders
and its VAE. Which file a model takes for each is kept at the model
(app/bildmodellwerte.py). A download that brings a part for a model writes it
there, so nobody has to pick the parts of a fetched model by hand — and the
same holds for a part that was lying in its folder already when the model
was asked for.

A model that arrives after its parts finds them the same way: every part of
its family's kit that is there already is written at it.

A part is shared by every model whose kit names it. So a part that is the
model's own by the family table (app/image_families.py, ``kit_of_file``) is
also written at every other model in the folder whose kit names the same
file and that carries none for that field yet: their kit is complete from
that moment too. A part a model was given by hand is never replaced that way.
"""

from __future__ import annotations

from pathlib import Path

from app import bildinhalt, bildmodellwerte, bildrunner, bildwahlen, image_families

# The fields of a model's kit a download can fill: every part the family
# table names a source for.
FIELDS = tuple(sorted({
    part.part for family in image_families.FAMILIES for part in family.kit_parts
}))


# The kinds the picture side keeps in folders of their own, by the word their
# folder is named with. A file whose path carries one of them is that kind —
# a LoRA, a VAE, a ControlNet of the family — and no model to assemble a kit
# for. A text encoder outside such a folder is told by its own name, and so
# is a latent upscaler, which a repository keeps under a word of its own.
_COMPANION_WORDS = tuple(
    folder.removesuffix("s")
    for folder in (
        bildrunner.VAE_ORDNER, bildrunner.TEXTVERSTEHER_ORDNER, bildwahlen.LORA_ORDNER,
        bildrunner.CONTROLNET_ORDNER, bildrunner.UPSCALER_ORDNER, bildrunner.PULID_ORDNER,
        bildrunner.YOLO_ORDNER, bildwahlen.EMBEDDING_ORDNER, bildwahlen.PHOTOMAKER_ORDNER,
    )
) + ("t5xxl", "clip_l", "clip_g", "upscale", "upsampler")


def kit_parts(path: str, family: str | None = None) -> tuple[image_families.KitPart, ...]:
    """The parts a model file comes with — in a repository or in the folder.
    ``family`` is the family its own header names (``bildinhalt.file_family``,
    ``header_family``); given, it decides, and the name only picks among the
    parts some models of the family take. Without it the name decides, as it
    always did. Empty for a family or a name that shows none, a model its
    family names no complete kit for, and a file that is a companion itself
    by its path."""
    if is_companion_path(path):
        return ()
    if family is not None:
        known = image_families.get(family)
        if known is not None:
            return image_families.kit_of_family(known, path)
    return image_families.kit_of_file(path)


def is_companion_path(path: str) -> bool:
    """Whether the path itself says the file is a companion — a LoRA, a VAE,
    a ControlNet, a text encoder of its own."""
    lower = path.lower()
    return any(word in lower for word in _COMPANION_WORDS)


def parts_in_folder(folder: Path, model: str) -> tuple[image_families.KitPart, ...]:
    """The parts of a model that lies in the folder: its family from its own
    header, its name where the header says none. A LoRA or a ControlNet,
    told by its header, has none."""
    family, companion = bildinhalt.file_family(folder / model)
    if companion:
        return ()
    return kit_parts(model, family)


def _in_kit(folder: Path, model: str, field: str, name: str) -> bool:
    return any(part.part == field and part.name == name for part in parts_in_folder(folder, model))


def offered(folder: Path, field: str) -> list[str]:
    """The files the picture side offers for this field."""
    return bildrunner.vaes(folder) if field == "vae" else bildrunner.textversteher(folder)


def tie(
    repositories, folder: Path, model: str, field: str, name: str, *, keep_own: bool = False
) -> None:
    """Writes ``name`` as the model's part for ``field``, and at every other
    model in the folder whose kit names the same file and that has none.
    ``keep_own`` leaves a part the named model already carries; the other
    models always keep theirs."""
    bildmodellwerte.set_part(repositories, model, field, name, keep_own=keep_own)
    if not _in_kit(folder, model, field, name):
        return
    for other in bildrunner.modelle(folder):
        if other != model and _in_kit(folder, other, field, name):
            bildmodellwerte.set_part(repositories, other, field, name, keep_own=True)


def tie_offered(repositories, folder: Path, model: str) -> None:
    """Writes at a model every part of its kit that the picture side offers
    already — what a model that has just arrived finds lying there. A part
    the model carries by then stays."""
    for part in parts_in_folder(folder, model):
        if part.name in offered(folder, part.part):
            bildmodellwerte.set_part(repositories, model, part.part, part.name, keep_own=True)
