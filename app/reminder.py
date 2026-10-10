"""The third kind of schedule: a reminder.

An agent entry runs a model, a script entry runs a file, and a reminder runs
nothing at all. When it comes due, the system's own notification shows its
text once, with the sound (app/cronmeldung.py) — no model is loaded and no
answer is written. A reminder is its words and its moment, nothing else.

Marked the way a script entry is marked (``skriptlauf.SKRIPT_AGENT``): the
``agent`` column carries a name no agent file can have, so every place that
asks "which agent runs this" meets a value that is plainly not one, and the
table needs no second column saying the same thing.
"""

from __future__ import annotations

from typing import Any

# Brackets can appear in no agent name — an agent is a file name and the
# interface's own pattern allows none (app/skriptlauf.py, ``SKRIPT_AGENT``) —
# so this collides with nothing.
REMINDER_AGENT = "(reminder)"


KIND_AGENT = "agent"
KIND_SCRIPT = "script"
KIND_REMINDER = "reminder"


def is_reminder(entry: Any) -> bool:
    return getattr(entry, "agent", None) == REMINDER_AGENT


def kind_of(agent: str | None, skript: str | None) -> str:
    """Which of the three kinds an entry — or one of its runs — is, read off
    the two columns that say it: a marker in ``agent``, or a script."""
    from app.skriptlauf import SKRIPT_AGENT

    if agent == REMINDER_AGENT:
        return KIND_REMINDER
    if skript or agent == SKRIPT_AGENT:
        return KIND_SCRIPT
    return KIND_AGENT
