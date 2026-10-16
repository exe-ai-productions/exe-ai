"""``/agents``: the tasks of the agents — shown, started, followed, stopped,
deleted, and the questions they ask answered.

A task is a run of an agent on its own. The service keeps the list, the
log of every run and its report; the client only shows them and sends the
person's decisions: which agent gets which words, an answer, a stop, a
deletion.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from cli import agent_edit
from cli.client import ServiceError
from cli.interfaces import Context, Entry
from cli.render import clock

# The words behind ``/agents``: one that starts a task in one line, and one
# that opens the agents themselves.
RUN = "run"
EDIT = "edit"

# The states of a task, as the service names them.
WAITING = "wartet"
RUNNING = "laeuft"
DONE = "fertig"
FAILED = "gescheitert"

_STATE_STYLE = {WAITING: "yellow", RUNNING: "blue", DONE: "green", FAILED: "red"}
# What may still be stopped.
_ACTIVE = (WAITING, RUNNING)
# The longest a task's words stand in a row of the list.
_TASK_WIDTH = 70


def run_command(ctx: Context, argument: str) -> None:
    word, _, rest = argument.strip().partition(" ")
    word, rest = word.casefold(), rest.strip()
    if not word:
        _choose(ctx)
    elif word == RUN:
        _run(ctx, rest)
    elif word == EDIT:
        agent_edit.run_command(ctx, rest)
    else:
        ctx.renderer.error(ctx.texts.t("cli.unknown_choice", name=argument.strip()))


# --- The list --------------------------------------------------------------------------


def _one_line(text: str) -> str:
    line = " ".join(text.split())
    return line if len(line) <= _TASK_WIDTH else line[: _TASK_WIDTH - 1] + "…"


def _seconds(stamp: object) -> float | None:
    if not isinstance(stamp, str):
        return None
    try:
        moment = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.timestamp()


def _duration(job: dict[str, Any]) -> str:
    """How long a task has been at it, or took: a running one since it was
    made, a finished one until it was last changed, a waiting one none."""
    state = job.get("state")
    began = _seconds(job.get("created_at"))
    if state == WAITING or began is None:
        return ""
    end = datetime.now(timezone.utc).timestamp() if state == RUNNING else _seconds(job.get("updated_at"))
    return "" if end is None else clock(end - began)


def _state_word(ctx: Context, state: object) -> str:
    return ctx.texts.t(f"jobs.zustand.{state}")


def _row(ctx: Context, job: dict[str, Any]) -> list[tuple[str, str]]:
    state = str(job.get("state") or "")
    return [
        ("text", str(job.get("agent") or "")),
        (_STATE_STYLE.get(state, "muted"), _state_word(ctx, state)),
        ("text", _one_line(str(job.get("task") or ""))),
        ("muted", _duration(job)),
    ]


def _ordered(jobs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The waiting ones first, then the running, then the rest in the order
    the service gave them — as the window lists them."""
    rank = {WAITING: 0, RUNNING: 1}
    return sorted(jobs, key=lambda job: rank.get(str(job.get("state")), 2))


def _choose(ctx: Context) -> None:
    listed = ctx.client.get("/jobs")
    jobs = _ordered([job for job in listed if isinstance(job, dict)]) if isinstance(listed, list) else []
    entries = [Entry(cells=[("text", ctx.texts.t("jobs.starten"))])]
    entries += [Entry(cells=_row(ctx, job)) for job in jobs]
    picked = ctx.asker.choose(entries)
    if picked is None:
        return
    if picked == 0:
        _start_from_selection(ctx)
    else:
        _open(ctx, str(jobs[picked - 1].get("id")))


# --- Starting ----------------------------------------------------------------------------


def _start_from_selection(ctx: Context) -> None:
    agent = _pick_agent(ctx)
    if agent is not None:
        _start(ctx, agent, None)


def _pick_agent(ctx: Context) -> str | None:
    listed = ctx.client.get("/agents")
    agents = [entry for entry in listed if isinstance(entry, dict)] if isinstance(listed, list) else []
    if not agents:
        ctx.renderer.notice(ctx.texts.t("jobs.keine_agenten"))
        return None
    entries = [
        Entry(cells=[("text", str(agent.get("name") or ""))], note=str(agent.get("description") or ""))
        for agent in agents
    ]
    picked = ctx.asker.choose(entries, head=ctx.texts.t("jobs.agent_waehlen"))
    return None if picked is None else str(agents[picked].get("name") or "")


