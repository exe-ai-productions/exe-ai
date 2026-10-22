"""The edited copy of the chat template a model file carries.

A model file holds its chat template (the Jinja text that turns a chat into
the words the model was trained on) inside its header. To change it, the user
needs a file: the first time they ask, the template is copied out of the model
file into the program's data folder, next to no other model's copy, and the
engine is told to read that file instead (`--chat-template-file`, see
``app/feineinstellungen.py``). The copy is the user's from then on: asking
again opens the same file, it is never written over.
"""

from __future__ import annotations

from pathlib import Path

from app import ggufmtp
from app.config import Config

FOLDER = "chat_templates"


class TemplateError(Exception):
    """``reason`` is ``keine_vorlage`` (the model file carries none) or
    ``nicht_lesbar`` (the model file cannot be read)."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def copy_path(config: Config, model: str) -> Path:
    """Where the copy of this model's template lies, there or not. One file
    per model file, named after it — a name that came through the model list,
    never a path of the caller's."""
    return config.datenverzeichnis / FOLDER / f"{model}.jinja"


def ensure_copy(config: Config, model: str, model_file: Path) -> Path:
    """The copy of the template of ``model_file``, made from it when there is
    none yet and left as it is when there is one."""
    copy = copy_path(config, model)
    if copy.is_file():
        return copy
    try:
        template = ggufmtp.chat_template(model_file)
    except OSError:
        raise TemplateError("nicht_lesbar") from None
    if template is None:
        raise TemplateError("keine_vorlage")
    copy.parent.mkdir(parents=True, exist_ok=True)
    # Written as it stands in the model: no line ending of this system.
    with open(copy, "w", encoding="utf-8", newline="") as datei:
        datei.write(template)
    return copy


def file_to_show(config: Config, model: str, model_file: Path) -> Path:
    """What "show in the file manager" points at: the copy where there is
    one, else the model file the template is in."""
    copy = copy_path(config, model)
    return copy if copy.is_file() else model_file
