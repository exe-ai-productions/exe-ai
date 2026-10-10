"""The schedule's note tool — ``cron_note``.

When a script finishes, it is finished. When a scheduled run finishes, it
usually has to remember what it did, for the next run. Without that, the
10:15 look into the inbox knows nothing of what the 10:00 look saw: it
reports the same mail again, or cannot tell "new" from "old" at all.

Four decisions, each made against something:

* **A note per entry, not the global memory.** ``app/tools/memory.py`` writes
  the file that travels with every single request (``app/gedaechtnis.py``) —
  rules and facts about the user. A schedule parking its inbox position
  there would flood that file with run state, and every chat would carry it
  around forever. This note belongs to one entry, is read by that entry's
  next run and by nothing else — with one exception, and it is the same
  entry seen twice: a run that overflowed carries the work on in a
  continuation entry, and what that continuation notes down is the state of
  the original job, so it is written on the original as well (see
  ``ausfuehren``).
* **Replaced, never appended.** The note is fed back into the task text of
  every future run. One that grew by a line per run would crowd out the task
  itself within a day of minute-by-minute checking. There is no append
  action, and there is nothing to grow: the model writes the whole note it
  wants the next run to have, or an empty one to drop it.
* **The model writes it, the program does not.** The obvious alternative was
  to feed the previous run's ``ergebnis`` in. That text is a report written
  for a person; deciding which half of it was state would be guessing. What
  the program contributes instead is the one thing it knows for certain and
  the model cannot: the timestamp of the previous run (see
  ``app/cronablauf.py``), which answers "since when is new new" without any
  model involvement at all.
* **Offered only in a cron-fired run.** A chat has no entry a note could
  belong to, so the tool would be an offer that cannot be taken — the
  "sentence about nothing" the base prompt exists to avoid. The run's own
  entry id comes from the run (``app/api/v1/auftraege.py``), never from the
  model's arguments: the note is stored against whichever entry actually
  fired, and no call can aim it at somebody else's.

Too long is refused, not trimmed — the same choice the memory and goal tools
make. A model whose 4000-character note came back trimmed would learn that
4000 is fine and keep writing them; one that is told the number learns the
size of the thing it is keeping.
"""

from __future__ import annotations

import logging
import unicodedata
from typing import Any

from app.tools.mcp_client import MCPWerkzeug

log = logging.getLogger(__name__)

# The schedule's own server: this note belongs to the cron entry the
# ``cronjob`` tool creates, and grouping it anywhere else would make it look
# like a second, unrelated mechanism in the tools window.
SERVER_NAME = "cronjob"
WERKZEUG_NAME = "cron_note"

# Room for a real working state -- a handful of ids, a last-seen marker, a
# short list of what was already dealt with -- and not a line more. Every
# character of this is read back into the opening message of every future
# run of this entry, so the limit is the price of each run, not just of the
# row.
MAX_LAENGE = 2000

# Newline and tab are the only control characters a note can legitimately
# carry. The rest of the "invisible" Unicode categories is either a
# formatting trick (zero-width joiners, direction overrides, a BOM) or a
# control code with no business in stored text. Deliberately the same rule
# as the schedule's task text (``app/tools/cronjob.py``) and the goal report
# (``app/tools/ziel_werkzeug.py``), and for a sharper reason than either: a
# web page this run read could otherwise plant an invisible standing
# instruction that is handed to every future run of this entry.
# WHOEVER CHANGES ONE READS THE OTHERS.
_STEUERZEICHEN_ERLAUBT = {"\n", "\t"}
_UNSICHTBARE_KATEGORIEN = {"Cf", "Cc", "Co", "Cs"}

GESPEICHERT = "Note saved. The next run of this entry will be given it."
GELOESCHT = "Note cleared. The next run of this entry starts without one."

# Said here because the registry says it for a call that reached it from a
# chat, where there is no entry for a note to belong to.
NUR_IM_LAUF = (
    "cron_note only works in a run started by a schedule — there is no "
    "entry here for a note to belong to."
)


