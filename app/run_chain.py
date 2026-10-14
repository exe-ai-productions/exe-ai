"""Which level of a chain of runs a run is on.

A chat sends a run off, and that run may ask for runs of its own: a part of
the work its model was given. That is where it ends. A run another run asked
for is one level below it and is not offered ``start_job`` at all — a chain
of runs each starting the next has no end of its own, and nothing in it is
something somebody confirmed in a window.

The same holds for ``cronjob``: a schedule that run created would start runs
of its own on the clock, with no run above them, and the chain would go on
through time instead of through calls.

Two places read the rule, so it stands once, here: the offer of a run's
tools (``app/api/v1/auftraege.py``, ``auftrag_anstossen``) leaves both tools
out, and the interception of a call made anyway answers it with
:data:`NO_RUN_UNDER_A_RUN` or :data:`NO_SCHEDULE_UNDER_A_RUN`.
"""

from __future__ import annotations

# What a run is told when it reaches for ``start_job`` below another run. The
# tool is not in its list; this answers a call made anyway, because a tool
# that is not offered must still not run. English: only the model reads it.
NO_RUN_UNDER_A_RUN = (
    "This run was started by another run and cannot start further runs. Complete the work "
    "yourself, or state in your report which tasks still need to be delegated."
)


# The same, for ``cronjob``. English: only the model reads it.
NO_SCHEDULE_UNDER_A_RUN = (
    "This run was started by another run and cannot create schedules. Complete the work "
    "yourself, or state in your report which tasks still need to be scheduled."
)


def started_by_a_run(parent_id: str | None, origin) -> bool:
    """Whether a run is the work of another run: another run asked for it
    (``parent_id``), or it continues work that began with such a run
    (``origin``, the run the continuation's work began with, or ``None``).
    The chat's own run and a run nobody's run started — by hand, by a
    schedule — are not, and keep ``start_job``."""
    return parent_id is not None or (origin is not None and origin.eltern_id is not None)
