"""The moment a job run is over, written down and announced — once.

Three places end a run: the cancel route and the run loop
(app/api/v1/auftraege.py), and the script half of a schedule
(app/cronablauf.py). All three wrote the ending straight into the table
through ``zustand_setzen``, which is the repository's job and says nothing
to anybody. The table was therefore the only witness, and the only way to
learn that a run had ended was to keep asking for the list.

So the ending goes through here instead. The row is written exactly as
before, and the event is the addition: whoever wants to know the moment
subscribes to it rather than polling for it.

Two rules decide whether an ending is announced, and both exist so that one
piece of work reports itself once:

  * **An ending is an end state.** ``zustand_setzen`` also carries a run
    from ``wartet`` to ``laeuft``; nothing is announced for that. Only the
    states in ``ENDZUSTAENDE`` count, and only when the run was not already
    in one of them — a second write of the same ending announces nothing.

  * **Handing the work on is not an ending.** A run whose context filled up
    or whose provider stopped answering ends ``unterbrochen`` and puts the
    rest of the work on the clock as a continuation
    (app/zwischenstand.py) — the work is still going. Announcing those
    would make a chain of ten links say "finished" ten times. The one
    ``unterbrochen`` that IS an ending is the sweep at service start, whose
    reason is ``dienst_neustart``: nothing was handed anywhere, the run was
    cut off.

The second rule is the same distinction the interface draws in
frontend/src/lib/laufstand.js, and it is written down twice on purpose —
once per side of the wire, because neither side can import the other's.
"""

from __future__ import annotations

from app.api.v1.schemas import werk_von
from app.db import Repositories
from app.db.models import Auftrag
from app.db.repositories.auftraege import ENDZUSTAENDE
from app.events import Ereignisse, bus

# The reason that marks the one interrupted run nobody handed on: the sweep
# that runs at service start (``beim_start_aufraeumen``,
# app/db/repositories/auftraege.py).
GRUND_DIENST_NEUSTART = "dienst_neustart"


def weitergereicht(zustand: str, ende_grund: str | None) -> bool:
    """Did this run hand its work on instead of ending it?"""
    return zustand == "unterbrochen" and ende_grund != GRUND_DIENST_NEUSTART


def beenden(
    repositories: Repositories,
    auftrag_id: str,
    zustand: str,
    *,
    ende_grund: str | None = None,
    ergebnis: str | None = None,
) -> Auftrag | None:
    """Writes the ending and announces it. Returns the row, as the
    repository does — ``None`` when the job is gone."""
    vorher = repositories.auftraege.holen(auftrag_id)
    auftrag = repositories.auftraege.zustand_setzen(
        auftrag_id, zustand, ende_grund=ende_grund, ergebnis=ergebnis
    )
    if auftrag is None:
        return None
    if _meldenswert(vorher, auftrag):
        _melden(repositories, auftrag)
    return auftrag


def _meldenswert(vorher: Auftrag | None, nachher: Auftrag) -> bool:
    if nachher.zustand not in ENDZUSTAENDE:
        return False
    # Already over before this write: whatever ended it announced it then.
    if vorher is not None and vorher.zustand in ENDZUSTAENDE:
        return False
    return not weitergereicht(nachher.zustand, nachher.ende_grund)


def _melden(repositories: Repositories, auftrag: Auftrag) -> None:
    eintrag = (
        repositories.cronjobs.holen(auftrag.cronjob_id) if auftrag.cronjob_id else None
    )
    bus.veroeffentlichen_ohne_warten(
        Ereignisse.AUFTRAG_BEENDET,
        auftrag_id=auftrag.id,
        # The piece of work, not the link: a restart chain answers with the
        # entry it started from, so ten links share one work.
        work_id=werk_von(auftrag, eintrag),
        agent=auftrag.agent,
        ausgang=auftrag.zustand,
        grund=auftrag.ende_grund,
        ergebnis=auftrag.ergebnis,
    )
