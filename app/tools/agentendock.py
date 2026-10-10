"""The delivery tool — ``deliver_file``.

Puts one file where a run's deliverables land, which the doc folder shows:
the report as a document, a generated picture, whatever the run produced for
the person to keep. Three callers, two places:

* a chat delivers into its own folder, as a document of the chat
  (``app/dokumentablage.py``), and the file hangs on the answer being
  written — the person finds it right where they asked for it;
* a job started from a chat delivers into that chat's folder the same way,
  so the file goes with the chat;
* a job without a chat (a cron entry run on its own) delivers onto the dock
  (``app/agentendock.py``).

Two ways in, exactly one per call:

* ``content`` — text, written as UTF-8. The straight path for reports.
* ``path`` — a file inside the run's shared folders, copied. The path for
  anything binary, like a picture the run produced. Strictly inside the
  share for every caller: a job has nobody to ask, and a chat that wants a
  file from elsewhere reads it with the file tools, which do ask.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app import agentendock as shelf
from app.agentendock import AgentenDock
from app.tools import grenzen
from app.tools.mcp_client import MCPWerkzeug

SERVER_NAME = "dock"
WERKZEUG_NAME = "deliver_file"

# How a run ends whose delivery never arrived. Measured before it
# existed: a run that met the shelf's ceiling was refused, wrote one line into
# its own step log, and then ended "fertig" — with `deliver: 'log'` on a cron
# entry the user was never told the file was gone. The ceiling is gone now,
# but the reasons a delivery can fail are not (a full disk, a file over the
# per-file ceiling, a folder that cannot be written), so the ending stays.
GRUND_NICHT_ABGELEGT = "ablage_gescheitert"


class AblageVerboten(Exception):
    """The call cannot run — wrong caller, bad arguments, or the file could
    not be stored. Whatever the reason: the delivery did not arrive, and the
    run must not end reporting success (see ``GRUND_NICHT_ABGELEGT``)."""


def werkzeug_beschreibung(in_chat: bool = False) -> MCPWerkzeug:
    """``in_chat`` is whose list this goes into. The two callers are told
    two different things because the file lands in two different places: a
    chat's on the answer it is writing, a job's in the doc folder."""
    if in_chat:
        description = (
            "Hands a finished file to the user in this conversation: the "
            "file is kept with the conversation and shown as a card in your "
            "answer, which the user opens with a click. Call it whenever the "
            "user asks you for a file — to write, create, export or send "
            "one — and for any deliverable they will want to keep (a report, "
            "a document, a table, a picture). Do not use it for working "
            "files, and not for a short answer, which belongs in the message "
            "itself.\n"
            "Pass `name` and EITHER `content` OR `path`. `content` is text "
            "and is stored as it is under that name, so it suits text "
            "formats (.md, .txt, .csv, .html, .json); nothing has to be "
            "written to a folder first. A file in any other format (a PDF, a "
            "picture) has to exist already and is passed by `path`, from "
            "inside the folders of this conversation, and is copied as it "
            "is.\n"
            "A file you only write into a folder is not handed over: it gets "
            "no card, and the user has to go looking for it."
        )
        name_hint = "File name shown on the card, e.g. \"report.md\"."
        path_hint = (
            "A file inside the folders of this conversation to copy instead "
            "of passing content."
        )
    else:
        description = (
            "Delivers one file to the user's doc folder, where they find what "
            "a job produced, marked with the agent that delivered it. Use it "
            "for the finished deliverable (a report, a document, a picture), "
            "not for working files.\n"
            "Pass `name` and EITHER `content` (text, written as UTF-8) OR "
            "`path` (a file inside the shared folders, or a picture this job drew, "
            "copied as it is).\n"
            "This is how a job hands something over: a file left in a folder "
            "is a file nobody goes looking for."
        )
        name_hint = "File name shown in the doc folder, e.g. \"report.md\"."
        path_hint = (
            "A file inside the shared folders, or a picture this job "
            "drew, to copy instead of passing content."
        )
    return MCPWerkzeug(
        name=WERKZEUG_NAME,
        beschreibung=description,
        schema={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": name_hint},
                "content": {
                    "type": "string",
                    "description": "The text the file should hold.",
                },
                "path": {"type": "string", "description": path_hint},
            },
            "required": ["name"],
        },
        server=SERVER_NAME,
    )


async def ausfuehren(
    argumente: dict[str, Any],
    dock: AgentenDock,
    ordner: list[str],
    herkunft: str = "chat",
    agent: Any | None = None,
    job: str | None = None,
    data_dir: Any | None = None,
    chat_delivery: Callable[..., Any] | None = None,
    chat: str | None = None,
    answer: str | None = None,
) -> str:
    """``chat_delivery`` keeps the file in a chat (``app/tools/aufbau.py``).
    For a job it is called with the job, the name, the bytes and the agent's
    name, and answers with the document it stored, or ``None`` when the job
    has no chat — then the file goes onto the dock. For a chat's own call it
    is called with ``chat`` and ``answer`` instead: the chat that is asking
    and the answer it is writing, which the document is hung on. Both come
    from the run, never from the model's arguments."""
    in_chat = herkunft == "chat"
    if in_chat:
        # A chat has one place to deliver into, its own. Without it there is
        # nothing this call could do — the dock is the jobs' shelf.
        if chat_delivery is None or not chat:
            raise AblageVerboten(
                "deliver_file has no conversation to deliver into here. Hand "
                "the result to the user in your answer."
            )
    elif herkunft != "agent" or agent is None:
        raise AblageVerboten(
            "deliver_file needs a job or a conversation behind the call, and "
            "this one has neither."
        )
    # Who delivered, for the shelf and the document row. A chat's own file
    # names nobody: it is the conversation's.
    deliverer = "" if agent is None else agent.name

    name = str(argumente.get("name") or "").strip()
    if not name:
        raise AblageVerboten("No name given.")

    inhalt = argumente.get("content")
    pfad = str(argumente.get("path") or "").strip()
    if (inhalt is None) == (not pfad):
        raise AblageVerboten("Pass either 'content' or 'path' — exactly one.")

    if inhalt is not None:
        daten = str(inhalt).encode("utf-8")
    else:
        # Strictly inside the share — a path that leaves the run's folders
        # is simply refused, in a chat as in a job: this tool hands a file
        # over, and asking about a path is the file tools' business.
        try:
            ziel = grenzen.ziel(pfad, ordner, data_dir)
        except grenzen.GrenzeVerletzt as fehler:
            raise AblageVerboten(str(fehler)) from fehler
        if not grenzen.liegt_innerhalb(ziel, grenzen.wurzeln(ordner)):
            raise AblageVerboten(
                f"'{pfad}' lies outside the shared folders — only files "
                "inside the share can be delivered."
            )
        if not ziel.is_file():
            raise AblageVerboten(f"'{pfad}' is not a file.")
        try:
            daten = ziel.read_bytes()
        except OSError as fehler:
            raise AblageVerboten(f"'{pfad}' could not be read ({fehler}).") from fehler

    # Here and not on the shelf: the ceiling is for a run's delivery, and
    # the person drops files through the same shelf without one.
    if len(daten) > shelf.MAX_BYTES:
        raise AblageVerboten(
            f"The file is too large to deliver "
            f"({len(daten):,} bytes, ceiling {shelf.MAX_BYTES:,})."
        )

    if in_chat:
        assert chat_delivery is not None  # refused above otherwise
        try:
            document = chat_delivery(chat=chat, answer=answer, name=name, daten=daten)
        except OSError as error:
            raise AblageVerboten(f"The file could not be stored ({error}).") from error
        if document is None:
            raise AblageVerboten(
                "The file could not be delivered: this conversation no longer exists."
            )
        return (
            f"Delivered '{document.filename}' to the user in this conversation "
            f"({document.size_bytes:,} bytes). It is kept at '{document.pfad}', "
            "and the user sees it as a card in your answer — do not repeat its "
            "content there."
        )

    if chat_delivery is not None and job:
        try:
            dokument = chat_delivery(job=job, name=name, daten=daten, agent=deliverer)
        except OSError as fehler:
            raise AblageVerboten(f"The file could not be stored ({fehler}).") from fehler
        if dokument is not None:
            return (
                f"Delivered '{dokument.filename}' to the doc folder of the chat "
                f"this job was started from ({dokument.size_bytes:,} bytes)."
            )

    # No type is passed on purpose: neither way in carries one — text
    # content has none and a copied file does not hand one over — so the
    # shelf reads it off the name, the same for both branches.
    try:
        eintrag = dock.ablegen(name, daten, agent=deliverer, job=job or "")
    except ValueError as fehler:
        raise AblageVerboten(str(fehler)) from fehler
    except OSError as fehler:
        raise AblageVerboten(f"The file could not be stored ({fehler}).") from fehler

    return (
        f"Delivered '{eintrag['name']}' to the agent dock "
        f"({eintrag['groesse']:,} bytes)."
    )
