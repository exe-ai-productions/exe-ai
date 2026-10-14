"""The job tool — `start_job`.

The chat can now send an agent off: the model names an agent and writes the
task, and a job run starts — the same run the start window creates, with the
agent's own tools, folders and clocks.

Two rules carry this tool, both fixed in code on purpose:

* **The task format lives in the description**, not in a setting. The agent
  never saw the conversation, so the task has to stand alone — a model that
  is not told this writes "do the thing we discussed" and the run burns its
  minutes on guessing.
* **Sending an agent off never asks.** The run starts the moment the model
  calls the tool, as handing work to a subagent commonly does; what
  the agent then does is judged call by call (app/berechtigungen.py) with
  its own tools, but under the mode and rules of the chat it was sent from
  (``berechtigungsmodus_chat``), as a subagent works in its main session's
  mode: a call that chat would ask about is asked about in it, and one
  nobody answers within the usual wait is refused alone while the run goes
  on. A run started by hand or by a schedule keeps the agent's own mode
  (``berechtigungsmodus_agent``). The call is the chat's: a job run starts a
  child only as part of its own assignment, and the registry refuses
  everywhere else.
"""

from __future__ import annotations

import unicodedata
from typing import Any

from app import agentenname, zwischenstand
from app.task_images import MAX_IMAGES
from app.tools.mcp_client import MCPWerkzeug

SERVER_NAME = "shell"
WERKZEUG_NAME = "start_job"

# Newline and tab are the only control characters a task text can
# legitimately carry. The rest of the "invisible" Unicode categories is
# either a formatting trick (zero-width joiners, direction overrides, a BOM)
# or a control code with no business in a stored text. Deliberately the same
# rule as the schedule's task text (``app/tools/cronjob.py``), the schedule's
# note (``app/tools/cron_notiz.py``) and the goal report
# (``app/tools/ziel_werkzeug.py``). WHOEVER CHANGES ONE READS THE OTHERS.
_STEUERZEICHEN_ERLAUBT = {"\n", "\t"}
_UNSICHTBARE_KATEGORIEN = {"Cf", "Cc", "Co", "Cs"}


class AuftragVerboten(Exception):
    """This call cannot start a job, and the reason says why."""


def werkzeug_beschreibung(
    agenten: dict[str, Any] | None = None, *, helpers: bool = False
) -> MCPWerkzeug:
    """``helpers`` is whether this caller may start a helper
    (app/helper.py) — a chat may, a job may not: a helper is one level
    below the chat, never below another run."""
    if helpers:
        who = (
            "Leave out agent to start a helper: it needs no agent set up, "
            "works with this chat's tools and folders, and cannot ask the "
            "user, write the memory, schedule anything or start further "
            "runs — when it needs something from the user, its report says "
            "so and you ask them. Name an agent when one listed fits the "
            "work better; what each one is for stands beside its name.\n"
        )
    else:
        who = ""
    return MCPWerkzeug(
        name=WERKZEUG_NAME,
        beschreibung=(
            "Starts an independent background job that reports back when finished. Use it "
            "when the user wants to delegate research, lengthy file operations, or other work "
            "that should continue independently of the chat.\n"
            + who
            + "The job starts at once with the task as you write it.\n"
            "Write the task so it stands ALONE. The agent never saw this "
            "conversation: no \"the thing we talked about\", no \"it\", no "
            "\"that file\". Name the subject, the goal, and where the result "
            "belongs. Two to four sentences. Write it out in full even when "
            "the user only muttered half a sentence — turning that into a "
            "complete task is your job."
        ),
        schema={
            "type": "object",
            "properties": {
                "agent": {
                    "type": "string",
                    # The names as they stand on disk, same as the schedule
                    # tool's list: no prompt anywhere names an agent, so a
                    # schema without them makes every call a guess — and a
                    # wrong guess comes back with nothing but its own word.
                    **({"enum": sorted(agenten, key=str.casefold)} if agenten else {}),
                    "description": (
                        "The agent's name, exactly as it is listed."
                        + (" Omit it to start a helper." if helpers else "")
                        + (
                            f" Available: {agentenname.auswahl_satz(agenten)}."
                            if agenten
                            else ""
                        )
                    ),
                },
                "task": {
                    "type": "string",
                    "description": (
                        "The complete, self-contained task: subject, goal, and destination "
                        "for the result."
                    ),
                },
                "context": {
                    "type": "string",
                    "description": (
                        "Optional. Additional context needed for the task: facts from this "
                        "conversation, file paths, previous attempts, and constraints."
                    ),
                },
                # Offered to a chat only: the pictures a run needs come
                # from the conversation it never saw, and a run starting a
                # part of its own assignment has none of those.
                **({"images": {
                    "type": "array",
                    "items": {"type": "string"},
                    "maxItems": MAX_IMAGES,
                    "description": (
                        f"Optional. Up to {MAX_IMAGES} images needed for the task: file paths "
                        "within this chat's shared folders, http(s) URLs, or data:image URLs. "
                        "Images accompany the task; models without image support receive a "
                        "text reference to each image instead."
                    ),
                }} if helpers else {}),
            },
            "required": ["task"] if helpers else ["agent", "task"],
        },
        server=SERVER_NAME,
    )


