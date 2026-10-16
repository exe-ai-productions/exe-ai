"""``/ps``: the commands the model has running in the open chat, shown and
stopped.

The service keeps the runs of a chat and ends one with everything it
started. What is written here is the list of what still runs and the stop
of the one that was picked.
"""

from __future__ import annotations

from typing import Any

from cli.client import ServiceError
from cli.interfaces import Context, Entry

# What a run that is going on says of itself, and the kind that is a picture:
# a picture is not a command.
_RUNNING = "laeuft"
_PICTURE = "bild"


def run_command(ctx: Context, argument: str) -> None:
    word = argument.strip()
    if word and not word.isdecimal():
        ctx.renderer.error(ctx.texts.t("cli.unknown_choice", name=word))
        return
    running = _running(ctx)
    if not running:
        ctx.renderer.notice(ctx.texts.t("cli.ps_none"))
        return
    if word:
        number = int(word)
        if not 1 <= number <= len(running):
            ctx.renderer.error(ctx.texts.t("cli.unknown_choice", name=word))
            return
        _stop(ctx, running[number - 1])
        return
    entries = [
        Entry(
            cells=[
                ("text", " ".join(str(run.get("befehl") or "").split())),
                ("muted", ctx.texts.t("terminal.hintergrund") if run.get("hintergrund") else ""),
            ]
        )
        for run in running
    ]
    picked = ctx.asker.choose(entries)
    if picked is not None:
        _stop(ctx, running[picked])


def _running(ctx: Context) -> list[dict[str, Any]]:
    """The commands of the open chat that are going on, in the service's
    order. A chat the service does not have yet has none: nothing is asked."""
    opened = ctx.session.chat
    if opened is None:
        return []
    found = ctx.client.get(f"/laeufe/{opened['id']}")
    runs = found.get("laeufe") if isinstance(found, dict) else None
    return [
        run
        for run in runs or []
        if isinstance(run, dict) and run.get("zustand") == _RUNNING and run.get("art") != _PICTURE
    ]


def _stop(ctx: Context, run: dict[str, Any]) -> None:
    opened = ctx.session.chat
    if opened is None:
        return
    try:
        ctx.client.post(f"/laeufe/{opened['id']}/{run['lauf']}/stop")
    except ServiceError as error:
        ctx.renderer.error(error.detail)
