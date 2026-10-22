"""Helpers — work the chat's model hands off without an agent set up for it.

Handing work off used to need an agent file: ``start_job`` named one, and
without one there was nobody to hand anything to. A helper is the other
way, the one delegating agents elsewhere take: the model states the goal
and what the helper needs to know, and a run starts with no file behind it.
Fixed agents stay for roles of their own and for schedules.

What a helper is, is fixed here and nowhere else:

* **The chat's tools, minus five.** It may not ask the user (``ask_user``):
  a question from a run nobody set up would stand in the box beside the
  chat's own; when it needs something from the user it ends and says so,
  and the chat's model asks. It may not write the memory, which every chat
  shares, nor schedule work in somebody's name (``cronjob``, ``cron_note``),
  nor start further runs (``start_job``) — a helper is one level deep.
* **Two limits, in the settings once:** how many helpers may run at the
  same time, and how many tool rounds one of them may take. The shipped
  values are 10 at once and 250 rounds.
* **A name, not a file.** Its runs carry :data:`HELPER_NAME` as their agent,
  so the job list, the reports and a continuation after a full context all
  work as for any other run; the name is kept free of agent files for that.
"""

from __future__ import annotations

from typing import Any

from app import einstellungswahl
from app.agenten import HELPER_NAME, Agent
from app.tools import (
    auftrag_werkzeug, cron_notiz, cronjob, frage_werkzeug, job_werkzeug, memory,
)

BLOCKED_TOOLS = frozenset({
    frage_werkzeug.WERKZEUG_NAME,
    memory.WERKZEUG_NAME,
    cronjob.WERKZEUG_NAME,
    cron_notiz.WERKZEUG_NAME,
    auftrag_werkzeug.WERKZEUG_NAME,
    job_werkzeug.WERKZEUG_NAME,
})
# What a scheduled run with no agent is not offered: the same list without
# the schedule's note. The note is the run's own — it belongs to the entry
# that fired it and is read by that entry's next run — so a run nobody
# attends keeps it, where a helper (which has no entry) does not.
BLOCKED_WITHOUT_AGENT = BLOCKED_TOOLS - {cron_notiz.WERKZEUG_NAME}

AT_ONCE_KEY = "helpers_at_once"
AT_ONCE_DEFAULT = 10
STEPS_KEY = "helper_steps"
STEPS_DEFAULT = 250

# Not "a permission" among what a helper has to stop for: a call of its own
# that needs the user's yes is asked about in the chat that started it, or
# refused where nobody can be asked, and the run's own prompt says which
# (app/grundprompt.py, AGENTENLAUF).
PROMPT = (
    "You are a helper. The model of a chat handed you one piece of work, "
    "the task below, and you do it on your own with the tools you have.\n\n"
    "You cannot ask the user anything. When you need something only the "
    "user can give — a choice or a missing fact — stop there, and say in "
    "your report exactly what you need and why. The chat's model reads your "
    "report and asks the user.\n\n"
    "When you are done, write a short report: what you did, what came of "
    "it, and where any result is. The report is all the chat gets back."
)


# What a run is told when it reaches for what a helper may not do. Neither
# tool is offered to a helper; these answer a call made anyway, because a
# tool that is not offered must still not run.
NO_QUESTIONS = (
    "A helper cannot ask the user questions. Stop here and state in your report what you need "
    "from the user and why. The chat's model will ask them."
)
NO_FURTHER_RUNS = (
    "A helper cannot start additional runs. Complete the work yourself, or state in your "
    "report which tasks still need to be delegated."
)
NOT_FOR_HELPERS = (
    "A helper cannot update memory or schedule tasks. State in your report what should be "
    "remembered or scheduled; the chat's model will handle it."
)
CHAT_ONLY = "Specify an agent. A helper can only be started from a chat."
# The same tools but the note, answered for a scheduled run with no agent
# (app/no_agent.py): it is not offered them either, and nobody is there.
NOT_FOR_RUNS_WITHOUT_AGENT = (
    "A scheduled run without an agent cannot ask the user questions, update memory, schedule "
    "tasks, or start additional runs. State what is needed in your response."
)


def is_helper(name: str | None) -> bool:
    """Whether runs under this agent name are helpers."""
    return isinstance(name, str) and name.strip().casefold() == HELPER_NAME


def refused_call(agent_name: str | None, tool_name: str) -> str | None:
    """Why this run may not make this call, or None. Only a helper and a
    scheduled run with no agent are refused anything here, and only the
    tools they are not offered — whatever the rule file says."""
    from app import no_agent

    if no_agent.is_no_agent(agent_name):
        return NOT_FOR_RUNS_WITHOUT_AGENT if tool_name in BLOCKED_WITHOUT_AGENT else None
    if tool_name not in BLOCKED_TOOLS:
        return None
    if not is_helper(agent_name):
        return None
    if tool_name == frage_werkzeug.WERKZEUG_NAME:
        return NO_QUESTIONS
    if tool_name == auftrag_werkzeug.WERKZEUG_NAME:
        return NO_FURTHER_RUNS
    return NOT_FOR_HELPERS


def limit_check(value: Any) -> int | None:
    """Either limit: a whole number of at least one, or nothing."""
    return einstellungswahl.ganze_zahl_ab_eins(value)


def at_once(repositories) -> int:
    return einstellungswahl.aufgeloest(
        repositories, AT_ONCE_KEY, limit_check, AT_ONCE_DEFAULT
    )


def steps(repositories) -> int:
    return einstellungswahl.aufgeloest(
        repositories, STEPS_KEY, limit_check, STEPS_DEFAULT
    )


def limit_reached(repositories) -> dict[str, int] | None:
    """How many helpers run and how many may, when no further one may start
    now; None when one may. The two numbers are what the refusal's sentence
    names (see ``limit_key``)."""
    limit = at_once(repositories)
    running = repositories.auftraege.open_count(agent=HELPER_NAME)
    if running < limit:
        return None
    return {"running": running, "limit": limit}


def limit_key(running: int, limit: int) -> str:
    """The catalogue key of the refusal's sentence for these two numbers.

    The sentence names both, and each is bent on its own: one helper "is"
    running, several "are"; one "may", several "may" — a verb and a noun
    that differ in the two languages. So there is one text for each way the
    two can stand, the plain one for the many.
    """
    if running == 1 and limit == 1:
        return "jobs.helper_limit_both_one"
    if running == 1:
        return "jobs.helper_limit_running_one"
    if limit == 1:
        return "jobs.helper_limit_limit_one"
    return "jobs.helper_limit"


def helper_agent(repositories, registry) -> Agent:
    """The helper as a run sees it — built fresh for every start, so a tool
    switched on or off since is right the next time."""
    names = registry.namen() if registry is not None else []
    return Agent(
        name=HELPER_NAME,
        prompt=PROMPT,
        werkzeuge=[name for name in names if name not in BLOCKED_TOOLS],
        runden=steps(repositories),
    )


def agent_named(name: str, agenten, repositories, registry) -> Agent | None:
    """The agent a stored name stands for: the helper, the run with no agent
    (app/no_agent.py), or a file's agent."""
    from app import no_agent

    if is_helper(name):
        return helper_agent(repositories, registry)
    if no_agent.is_no_agent(name):
        return no_agent.agent(registry)
    return agenten.get(name)
