"""The picture server's tools under "Local": its model files with their
size and state, converting one to GGUF, the one switch for collecting
importance matrices, and the devices sd-cli computes on."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel

from app import bildgeraete, fp16_convert, model_convert
from app.api.abhaengigkeiten import hole_config, hole_repositories, hole_sprache
from app.api.v1.bild import _bildordner, _runner
from app.bildrunner import BildFehler, imatrix_path, modell_pfad, modelle
from app.bildwahlen import WEIGHT_TYPES
from app.config import Config
from app.db import Repositories
from app.i18n import t

router = APIRouter(tags=["bild"])


class ModelFile(BaseModel):
    name: str
    size: int
    # An importance matrix is being collected for this file: the machine's
    # one switch is on and a matrix lies beside the file, so every sd-cli
    # picture drawn with it adds to that matrix.
    collecting_imatrix: bool
    has_imatrix: bool
    # The weight type of a GGUF file a conversion wrote — the type its name
    # carries, as ``model_convert.target`` names it — or None: the source of
    # a conversion and every other file carry none.
    gguf_type: str | None
    # The weight types a GGUF copy of this file gets smaller in; empty when
    # no copy would (app/model_convert.py).
    convert_types: list[str]
    # Most of the file's weights are BF16: it gets a copy in FP16
    # (app/fp16_convert.py).
    fp16_convertible: bool


class ConvertWish(BaseModel):
    model: str
    weight_type: str


class Fp16Wish(BaseModel):
    model: str


class ImatrixWish(BaseModel):
    on: bool


def _convert_failure(error: model_convert.ConvertError, language: str) -> HTTPException:
    """The answer to a conversion that did not give a file: stopped on
    request, a copy that already lies there, or a failure with its reason."""
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
    return HTTPException(code, sentence)


def _model_path(config: Config, name: str, language: str):
    try:
        return modell_pfad(_bildordner(config), name)
    except BildFehler as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, t(error.grund, language)) from error


@router.get("/bild/model-files", response_model=list[ModelFile], summary="Model files")
def model_files(
    config: Config = Depends(hole_config),
    repositories: Repositories = Depends(hole_repositories),
) -> list[ModelFile]:
    folder = _bildordner(config).expanduser()
    collecting = bildgeraete.lesen(repositories).imatrix
    files = []
    for name in modelle(folder):
        path = folder / name
        has_matrix = imatrix_path(path).is_file()
        files.append(ModelFile(
            name=name, size=path.stat().st_size,
            collecting_imatrix=collecting and has_matrix, has_imatrix=has_matrix,
            gguf_type=model_convert.converted_type(path),
            convert_types=list(model_convert.smaller_types(path)),
            fp16_convertible=fp16_convert.convertible(path),
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
        raise _convert_failure(error, language) from error
    finally:
        runner.freigeben()
    return {"file": new.name}


@router.post("/bild/convert-fp16", summary="Write a BF16 model file again as FP16")
async def convert_fp16(
    wish: Fp16Wish, request: Request,
    config: Config = Depends(hole_config), language: str = Depends(hole_sprache),
) -> dict:
    """A copy of the chosen file beside it with its BF16 weights as FP16; the
    file itself stays. The answer names the copy and how many values were
    out of FP16's range and set to its largest. Under the one-picture lock
    like every conversion, and the stop that ends a picture ends it too."""
    source = _model_path(config, wish.model, language)
    if not fp16_convert.convertible(source):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, t("bild.convert_not_bf16", language))
    if fp16_convert.target(source).exists():
        raise HTTPException(status.HTTP_409_CONFLICT, t("bild.umwandeln_da", language))
    runner = _runner(request)
    try:
        runner.reservieren(stoppable=True)
    except BildFehler as error:
        raise HTTPException(status.HTTP_409_CONFLICT, t(error.grund, language)) from error
    try:
        new, capped = await asyncio.to_thread(fp16_convert.convert, runner, source)
    except model_convert.ConvertError as error:
        raise _convert_failure(error, language) from error
    finally:
        runner.freigeben()
    return {"file": new.name, "capped": capped}


@router.post("/bild/imatrix", response_model=bool, summary="Switch importance matrix collection")
def imatrix(
    wish: ImatrixWish,
    repositories: Repositories = Depends(hole_repositories),
) -> bool:
    """One switch for every model file, stored with the machine's other
    picture settings: while on, every picture drawn with sd-cli adds to the
    importance matrix beside its model file; converting then uses it."""
    repositories.einstellungen.zusammenlegen(
        "global", bildgeraete.SCHLUESSEL, {"imatrix": wish.on}, pruefen=bildgeraete.pruefen,
    )
    return wish.on


@router.get("/bild/devices", summary="Devices available to sd-cli for computation")
async def devices(request: Request) -> list[dict[str, str]]:
    program = _runner(request).programm
    if program is None:
        return []
    return await asyncio.to_thread(model_convert.devices, program)
