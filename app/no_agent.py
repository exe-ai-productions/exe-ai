"""A scheduled task that names no agent: the model that runs unattended,
with no agent file behind it.

Marked the way a script or a reminder entry is marked: the ``agent`` column
carries a name no agent file can have — brackets appear in no agent name —
so every place that asks "which agent runs this" meets a value that is
plainly not one, and the table needs no second column.

The run is built in memory for every start, so a tool switched on or off
since counts the next time. It gets every approved tool except the ones
nobody is there to answer or that would let it multiply: asking the user,
the memory, scheduling and starting further runs — the list a helper is held
to (app/helper.py), but for the schedule's own note, which it keeps. It names
no folders, and none are added for it — neither the dock nor the picture
folder a run otherwise gets — so the file tools stay shut, as for any agent
that names none. The rule file applies as it always does.
"""

from __future__ import annotations

from app.agenten import Agent

NAME = "(none)"


def is_no_agent(name: str | None) -> bool:
    return name == NAME


def agent(registry) -> Agent:
    """The run as it starts: no prompt of its own, the tools above."""
    # Imported here: app/helper.py resolves stored names through this
    # module, and a top-level import would make the two a circle.
    from app.helper import BLOCKED_WITHOUT_AGENT

    names = registry.namen() if registry is not None else []
    return Agent(
        name=NAME,
        prompt="",
        werkzeuge=[name for name in names if name not in BLOCKED_WITHOUT_AGENT],
    )
