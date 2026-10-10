"""The folder check at the start of a tool call — one place for the chat run
and the job run alike.

A tool call is only complete at the end of the model's stream; its argument
may take minutes to arrive (measured: a write_file argument of 32,393
characters streamed for 157 s). The folder check of the file tools does not
depend on that argument at all — whether any folder is shared, and whether
the first of them is still there (``grenzen.ordner_pruefen``, microseconds).
It only checks: it makes no folder, not even a chat's own one that is not
there yet — that one is made when the call runs, and passes the check.
So it runs the moment the call's name arrives, and a call that can only be
refused is cut off there and answered with the reason, instead of being
written out in full first.

Both runs report a call's beginning the same way (the ``tool_call_laeuft``
piece of the providers); this module decides from it, and hands back the
stand-in call that goes into the history in place of the one that was cut.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Iterable
from uuid import uuid4

from app.providers.base import Werkzeugaufruf
from app.tools import agentendock as ablage_werkzeug
from app.tools import dateiwerkzeuge, grenzen, shell

log = logging.getLogger(__name__)


def arbeitet_in_ordnern(name: str) -> bool:
    """Whether a tool resolves its paths against the shared folders — the
    file tools, the shell (whose working directory is the first of them) and
    the delivery tool (which reads its file from them). All of them refuse
    alike when that first folder is missing."""
    return (
        name == shell.WERKZEUG_NAME
        or name == ablage_werkzeug.WERKZEUG_NAME
        or dateiwerkzeuge.modul(name) is not None
    )


def frueh_pruefbar(name: str) -> bool:
    """The tools whose call may be cut off as it begins: the file tools and
    the shell. Not the delivery tool — a refused delivery is booked as a
    file still owed, under the name in its argument, and a call cut off
    before its argument has no name to book."""
    return name == shell.WERKZEUG_NAME or dateiwerkzeuge.modul(name) is not None


def angebotene_namen(werkzeuge: list[dict[str, Any]]) -> set[str]:
    """The tool names a request offers, from its tool list in the
    function-calling shape every provider is handed."""
    return {
        str((w.get("function") or {}).get("name") or "")
        for w in werkzeuge
        if isinstance(w, dict)
    }


class Vorpruefung:
    """The check for one round of one run.

    ``angeboten`` are the tool names this round offers. A call for anything
    else is left alone: it is refused at execution for what it is — a tool
    turned off or not the agent's — and not for the folders.

    ``data_dir`` is the program's data folder, handed in on purpose: it is
    what tells a chat's own folder apart from a folder of the user's, and
    only the user's one is refused here when it is missing.
    """

    def __init__(
        self,
        ordner: list[str] | None,
        angeboten: Iterable[str],
        data_dir: Path | str | None,
    ) -> None:
        self._ordner = list(ordner or [])
        self._angeboten = set(angeboten)
        self._data_dir = data_dir
        self._begonnen: set[Any] = set()
        self._geprueft = False
        # The call that was cut off, as (name, reason), once there is one.
        self.absage: tuple[str, str] | None = None

    def beginnt(self, daten: dict[str, Any]) -> bool:
        """Takes one progress report of the stream. True means: cut the
        stream here — the call it reports cannot work, and ``ersatz`` hands
        back what stands in for it.

        The folders are the same for every call of a round, so they are
        checked once, at the first call that works in them. The stream is
        only cut when that call is the first of the round: a call begun
        before it would be lost with the cut, so then it is left to the
        refusal at execution, as before.
        """
        index = daten.get("index")
        name = str(daten.get("name") or "")
        self._begonnen.add(index)
        if (
            self._geprueft
            or not frueh_pruefbar(name)
            or name not in self._angeboten
        ):
            return False
        self._geprueft = True
        grund = grenzen.ordner_pruefen(self._ordner, self._data_dir)
        if grund is None or len(self._begonnen) > 1:
            return False
        log.info(
            "Tool '%s' refused as its call began, %s characters of its argument "
            "written: %s",
            name, daten.get("zeichen", 0), grund,
        )
        self.absage = (name, grund)
        return True

    def ersatz(self) -> tuple[Werkzeugaufruf, str]:
        """The call as it began — its name, no argument — and the reason it
        is answered with. Only after ``beginnt`` returned True."""
        assert self.absage is not None
        name, grund = self.absage
        return Werkzeugaufruf(id=f"call_{uuid4().hex[:24]}", name=name), grund
