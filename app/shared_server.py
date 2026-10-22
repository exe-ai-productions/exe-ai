"""The server of ANOTHER service on this data folder, as the window shows it.

A second service on one data folder starts and ends no model server (see
``Modellrunner.shared_with``); it uses the one the first service holds. The
five server windows would then say "off" for a server that is running, so what
is shown for a server this service does not hold comes from the server itself:
``GET /health`` answers 200 once the model is loaded and 503 while it loads (it
is the one route of ``llama-server`` that needs no key — the key is the first
service's own and never leaves it). Nothing answering means off.

What the health route does not say — which model, which window, how many
layers — stands in the note the first service wrote for its server (the same
note the clean-up after a crash reads), and counts only while the port of the
note is the port that answered.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import httpx

log = logging.getLogger(__name__)

# The server is on this machine, so the answer is fast or nothing: a window is
# waiting for this one.
PROBE_SECONDS = 0.5


def answers(port: int, host: str = "127.0.0.1") -> bool:
    """Whether a server is up on this port — loaded (200) or loading (503)."""
    try:
        reply = httpx.get(f"http://{host}:{port}/health", timeout=PROBE_SECONDS)
    except httpx.HTTPError:
        return False
    return reply.status_code in (200, 503)


def note_of(folder: Path, note_name: str, port: int) -> dict:
    """The facts the first service noted for its server, or an empty dict when
    there is no note, it is unreadable, or it names another port."""
    try:
        note = json.loads((folder / note_name).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(note, dict) or note.get("port") != port:
        return {}
    return note


__all__ = ["PROBE_SECONDS", "answers", "note_of"]
