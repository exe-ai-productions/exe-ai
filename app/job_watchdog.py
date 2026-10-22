"""The watchdog for the runs a chat sent off.

A run that gives no sign of life for 450 seconds is ended as failed, with the
reason ``kein_fortschritt`` — "made no further progress" — and the chat gets
its report like after any ending. The case it exists for: a model server that
takes a request and never answers (the second of two helpers started in the
same second sat on its first request for good), where the run would stay
under the active jobs until somebody stopped it by hand.

What counts as a sign of life is decided where the run lives
(``Generierung``, app/generationen.py): every piece the model's stream
delivers — text, thinking, a tool call, readings — and the start and the end
of a tool. A bare keepalive of the provider is no piece. The reading of the
clock is in memory only: after a restart the service ends what was running
anyway (``dienst_neustart``).

Three things never wake it:

* **A tool at work.** What a tool may take is the tool's own limit and the
  stop button's business (a command has no ceiling, a picture no deadline) —
  the silence of the model meanwhile says nothing.
* **A run that waits for the user.** A question, or a call the chat would ask
  about, stands there for as long as the person takes.
* **Every run that nobody sent off from a chat.** A schedule's run, a run the
  user started in the start window and a run another run started have their
  own ways to end; the watchdog looks at the runs ``start_job`` made — and at
  the continuations of those: a run that handed its work on is still the same
  work, and what carries it on is watched like the run it carries on.

The limit is fixed: no setting, no variable. A test shortens it by passing
its own.
"""

from __future__ import annotations

import logging
import time

log = logging.getLogger(__name__)

# The ending the run records and the report names (``jobs.grund.*``).
REASON = "kein_fortschritt"
SILENCE_LIMIT_SECONDS = 450.0


def check(
    repositories,
    generierungen,
    *,
    now: float | None = None,
    limit: float = SILENCE_LIMIT_SECONDS,
) -> list[str]:
    """One pass over the open runs a chat sent off. Returns the IDs it ended.

    A run that waits, or has a tool at work, has its clock held at "now" while
    it does — so the silence is counted from the moment it goes on, not from
    the last piece before it stopped to wait.
    """
    # Imported here: the jobs module imports this one for the reason it
    # records.
    from app.api.v1.auftraege import stop_job

    now = time.monotonic() if now is None else now
    ended: list[str] = []
    for job in repositories.auftraege.open_sent_off():
        run = (
            generierungen.holen(job.generation_id) if job.generation_id else None
        )
        if run is None or run.fertig.is_set() or run.soll_abbrechen:
            continue
        if job.zustand != "laeuft" or run.tools_running or run.bestaetigungen:
            run.last_sign = now
            continue
        silence = now - run.last_sign
        if silence < limit:
            continue
        log.warning(
            "Job %s gave no sign of life for %d s and is ended",
            job.id,
            int(silence),
            extra={"ereignis": "auftrag_wachhund", "job": job.id},
        )
        stop_job(repositories, generierungen, job, reason=REASON)
        ended.append(job.id)
    return ended