def _bereinigt(text: str) -> str:
    """Strips invisible/format/control characters — kept: an ordinary
    newline or tab, and everything a person could actually see."""
    return "".join(
        zeichen
        for zeichen in text
        if zeichen in _STEUERZEICHEN_ERLAUBT
        or unicodedata.category(zeichen) not in _UNSICHTBARE_KATEGORIEN
    ).strip()


def geprueft(argumente: dict[str, Any]) -> tuple[str, str]:
    """Agent name and task as the run is given them. The
    name is empty where none was given — a helper, where the caller allows
    one (app/helper.py); the caller refuses it where not.

    The task goes through ``ohne_ablagebloecke`` on the way out. This is the last door raw model prose has into a task text: the
    schedule's own tool scrubs it (``app/tools/cronjob.py``,
    ``_aufgabe_bereinigt``), the handoff scrubs status and original task
    (``app/zwischenstand.py``), and note and goal are scrubbed at firing time
    (``app/cronablauf.py``) — this one was not.

    What it costs: the debt block is how a run tells its continuation which
    deliveries it still owes the agent dock, and it is meant to be something
    only the program can write. A model that writes the heading and its
    sentence into the task it hands an agent makes that run open owing a file
    nobody ever recorded — it delivers everything asked of it and still ends
    ``ablage_gescheitert``.

    Scrubbed HERE, at the source, and deliberately not in the run
    (``auftrag_anstossen`` with ``cronjob_id is None``): what the USER pastes
    into the start window is not model prose. Somebody putting a
    continuation text in there means the debt, and it stays owed.

    Invisible characters come out FIRST, and the order is what makes the
    scrub above hold at all (02.09.). The block is recognised by its heading
    and its sentence read LITERALLY, so one zero-width character inside the
    heading walks a forged block straight past ``ohne_ablagebloecke`` and
    onto the row — measured, verbatim, with the character invisible to
    anybody reading the task.

    What that costs is not the phantom debt of the paragraph above, and
    saying so is the point: ``offene_ablagen_lesen`` reads the heading just
    as literally, so a block nobody can repair is a block nobody reads
    either. What survives is the SENTENCE — "deliver each one again with
    deliver_file, under the same name, before you finish" — sitting in the
    task an agent is handed, an instruction this program never wrote, aimed
    at a file nobody ever recorded. The scrub belongs before the check for
    the same reason the schedule's own tool puts it there
    (``app/tools/cronjob.py``, ``_aufgabe_bereinigt``), and a task text is
    worth cleaning of invisible characters on its own account anyway — the
    same rule the note and the goal report already follow.
    """
    agent = str(argumente.get("agent") or "").strip()
    task = zwischenstand.ohne_ablagebloecke(
        _bereinigt(str(argumente.get("task") or ""))
    ).strip()
    context = zwischenstand.ohne_ablagebloecke(
        _bereinigt(str(argumente.get("context") or ""))
    ).strip()
    if not task:
        raise AuftragVerboten("No task provided.")
    # One text, as the run is given it, the context included.
    if context:
        task = f"{task}\n\nContext:\n{context}"
    return agent, task


# The registry-level refusal, and it is the LAST bolt rather than the rule.
# Two callers start a job and both do it before the call reaches the
# registry: a chat starts it in its own world, and a job run starts the
# child under itself — a part of its own assignment. So reaching this
# sentence means neither stood in between: a call with no chat and no
# assignment behind it at all.
NUR_IM_CHAT = (
    "start_job starts a job from a chat or as part of an existing job's assignment. Neither "
    "context is available here."
)
