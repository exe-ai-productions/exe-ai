"""Ends a run when the model keeps hitting the same wall.

Three consecutive rejections of the very same call — same tool, same
arguments — mean the model has not understood why it was refused. Left
alone, it burns rounds against a wall it cannot read; even a strong model
loses whole rounds this way instead of doing the run's actual work, and an
unattended job has nobody there to notice and redirect it.

Only rejected calls (Tor 3's own ``nein``, ``app/berechtigungen.py``)
count — a call that fails for some other reason is a different problem with
a different shape, and mixing the two would end a run that was still making
real progress elsewhere.
"""

from __future__ import annotations

import json


class Schleifenwaechter:
    """One running count of the same call, rejected back to back."""

    GRENZE = 3

    def __init__(self) -> None:
        self._letzter: str | None = None
        self._anzahl = 0

    def aufruf(self, name: str, argumente: dict, *, abgelehnt: bool) -> bool:
        """Records the outcome of one tool call. Returns ``True`` once the
        identical call has now been rejected three times in a row — the
        run should end.

        Anything else breaks the streak: a call that was allowed, or a
        rejected one with a different name or different arguments. Only
        the exact same refusal, repeated without change, counts up."""
        if not abgelehnt:
            self._letzter = None
            self._anzahl = 0
            return False
        schluessel = f"{name}:{json.dumps(argumente, sort_keys=True, ensure_ascii=False)}"
        if schluessel == self._letzter:
            self._anzahl += 1
        else:
            self._letzter = schluessel
            self._anzahl = 1
        return self._anzahl >= self.GRENZE
