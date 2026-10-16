"""``/memory`` and ``/system``: the two long texts the service keeps — what
the model remembers and the instructions it is given — read, edited in the
text editor and saved again.

Both are the same walk with different addresses and sentences, so there is
one function and two descriptions.
"""

from __future__ import annotations

from dataclasses import dataclass

from cli import editor
from cli.client import ServiceError
from cli.interfaces import Context


@dataclass(frozen=True)
class Document:
    """A long text of the service: where it lives and what is said about it
    once it is saved, emptied, or refused."""

    path: str
    saved: str
    cleared: str
    refused: str


MEMORY = Document(
    "/memory",
    "gedaechtnis.gesichert",
    "gedaechtnis.geleert",
    "gedaechtnis.nicht_gesichert",
)
SYSTEM = Document(
    "/system-prompt",
    "systemprompt.gesichert",
    "systemprompt.geleert",
    "systemprompt.nicht_gesichert",
)


def run_command(ctx: Context, document: Document) -> None:
    answer = ctx.client.get(document.path)
    current = answer.get("text") if isinstance(answer, dict) else None
    edited = editor.edit(ctx, current if isinstance(current, str) else "")
    if edited is None:
        # Nothing came back: sending the old text again would overwrite
        # whatever was written into the file in the meantime.
        return
    try:
        ctx.client.put(document.path, json={"text": edited})
    except ServiceError:
        ctx.renderer.error(ctx.texts.t(document.refused))
        return
    ctx.renderer.notice(ctx.texts.t(document.saved if edited.strip() else document.cleared))
