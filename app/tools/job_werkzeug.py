"""The job tool — list and stop the runs a chat started with ``start_job``.

``start_job`` hands work to a helper or a named agent and the model hears
nothing until the report comes back. Without this tool it cannot see whether
a run is still going, so it polls the folder and works the task itself while
the run is still at it, and it cannot end one, so it advises restarting the
program. The tool gives it the two things the window already has: the list
of what is running, and the stop button.

Two rules carry it, both fixed in code:

* **Only this chat's own runs.** A run of another chat, a run a schedule
  fired and a run the user started in the start window are not the model's
  to see or to stop; asking for one is answered as if it did not exist. A
  run another run started stops with the run above it, never by name.
* **One job is one piece of work.** A run whose context fills up hands its
  work on to a continuation, a run of its own under an entry of its own. The
  list shows the work once, under the ID ``start_job`` named, and ``stop``
  with that ID ends the continuation that is running — or switches off the one
  that has not started — and retires the chain.
* **The stop is the stop button's.** The same code ends the run and
  everything it started, and the report ("was stopped") returns to the chat
  like any other ending.

Like ``start_job`` the tool belongs to a chat: a run is never offered it
(app/helper.py), and the registry itself executes nothing — the chat run
hands the call its own world (app/api/v1/generierung.py).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable

from app.db.models import Auftrag, Cronjob
from app.tools.mcp_client import MCPWerkzeug

SERVER_NAME = "shell"
WERKZEUG_NAME = "job"
ACTIONS = ("list", "stop")

# How much of a task the list shows. The model wrote it a moment ago; the
# first words are enough to tell the runs apart.
_TASK_CHARS = 160

_STATES = {
    "laeuft": "running",
    "wartet": "waiting for an answer",
    # A run whose context filled up hands its work on; until the continuation
    # starts, the work is in this state.
    "unterbrochen": "handed on to a continuation that starts shortly",
}

# The registry-level refusal, the last bolt rather than the rule: the call
# reaches the registry only where no chat stood in between.
ONLY_IN_A_CHAT = "job works on the jobs of a chat. No chat is available here."


class JobRefused(Exception):
    """The call cannot be carried out, and the reason says why — English
    prose, because the reader is a model."""


def werkzeug_beschreibung() -> MCPWerkzeug:
    return MCPWerkzeug(
        name=WERKZEUG_NAME,
        beschreibung=(
            "Shows or ends the background jobs that this chat started with start_job — "
            "helpers and named agents.\n"
            "action 'list' shows every such job that is still open: its ID, who runs it, its "
            "state, how long it has been running and the last tool it called. A job's report "
            "arrives in this chat by itself when it ends; until then do not check folders, "
            "do not wait with commands and do not do its work yourself — call 'list' to see "
            "where it stands.\n"
            "action 'stop' ends the job with the given ID, and everything it started, the way "
            "the stop button does. Its report, marked as stopped, then comes into this chat. "
            "Use it when the user asks to stop or cancel a job, or when a job has clearly gone "
            "wrong.\n"
            "Jobs of other chats, scheduled jobs and jobs the user started themselves are not "
            "visible here and cannot be stopped with this tool."
        ),
        schema={
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": list(ACTIONS),
                    "description": "'list' shows the open jobs of this chat, 'stop' ends one.",
                },
                "id": {
                    "type": "string",
                    "description": (
                        "The job ID, as start_job and 'list' name it. Required for 'stop'."
                    ),
                },
            },
            "required": ["action"],
        },
        server=SERVER_NAME,
    )


def started_by_chat(job: Auftrag, chat_id: str) -> bool:
    """Whether this run is one the chat's model sent off with ``start_job``:
    it carries the chat, and no run and no schedule stands above it."""
    return (
        job.chat_id == chat_id
        and not job.eltern_id
        and not job.cronjob_id
    )


@dataclass
class _Work:
    """One piece of work the chat sent off. A run whose context fills up hands
    its work on to a continuation, which is a run of its own under an entry of
    its own — but the work stays what ``start_job`` named: the ID of the run it
    began with."""

    head: Auftrag
    # The run that is going now: the head, or the newest open continuation;
    # None while a continuation is on the clock and has not started.
    current: Auftrag | None
    # The continuation entries still switched on.
    entries: list[Cronjob]


def _chain_entries(repositories: Any, head_id: str) -> list[Cronjob]:
    return [e for e in repositories.cronjobs.aktive() if e.ursprung_id == head_id]


def _work_of(repositories: Any, head: Auftrag) -> _Work | None:
    """The work of this head, or None when nothing of it is going any more."""
    if head.zustand in ("laeuft", "wartet"):
        return _Work(head, head, [])
    runs = repositories.auftraege.open_chain_runs(head.id)
    entries = _chain_entries(repositories, head.id)
    if not runs and not entries:
        return None
    return _Work(head, runs[-1] if runs else None, entries)


def _head_of(repositories: Any, job: Auftrag | None, chat_id: str) -> Auftrag | None:
    """The run of this chat the given one belongs to — itself, or the run a
    continuation carries on (the report of a continuation names the
    continuation's own ID) — or None for anything that is not the chat's."""
    if job is None:
        return None
    if started_by_chat(job, chat_id):
        return job
    if job.eltern_id or not job.cronjob_id:
        return None
    entry = repositories.cronjobs.holen(job.cronjob_id)
    if entry is None or not entry.ursprung_id:
        return None
    origin = repositories.auftraege.holen(entry.ursprung_id)
    return origin if origin is not None and started_by_chat(origin, chat_id) else None


def _runtime(created_at: str, now: datetime) -> str:
    try:
        began = datetime.fromisoformat(created_at)
    except ValueError:
        return "unknown"
    if began.tzinfo is None:
        began = began.replace(tzinfo=timezone.utc)
    seconds = max(0, int((now - began).total_seconds()))
    minutes, rest = divmod(seconds, 60)
    return f"{minutes}m {rest:02d}s" if minutes else f"{rest}s"


def _task_excerpt(text: str) -> str:
    one_line = " ".join(text.split())
    if len(one_line) > _TASK_CHARS:
        return one_line[:_TASK_CHARS].rstrip() + " …"
    return one_line


def _list_jobs(repositories: Any, chat_id: str, now: datetime) -> str:
    works = [
        work for head in repositories.auftraege.sent_off_of_chat(chat_id)
        if (work := _work_of(repositories, head)) is not None
    ]
    if not works:
        return "No jobs started from this chat are open."
    ids = [i for w in works for i in {w.head.id, (w.current or w.head).id}]
    last_tools = repositories.auftraege.last_tool_calls(ids)
    lines = [f"{len(works)} open job(s) started from this chat:"]
    for w in works:
        now_run = w.current or w.head
        last_tool = last_tools.get(now_run.id) or last_tools.get(w.head.id)
        lines.append(
            f"- ID {w.head.id} · {w.head.agent} · {_STATES.get(now_run.zustand, now_run.zustand)} · "
            f"running for {_runtime(w.head.created_at, now)} · "
            f"last tool: {last_tool or 'none yet'} · task: {_task_excerpt(w.head.auftrag)}"
        )
    return "\n".join(lines)


def _stop(
    repositories: Any, chat_id: str, job_id: str, stop: Callable[[Auftrag], None]
) -> str:
    head = _head_of(
        repositories, repositories.auftraege.holen(job_id) if job_id else None, chat_id
    )
    if head is None:
        raise JobRefused(
            f"No job with ID '{job_id}' was started from this chat. Call 'list' to see "
            "the IDs of its jobs."
        )
    work = _work_of(repositories, head)
    if work is None:
        return f"Job {head.id} is already over ({head.zustand}); nothing to stop."
    # The chain first: a continuation switched off cannot start again, and a
    # run that ends without handing its work on retires its own entry anyway.
    for entry in work.entries:
        repositories.cronjobs.aktiv_setzen(entry.id, False)
    if work.current is None:
        # Nothing runs: the work was handed on and the continuation has not
        # started. No run ends, so no report would come — the work ends here.
        repositories.auftraege.zustand_setzen(head.id, "abgebrochen", ende_grund="benutzer_abbruch")
        return (
            f"Job {head.id} had been handed on to a continuation that had not started yet. The "
            "continuation is switched off and will not start; no further report will come."
        )
    stop(work.current)
    return (
        f"Job {head.id} is being stopped, with everything it started. It ends within "
        "moments, and its report, marked as stopped, will come into this chat by itself."
    )


def execute(
    arguments: dict[str, Any],
    *,
    repositories: Any,
    chat_id: str,
    stop: Callable[[Auftrag], None],
    now: datetime | None = None,
) -> str:
    """The answer to a ``list`` or ``stop`` call. ``stop`` ends one run the
    way the stop button does (``stop_job``, app/api/v1/auftraege.py) — handed
    in because that module imports the chat run that calls this one."""
    action = str(arguments.get("action") or "").strip()
    if action not in ACTIONS:
        raise JobRefused(f"'action' must be one of: {', '.join(ACTIONS)}.")
    if action == "list":
        return _list_jobs(repositories, chat_id, now or datetime.now(timezone.utc))
    return _stop(repositories, chat_id, str(arguments.get("id") or "").strip(), stop)
