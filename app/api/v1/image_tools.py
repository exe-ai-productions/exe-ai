"""The picture server's tools under "Local": its model files with their
size, converting one to GGUF, collecting an importance matrix, and the
devices sd-cli computes on."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel

from app import model_convert
from app.api.abhaengigkeiten import hole_config, hole_sprache
from app.api.v1.bild import _bildordner, _runner
from app.bildrunner import BildFehler, imatrix_path, modell_pfad, modelle
from app.bildwahlen import WEIGHT_TYPES
from app.config import Config
from app.i18n import t

router = APIRouter(tags=["bild"])


class ModelFile(BaseModel):
    name: str
    size: int
    # An importance matrix is being collected with this file, and one lies
    # beside it already.
    collecting_imatrix: bool
    has_imatrix: bool
    # The weight types a GGUF copy of this file gets smaller in; empty when
    # no copy would (app/model_convert.py).
    convert_types: list[str]


class ConvertWish(BaseModel):
    model: str
    weight_type: str


class ImatrixWish(BaseModel):
    model: str
    on: bool


def _model_path(config: Config, name: str, language: str):
    try:
        return modell_pfad(_bildordner(config), name)
    except BildFehler as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, t(error.grund, language)) from error


@router.get("/bild/model-files", response_model=list[ModelFile], summary="Model files")
def model_files(request: Request, config: Config = Depends(hole_config)) -> list[ModelFile]:
    folder = _bildordner(config).expanduser()
    collecting = _runner(request).imatrix_models
    files = []
    for name in modelle(folder):
        path = folder / name
        files.append(ModelFile(
            name=name, size=path.stat().st_size,
            collecting_imatrix=name in collecting, has_imatrix=imatrix_path(path).is_file(),
            convert_types=list(model_convert.smaller_types(path)),
        ))
    return files


@router.post("/bild/convert", summary="Convert a model file to GGUF")
async def convert(
    wish: ConvertWish, request: Request,
    config: Config = Depends(hole_config), language: str = Depends(hole_sprache),
) -> dict:
    """A new GGUF of the chosen type beside the file; the file itself
    stays. One at a time with the pictures: it holds the one-picture lock,
    and the stop that ends a picture ends it too."""
    if wish.weight_type not in WEIGHT_TYPES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, t("bild.umwandeln_typ", language))
    source = _model_path(config, wish.model, language)
    # Only a smaller copy: never one as large or larger, never 16 bits.
    if wish.weight_type not in model_convert.smaller_types(source):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, t("bild.umwandeln_nicht_kleiner", language)
        )
    runner = _runner(request)
    program = runner.programm
    if program is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, t("bild.kein_programm", language))
    try:
        runner.reservieren()
    except BildFehler as error:
        raise HTTPException(status.HTTP_409_CONFLICT, t(error.grund, language)) from error
    try:
        new = await asyncio.to_thread(
            model_convert.convert, runner, program, source, wish.weight_type,
        )
    except model_convert.ConvertError as error:
        sentence = t(error.reason, language)
        if error.log_text:
            sentence = f"{sentence}\n\n{error.log_text}"
        if error.reason == "bild.abgebrochen":
            # Stopped on request: the same 499 a stopped picture answers with.
            code = getattr(status, "HTTP_499_CLIENT_CLOSED_REQUEST", 499)
        elif error.reason == "bild.umwandeln_da":
            code = status.HTTP_409_CONFLICT
        else:
            code = status.HTTP_503_SERVICE_UNAVAILABLE
        raise HTTPException(code, sentence) from error
    finally:
        runner.freigeben()
    return {"file": new.name}


@router.post("/bild/imatrix", response_model=bool, summary="Generate an importance matrix")
def imatrix(
    wish: ImatrixWish, request: Request,
    config: Config = Depends(hole_config), language: str = Depends(hole_sprache),
) -> bool:
    """While on, every picture drawn with this model file adds to its
    importance matrix; converting it then uses the matrix."""
    _model_path(config, wish.model, language)
    collecting = _runner(request).imatrix_models
    if wish.on:
        collecting.add(wish.model)
    else:
        collecting.discard(wish.model)
    return wish.on


@router.get("/bild/devices", summary="Devices available to sd-cli for computation")
async def devices(request: Request) -> list[dict[str, str]]:
    program = _runner(request).programm
    if program is None:
        return []
    return await asyncio.to_thread(model_convert.devices, program)
