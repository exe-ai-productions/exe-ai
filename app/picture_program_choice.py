"""Which variant of the picture program the user picked.

On Windows the program comes in four builds (CPU, CUDA, Vulkan, …) that can
lie side by side, each in a folder of its own. Which one runs used to be the
highest build number among all of them — so a newer build of a variant nobody
asked for pushed the picked one out, and picking changed nothing.

The pick is stored once, for everybody (``GLOBAL``), when a fetch of a
variant is asked for. The folders on disk then keep to it
(``app/sddownload._chosen_build_folder``); with none of the picked variant on
disk — a fetch that failed, a folder somebody removed — the former rule
holds. Nothing picked is nothing stored.
"""

from __future__ import annotations

from typing import Any

from app.sddownload import gueltige_variante

KEY = "bildprogramm_fassung"


def check_choice(value: Any) -> dict[str, Any] | None:
    """Keeps a known variant, drops the rest. ``None`` deletes the entry."""
    if not isinstance(value, dict):
        return None
    variant = value.get("variante")
    if not isinstance(variant, str) or not gueltige_variante(variant):
        return None
    return {"variante": variant}


def picked(repositories: Any) -> str | None:
    """The variant picked, or nothing. Read per call: a pick holds for the
    very next start of the program."""
    from app.db.repositories.einstellungen import GLOBAL

    kept = check_choice(repositories.einstellungen.holen(GLOBAL, KEY))
    return kept["variante"] if kept else None


def remember(repositories: Any, variant: str) -> None:
    """Stores the pick. An unknown variant is not stored."""
    from app.db.repositories.einstellungen import GLOBAL

    kept = check_choice({"variante": variant})
    if kept is not None:
        repositories.einstellungen.setzen(GLOBAL, KEY, kept)
