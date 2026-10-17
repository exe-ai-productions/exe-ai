"""``@path`` in a message: a file or an image that goes with it.

A word that begins with ``@`` and names a file that exists — from the
folder the client runs in, ``~`` counted, a blank written as ``\\ `` or the
whole path in double quotes — is attached the way the window attaches: an
image goes to the service as a picture, any other file as a document of the
chat. The ``@path`` stays in the text. What is not a file, or cannot be
attached, is skipped: the message goes out all the same, and the sentence
for why stands above the input field where there is one.

Also here: the completion of a path behind ``@`` and what a dropped file
becomes in the field.
"""

from __future__ import annotations

import os
import re
import shlex
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from pathlib import Path

from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.document import Document

from cli.client import ServiceError
from cli.interfaces import Context

# The kinds of picture the service takes, by ending.
IMAGE_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
}

# An ``@`` at the beginning of a word, then a path: in double quotes, or
# running to the next blank, a blank inside it written with a backslash.
_MENTION = re.compile(r'(?<!\S)@("(?:[^"\\]|\\.)*"|(?:\\.|[^\s\\])+)')
# The beginning of a mention at the end of what stands before the cursor.
_OPEN_MENTION = re.compile(r"(?<!\S)@((?:\\.|[^\s\\\"])*)$")
# What ends a sentence and is no part of a path.
_TRAILING = ".,;:!?)]}"


@dataclass
class Attached:
    """What a message takes along: the names of the pictures the service
    stored, and the ids of the documents it made."""

    images: list[str] = field(default_factory=list)
    documents: list[str] = field(default_factory=list)


def _unescape(raw: str) -> str:
    if len(raw) >= 2 and raw[0] == raw[-1] == '"':
        return re.sub(r"\\(.)", r"\1", raw[1:-1])
    return re.sub(r"\\(.)", r"\1", raw)


def _escape(name: str) -> str:
    """A path as it is written behind ``@``: a blank, a backslash or a quote
    with a backslash before it."""
    return re.sub(r'([\s\\"])', r"\\\1", name)


def _resolve(name: str) -> Path | None:
    """The file the name stands for, relative to the folder the client runs
    in; ``None`` where it is none."""
    path = Path(os.path.expanduser(name))
    if not path.is_absolute():
        path = Path(os.getcwd()) / path
    try:
        return path if path.is_file() else None
    except OSError:
        return None


def _same_file(first: Path, second: Path) -> bool:
    try:
        return first.samefile(second)
    except OSError:
        return False


def mentioned_files(text: str) -> Iterator[Path]:
    """The existing files the words with ``@`` in front of them name, in the
    order they stand. A word that is no file — or an address such as
    ``name@example.com``, whose ``@`` stands inside a word — is none.

    A sentence that ends right behind the path leaves a mark at its end. The
    name without it wins wherever it leads to the same file — Windows reads
    ``note.txt.`` as ``note.txt``, and the ending of the file is what decides
    between a picture and a document, so the file must go under the name that
    carries it. A file whose name really ends in the mark, with no other one
    beside it, is found under its full name.
    """
    for found in _MENTION.finditer(text):
        name = _unescape(found.group(1))
        path = _resolve(name)
        bare = name.rstrip(_TRAILING)
        if bare and bare != name:
            plain = _resolve(bare)
            if plain is not None and (path is None or _same_file(path, plain)):
                path = plain
        if path is not None:
            yield path


def sees(ctx: Context) -> bool:
    """Whether the model in use takes pictures."""
    for entry in ctx.session.models:
        if entry.get("id") == ctx.session.endpoint_id:
            capabilities = entry.get("capabilities")
            return isinstance(capabilities, dict) and bool(capabilities.get("vision"))
    return False


def attach(ctx: Context, text: str, chat_id: str) -> Attached:
    """Attaches every file ``text`` names to the chat, the way the window
    does, and returns what the message takes along. A file that cannot be
    attached is left out and its sentence stands in the notice line."""
    attached = Attached()
    if "@" not in text:
        return attached
    done: set[Path] = set()
    for path in mentioned_files(text):
        if path in done:
            continue
        done.add(path)
        kind = IMAGE_TYPES.get(path.suffix.lower())
        if kind is not None and not sees(ctx):
            ctx.renderer.notice(ctx.texts.t("fehler.kein_vision"))
            continue
        try:
            data = path.read_bytes()
        except OSError as error:
            ctx.renderer.notice(str(error))
            continue
        try:
            if kind is not None:
                answer = ctx.client.upload("/images", data, content_type=kind)
                name = answer.get("bild") if isinstance(answer, dict) else None
                if isinstance(name, str) and name:
                    attached.images.append(name)
            else:
                answer = ctx.client.upload(
                    "/documents", data, params={"chat_id": chat_id, "name": path.name}
                )
                meta = answer.get("dokument") if isinstance(answer, dict) else None
                identifier = meta.get("id") if isinstance(meta, dict) else None
                if isinstance(identifier, str) and identifier:
                    attached.documents.append(identifier)
        except ServiceError as error:
            ctx.renderer.notice(error.detail)
    return attached


# --- The completion behind @ -------------------------------------------------------


class MentionCompleter(Completer):
    """Offers the files and folders behind an ``@`` — from the folder the
    client runs in, from ``~`` or from the root — with a blank written the
    way a mention takes it. It reads the disk; the screen asks for it on a
    thread of its own."""

    def get_completions(self, document: Document, complete_event: object) -> Iterable[Completion]:
        found = _OPEN_MENTION.search(document.text_before_cursor)
        if found is None:
            return
        typed = found.group(1)
        raw = _unescape(typed)
        directory, slash, prefix = raw.rpartition("/")
        if slash and not directory:
            directory = "/"
        base = Path(os.path.expanduser(directory or "."))
        if not base.is_absolute():
            base = Path(os.getcwd()) / base
        # What was typed up to and with the last slash stays as it was.
        kept = typed[: typed.rfind("/") + 1] if "/" in typed else ""
        try:
            with os.scandir(base) as entries:
                listed = sorted(
                    (entry for entry in entries if entry.name.startswith(prefix)),
                    key=lambda entry: (not entry.is_dir(), entry.name.casefold()),
                )
        except OSError:
            return
        for entry in listed:
            if entry.name.startswith(".") and not prefix.startswith("."):
                continue
            suffix = "/" if entry.is_dir() else ""
            yield Completion(
                kept + _escape(entry.name) + suffix,
                start_position=-len(typed),
                display=entry.name + suffix,
            )


# --- A dropped file ------------------------------------------------------------------


def paths_as_mentions(pasted: str) -> str | None:
    """What a pasted text becomes in the field when it consists of nothing
    but paths of existing files — each one written as a mention, a blank
    behind the last. ``None`` for any other text, which stays as it is.

    Only a path that says where it lies (absolute, or ``~``) counts: a
    pasted word that happens to be the name of a file in the folder is
    text."""
    text = pasted.strip()
    if not text:
        return None
    try:
        words = shlex.split(text, posix=os.name != "nt")
    except ValueError:
        return None
    mentions: list[str] = []
    for word in words:
        if os.name == "nt" and len(word) > 1 and word[0] == word[-1] == '"':
            word = word[1:-1]
        if not (word.startswith("~") or os.path.isabs(word)):
            return None
        if _resolve(word) is None:
            return None
        mentions.append("@" + _escape(word))
    return " ".join(mentions) + " "
