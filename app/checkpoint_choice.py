"""Whether snapshots are taken before the model changes files.

It ships off: a snapshot copies the person's folder into the program's data
folder, and nobody should find that happening without having asked for it.
The one switch is global — a chat or a model has no snapshots of its own.
"""

from __future__ import annotations

from typing import Any

KEY = "checkpoints"

# A set of one flag, stored as a dict on purpose: the settings route discards
# a falsy value as "unset", so a bare ``False`` could not be told apart from
# "never set" (the same shape as the picture metadata switch).
DEFAULT: dict[str, bool] = {"enabled": False}


def check_switch(wert: Any) -> dict[str, bool]:
    """The one switch, checked before it is stored: only the known key
    survives, as a real boolean."""
    if not isinstance(wert, dict):
        return {}
    return {name: bool(wert[name]) for name in DEFAULT if name in wert}


def enabled(repositories) -> bool:
    """Whether the model's file changes are snapshotted."""
    held = repositories.einstellungen.zusammengefuehrt(KEY, vorgabe=dict(DEFAULT))
    if not isinstance(held, dict):
        held = dict(DEFAULT)
    return bool(held.get("enabled", DEFAULT["enabled"]))
