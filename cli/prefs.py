"""What the client remembers between two starts.

One small JSON file in the user's home: the look, the language and the
address of the service. Nothing of it lives in the service's database — the
choice belongs to this terminal, the way the window keeps its look in the
browser.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

# What every start reads, and what each entry may hold besides ``None``:
# the three choices are words — the look falls back to the default look,
# the language to the system's and the address to the one the service
# listens on out of the box — and ``keys`` maps the address of a service
# that demanded a password to the key it handed out, so the next start
# does not ask again. ``None`` means nothing was chosen yet.
KINDS: dict[str, type] = {"look": str, "language": str, "url": str, "keys": dict}
DEFAULTS: dict[str, Any] = {key: None for key in KINDS}


def default_path() -> Path:
    return Path.home() / ".exe-ai" / "cli.json"


def load(path: Path | None = None) -> dict[str, Any]:
    """The remembered choices with the defaults behind them.

    A missing file, a file that is no JSON object and a known choice of the
    wrong kind all read as "not chosen". Entries this module does not know
    are kept as they are — they belong to whoever wrote them.
    """
    values = dict(DEFAULTS)
    try:
        stored = json.loads((path or default_path()).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return values
    if not isinstance(stored, dict):
        return values
    for key, value in stored.items():
        if key in KINDS and not (value is None or isinstance(value, KINDS[key])):
            continue
        values[key] = value
    return values


def save(values: Mapping[str, Any], path: Path | None = None) -> None:
    """Writes the choices. The file is replaced in one step, so a start that
    reads while another one writes never meets half a file."""
    target = path or default_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    draft = target.with_name(target.name + ".tmp")
    draft.write_text(
        json.dumps(dict(values), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    os.replace(draft, target)


def remember(path: Path | None = None, **choices: Any) -> dict[str, Any]:
    """Stores the given choices beside the ones already remembered and
    returns what is remembered now."""
    values = load(path)
    values.update(choices)
    save(values, path)
    return values