def _run(ctx: Context, rest: str) -> None:
    name, _, task = rest.partition(" ")
    if not name:
        _start_from_selection(ctx)
        return
    _start(ctx, name, task.strip() or None)


def _start(ctx: Context, agent: str, task: str | None) -> None:
    if task is None:
        typed = ctx.asker.ask_text(ctx.texts.t("jobs.aufgabe_platzhalter"))
        task = (typed or "").strip()
        if not task:
            return
    try:
        started = ctx.client.post("/jobs", json={"agent": agent, "task": task})
    except ServiceError as error:
        # The service says which agents there are when it does not know one.
        ctx.renderer.error(error.detail)
        return
    if isinstance(started, dict):
        ctx.renderer.notice("  ".join(text for _, text in _row(ctx, started) if text))


# --- One task ----------------------------------------------------------------------------


def _open(ctx: Context, job_id: str) -> None:
    detail = ctx.client.get(f"/jobs/{job_id}")
    if not isinstance(detail, dict):
        return
    _show_log(ctx, detail)
    state = str(detail.get("state") or "")
    question = detail.get("question")
    if state == WAITING and isinstance(question, dict):
        _answer(ctx, job_id, question)
    _act(ctx, job_id, state)


def _json_object(text: str) -> dict[str, Any] | None:
    try:
        value = json.loads(text)
    except ValueError:
        return None
    return value if isinstance(value, dict) else None


def _show_log(ctx: Context, detail: dict[str, Any]) -> None:
    """The log of a run in the form of the chat: its sentences as the
    answer, its thinking as thinking, a call and its result as a tool line.
    What the run wrote besides — the context readings, its states — stays
    behind."""
    renderer = ctx.renderer
    for step in detail.get("schritte") or []:
        if not isinstance(step, dict):
            continue
        kind = step.get("typ")
        content = str(step.get("inhalt") or "")
        if kind == "text":
            renderer.content(content)
        elif kind == "reasoning":
            renderer.reasoning(content)
        elif kind in ("tool_call", "tool_result"):
            data = _json_object(content)
            if data is None:
                continue
            (renderer.tool_call if kind == "tool_call" else renderer.tool_result)(data)
    state = detail.get("state")
    result = detail.get("result")
    if state not in _ACTIVE and isinstance(result, str) and result.strip():
        renderer.content("\n\n" + result)
    renderer.done({"typ": "done"})
    ctx.screen.set_activity(None)


def _answer(ctx: Context, job_id: str, question: dict[str, Any]) -> None:
    """Puts the question of the run the way the model's question is put in
    a chat. Nothing typed — Esc — is the answer "later": nothing is sent."""
    given = ctx.asker.ask_user(
        {
            "typ": "user_ask",
            "frage": question.get("frage"),
            "optionen": question.get("optionen") or [],
            "aufruf_id": question.get("aufruf_id"),
        }
    )
    text = str((given or {}).get("antwort") or "")
    if not text.strip():
        return
    try:
        ctx.client.post(f"/jobs/{job_id}/answer", json={"antwort": text})
    except ServiceError as error:
        ctx.renderer.error(error.detail)


def _act(ctx: Context, job_id: str, state: str) -> None:
    """What may be done with the task: stop it where it still runs or
    waits, and delete it."""
    texts = ctx.texts
    cancel = state in _ACTIVE
    entries = [Entry(cells=[("text", texts.t("jobs.abbrechen"))])] if cancel else []
    entries.append(Entry(cells=[("text", texts.t("jobs.loeschen"))]))
    picked = ctx.asker.choose(entries)
    if picked is None:
        return
    if cancel and picked == 0:
        ctx.client.post(f"/jobs/{job_id}/cancel")
        return
    sure = ctx.asker.choose(
        [Entry(cells=[("text", texts.t("app.ja"))]), Entry(cells=[("text", texts.t("app.nein"))])],
        head=texts.t("jobs.loeschen_frage"),
    )
    if sure != 0:
        return
    ctx.client.delete(f"/jobs/{job_id}")
    ctx.renderer.notice(texts.t("jobs.geloescht"))
