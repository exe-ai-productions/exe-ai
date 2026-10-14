"""What an agent started from a chat leaves in that chat when it is done.

The chat that handed the work off gets the report back, and the model is
woken to tell the user in its own words what came of it
(``app/hintergrundwecken.py``). The report itself goes in as a row the model
reads and the reader does not — a ``werkzeugmeldung``, the kind a finished
background command writes (``app/hintergrundmeldung.py``). The reader sees
the model's summary, not the raw report: a long report standing in the chat
would be exactly the card the chat is meant to keep out.

Only the run a chat started reports back. A run another run started reports
to that run, as it always did, and a run that handed its work on has not
ended (``app/auftragsende.py`` announces neither).

Like the background report, this hangs in at startup: the job run itself can
write no message and start no answer.
"""

from __future__ import annotations

import logging
from typing import Any, Callable

from app import i18n
from app.api.v1.generierung import WERKZEUGERGEBNIS_GRENZE
from app.db import Repositories
from app.db.models import Auftrag
from app.events import Ereignisse, bus

log = logging.getLogger(__name__)

# What the model is told about how the run ended, in its own language.
_ENDINGS = {
    "fertig": "finished",
    "gescheitert": "failed",
    "abgebrochen": "was stopped",
    "unterbrochen": "was cut off",
}


def _reason_text(grund: str) -> str:
    """The stored identifier as a sentence the model can read.

    Everything the provider itself said stands behind ``fehler:`` — that
    text travels on, because a rewritten error hides what really happened.

    Every other ending is translated from the catalogue, the same block the
    job list shows in the window's language (``jobs.grund.*``, read in
    app/cronmeldung.py and frontend/src/lib/auftragsmelder.js): the stored
    value is a short identifier, and a second table of sentences here would
    be a copy that can only fall behind it.
    """
    if grund.startswith("fehler:"):
        return f"the run failed: {grund.split(':', 1)[1].strip()}"
    schluessel = f"jobs.grund.{grund}"
    satz = i18n.t(schluessel, i18n.STANDARDSPRACHE)
    if satz == schluessel:
        # An ending this program does not know: say that much rather than
        # hand the model a key.
        return "the run ended without a stated reason"
    return satz

# What this module has hung on the bus, so a second lifecycle in the same
# process takes the first one's subscriber off again (the reason is spelled
# out at `_abonnenten` in app/hintergrundwecken.py).
_subscribers: list = []


def report_text(auftrag: Auftrag) -> str:
    """The report as the model reads it: who, how it ended, the task, and
    what the agent wrote."""
    ending = _ENDINGS.get(auftrag.zustand, auftrag.zustand)
    lines = [f"[Agent '{auftrag.agent}' {ending} — job {auftrag.id}]"]
    if auftrag.zustand != "fertig" and auftrag.ende_grund:
        lines.append(f"Reason: {_reason_text(auftrag.ende_grund)}")
    lines.append(f"Task: {auftrag.auftrag}")
    report = (auftrag.ergebnis or "").strip()
    # The ceiling a tool result has in the chat: the report is, in the end,
    # what the start_job call came back with.
    if len(report) > WERKZEUGERGEBNIS_GRENZE:
        report = (
            report[:WERKZEUGERGEBNIS_GRENZE]
            + "\n[The report continues; the full report is available in the agents view.]"
        )
    lines.append("")
    lines.append(f"Report:\n{report}" if report else "The agent did not provide a report.")
    return "\n".join(lines)


def anmelden(
    repositories: Repositories,
    wecken: Callable[[str], Any] | None = None,
) -> None:
    """From now on every job a chat started reports back into that chat."""
    for old in _subscribers:
        bus.abbestellen(Ereignisse.AUFTRAG_BEENDET, old)
    _subscribers.clear()

    def ended(auftrag_id: str = "", **_rest: Any) -> None:
        from app.api.v1.auftraege import work_origin

        auftrag = repositories.auftraege.holen(auftrag_id)
        if auftrag is None or not auftrag.chat_id or auftrag.eltern_id:
            return
        # The continuation of a run under another run is still that run's
        # part of the work, and reports where it did.
        origin = work_origin(repositories, auftrag.cronjob_id)
        if origin is not None and origin.eltern_id:
            return
        # A chat deleted while its agent ran stopped the agent and took its
        # rows along; there is nobody left to tell.
        if repositories.chats.holen(auftrag.chat_id) is None:
            return
        try:
            repositories.messages.speichern(
                chat_id=auftrag.chat_id,
                role="assistant",
                content=report_text(auftrag),
                art="werkzeugmeldung",
                stats={
                    "werkzeuge": [
                        {
                            "name": "start_job",
                            "server": "shell",
                            "argumente": {"agent": auftrag.agent, "task": auftrag.auftrag},
                            "fehlgeschlagen": auftrag.zustand != "fertig",
                            "auftrag_id": auftrag.id,
                        }
                    ]
                },
            )
        except Exception:  # noqa: BLE001 - a lost report must not take the service with it
            log.exception("Report of job %s could not be put into its chat", auftrag.id)
            # And no wake: the answer would read a history without the report.
            return
        log.info(
            "Job %s reported back to chat %s",
            auftrag.id,
            auftrag.chat_id,
            extra={"ereignis": "auftrag_bericht_im_chat", "chat": auftrag.chat_id},
        )
        if wecken is not None:
            wecken(auftrag.chat_id)

    _subscribers.append(ended)
    bus.abonnieren(Ereignisse.AUFTRAG_BEENDET, ended)
