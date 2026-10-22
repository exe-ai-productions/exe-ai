"""The two doors of a model server's chat template row: make the copy and open
it in the text editor, and show the file in the file manager.

The model server and the agent server each have a router and each hands its
own runner in; what happens is the same, so it is written once here. The body
names a model only by its file name, and only a name the runner lists is
taken — never a path from outside.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import HTTPException, Request, status
from pydantic import BaseModel, Field

from app import chat_template_copy
from app.i18n import t
from app.modellrunner import Modellrunner
from app.ordner_oeffnen import OeffnenNichtMoeglich, open_file_in_editor, show_file


class TemplateRequest(BaseModel):
    modell: str = Field(min_length=1, max_length=200)


class TemplatePath(BaseModel):
    pfad: str


def _model_file(runner: Modellrunner, model: str, language: str) -> Path:
    if model not in {m.name for m in runner.modelle()}:
        raise HTTPException(status.HTTP_404_NOT_FOUND, t("fehler.runner_kein_modell", language))
    return runner.ordner / model


def edit(request: Request, runner: Modellrunner, model: str, language: str) -> TemplatePath:
    """Makes the copy of the model's template (or finds the one made before)
    and opens it in the text editor; answers where it lies."""
    model_file = _model_file(runner, model, language)
    try:
        copy = chat_template_copy.ensure_copy(request.app.state.config, model, model_file)
    except chat_template_copy.TemplateError as fehler:
        lage = (
            status.HTTP_422_UNPROCESSABLE_ENTITY
            if fehler.reason == "keine_vorlage"
            else status.HTTP_404_NOT_FOUND
        )
        raise HTTPException(lage, t(f"fehler.chat_template_{fehler.reason}", language)) from None
    try:
        open_file_in_editor(copy)
    except OeffnenNichtMoeglich:
        raise HTTPException(
            status.HTTP_501_NOT_IMPLEMENTED, t("fehler.editor_oeffnen", language)
        ) from None
    return TemplatePath(pfad=str(copy))


def reveal(request: Request, runner: Modellrunner, model: str, language: str) -> bool:
    """Shows the copy of the template in the file manager, or the model file
    where there is no copy yet."""
    model_file = _model_file(runner, model, language)
    try:
        show_file(chat_template_copy.file_to_show(request.app.state.config, model, model_file))
    except OeffnenNichtMoeglich:
        raise HTTPException(
            status.HTTP_501_NOT_IMPLEMENTED, t("fehler.ordner_oeffnen", language)
        ) from None
    return True