class NotizVerboten(Exception):
    """The call was refused — nothing was stored or changed."""


def werkzeug_beschreibung() -> MCPWerkzeug:
    return MCPWerkzeug(
        name=WERKZEUG_NAME,
        beschreibung=(
            "Keeps one short note on this schedule, for your own next run "
            "of it. If an earlier run left a note, you were given it in the "
            "task text above, with the time it was written.\n"
            "Write down what the next run needs in order to tell new from "
            "old: the last thing you saw and how it is identified — the id "
            "of the newest mail, the timestamp you got up to, what you have "
            "already reported. Not a diary of what you did.\n"
            "Every call REPLACES the whole note; there is no appending. So "
            "write the note you want to find next time, in full. Calling it "
            "with an empty 'note' clears it.\n"
            f"At most {MAX_LAENGE} characters — a longer call is refused, "
            "not shortened."
        ),
        schema={
            "type": "object",
            "properties": {
                "note": {
                    "type": "string",
                    "description": (
                        "The complete new note, replacing whatever was "
                        "there. Empty clears it."
                    ),
                },
            },
            "required": ["note"],
        },
        server=SERVER_NAME,
    )


def _bereinigt(text: str) -> str:
    """Strips invisible/format/control characters — kept: an ordinary
    newline or tab, and everything a person could actually see."""
    return "".join(
        zeichen
        for zeichen in text
        if zeichen in _STEUERZEICHEN_ERLAUBT
        or unicodedata.category(zeichen) not in _UNSICHTBARE_KATEGORIEN
    ).strip()


def notiz(argumente: dict[str, Any]) -> str | None:
    """The note as it would be stored, or ``None`` for "clear it".

    Public so a caller that wants to know what a call means does not have to
    clean the text a second time and get a slightly different answer.

    Refuses rather than trims: see the module docstring.
    """
    text = _bereinigt(str(argumente.get("note") or ""))
    if len(text) > MAX_LAENGE:
        raise NotizVerboten(
            f"Too long ({len(text)} characters, at most {MAX_LAENGE}). "
            "A note is the state the next run needs, not a transcript of "
            "this one. Nothing was stored — the previous note still stands."
        )
    return text or None


async def ausfuehren(
    argumente: dict[str, Any], repo, cronjob_id: str | None
) -> str:
    """Replaces this entry's note. Returns what the model is told about it.

    ``cronjob_id`` comes from the run, never from the arguments — the same
    reason the shared folders and the chat id do not (``app/tools/registry.py``):
    anything the model can pass, the model can forge, and a note aimed at
    another entry would be a note in somebody else's next run.
    """
    if repo is None or not cronjob_id:
        raise NotizVerboten(NUR_IM_LAUF)

    text = notiz(argumente)
    eintrag = repo.holen(cronjob_id)
    if eintrag is None:
        # The entry was deleted while its own run was still going. Nothing
        # to write to, and saying "saved" would be a lie about a row that no
        # longer exists.
        raise NotizVerboten(
            "This schedule no longer exists — the note was not stored."
        )
    repo.notiz_setzen(cronjob_id, text)
    # A run whose context filled up hands the rest of its work to a fresh
    # entry, and that continuation is what writes the note from then on. The
    # state it describes is the state of the ORIGINAL job, though — so it is
    # written there too. Left on the continuation alone, the entry a person
    # made would fire again still holding the note from before the handoff,
    # look at the same mails once more, and report them a second time. The
    # continuation is thrown away when the job is done; the original is what
    # keeps running.
    if eintrag.ursprung_id:
        repo.notiz_setzen(eintrag.ursprung_id, text)
    log.info(
        "Cron note %s: %s",
        "cleared" if text is None else "set",
        text or "",
        extra={
            "ereignis": "cron_notiz_gesetzt",
            "cronjob": cronjob_id,
            "ursprung": eintrag.ursprung_id,
            "zeichen": len(text or ""),
        },
    )
    return GESPEICHERT if text is not None else GELOESCHT
