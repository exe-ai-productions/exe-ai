"""The arrow under the chat's last answer, as the service reads it.

Two requests name an answer instead of bringing a turn of their own
(app/api/v1/schemas.py, ``GenerierungAnfrage``):

* ``replaces`` — a new answer is written on the history WITHOUT the named
  row. The row stays stored for as long as the new answer is being written
  and goes in the very step that stores the new one as finished; a new
  answer that fails or is stopped is dropped instead, and the named row
  stands as it was.
* ``retries`` — the model call a failed answer died in is asked again, in
  the same row, with everything the run had already done.

Which of the two a press means is decided by how the run behind the answer
ended, and that is read here once, for the route and for the tests alike.
"""

from __future__ import annotations

FAILED = "fehler"
RUNNING = "laeuft"


def run_state(row) -> str | None:
    """How the run behind an answer ended.

    The column, and the metrics blob where the column is empty: an answer
    stored before the column existed says it only there. The window reads a
    row the same way (frontend/src/teile/Nachricht.svelte), so the arrow and
    the service agree on which answer is a failed one.
    """
    if row.zustand:
        return row.zustand
    stats = row.stats or {}
    if stats.get("fehler"):
        return FAILED
    if stats.get("abgebrochen"):
        return "abgebrochen"
    return None


def named_answer(repositories, chat_id: str, message_id: str):
    """The row a request names — where it is the chat's last answer.

    Only the last one: an answer further up has turns behind it that were
    written with it in the history. ``None`` for every other id, a row of
    another chat and a row that is no answer included.
    """
    row = repositories.messages.last_answer(chat_id=chat_id)
    if row is None or row.id != message_id:
        return None
    return row


def replaceable(row) -> bool:
    """Whether a new answer may take this one's place: a finished or a
    stopped one. A running answer is still being written, and a failed one
    is asked again where it stands instead."""
    return run_state(row) not in (RUNNING, FAILED)
