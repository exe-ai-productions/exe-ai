"""Keeping the machine awake for the duration of a job.

Not a code bug, but it kills an overnight run just as reliably as one: the
Mac goes to sleep, and whatever was running dies with it. ``caffeinate`` is
macOS's own answer to exactly this. Started once when the first job of the
moment begins and stopped once none are left running, so two jobs at once
do not race to end it under each other.

Windows carries no equivalent today (the project's other supported
platform) — asking for one there is a silent no-op rather than an error a
job would otherwise fail on.
"""

from __future__ import annotations

import logging
import sys
# Bound directly rather than kept as `subprocess.Popen` — a test faking
# this one module's process out (tests/conftest.py) would otherwise patch
# the same shared `subprocess` module every other caller reaches through
# too, breaking their own Popen calls along with it.
from subprocess import Popen

from app.no_console import no_window

log = logging.getLogger(__name__)

_prozess: Popen | None = None
_laeufende_auftraege = 0


def sicherstellen() -> None:
    """One more job needs the machine to stay awake."""
    global _prozess, _laeufende_auftraege
    _laeufende_auftraege += 1
    if _prozess is not None or sys.platform != "darwin":
        return
    try:
        # -i: no idle sleep, -m: no disk sleep, -s: no system sleep on AC —
        # the combination that actually keeps an unattended Mac running,
        # not just its screen lit.
        _prozess = Popen(["caffeinate", "-ims"], **no_window())
    except OSError:
        log.warning(
            "caffeinate not found — the computer may fall asleep during the run"
        )


def freigeben() -> None:
    """One job is done needing it — ends caffeinate once nothing else does."""
    global _prozess, _laeufende_auftraege
    _laeufende_auftraege = max(0, _laeufende_auftraege - 1)
    if _laeufende_auftraege > 0 or _prozess is None:
        return
    _prozess.terminate()
    _prozess = None
