"""The note a model is told when its previous reply was stopped.

A stopped reply stays in the history as far as it got, and read back it looks
like a finished one: the model takes up the next turn as if it had said all it
meant to. So the turn that follows a stopped reply goes out with one bracketed
line in front of the user's words, the way a spoken reply cut short already
does (``app/diktatsprachewahl.py``, ``UNTERBRECHUNGSHINWEIS``) — and by the
same way: it travels with that one request in front of the newest user turn
(``app/verlaufsbau.py``, the instruction a request carries) and is never
stored, so neither the history nor the window ever shows it.

What was stopped is read from what is stored, not remembered anywhere new: a
chat's answer row ends in the state "abgebrochen", and so does a job run.
"""

from __future__ import annotations

STOP_NOTE = "[Note: the user stopped your previous response before it finished.]"


# The ending a job run records when a person pressed its stop
# (app/api/v1/auftraege.py). A run the system ended — its parent stopped, its
# chat deleted — records a reason of its own.
USER_STOP = "benutzer_abbruch"


def previous_reply_stopped(previous) -> bool:
    """Whether ``previous`` — the model's reply right before the new turn,
    or None where there is none — was stopped by the USER before it
    finished.

    Only the model's own answer counts: a background run's report or a
    picture stored after it is the service talking, and a turn that follows
    one of those does not follow the stopped reply directly.

    Only a stop of the user's, read from what is stored. A job run records
    why it ended (``ende_grund``), and only the stop button's reason counts.
    A chat answer records nothing like it, but a stopped answer ends with its
    own closing write, which marks its figures stopped (``stats``
    "abgebrochen"); an answer the service found unfinished at its start was
    set to "abgebrochen" without one (app/db/repositories/messages.py,
    ``beim_start_aufraeumen``) — the system's ending, not the user's.
    """
    if previous is None or getattr(previous, "zustand", None) != "abgebrochen":
        return False
    if (getattr(previous, "art", None) or "nachricht") != "nachricht":
        return False
    if hasattr(previous, "ende_grund"):
        return getattr(previous, "ende_grund", None) == USER_STOP
    stats = getattr(previous, "stats", None) or {}
    return stats.get("abgebrochen") is True


def with_stop_note(prefix: str | None, stopped: bool) -> str | None:
    """``prefix`` — what already goes in front of the newest user turn, or
    None — with the stop note in front of it where the previous reply was
    stopped."""
    if not stopped:
        return prefix
    return f"{STOP_NOTE}\n\n{prefix}" if prefix else STOP_NOTE
