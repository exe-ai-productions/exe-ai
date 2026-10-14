"""The built-in file tools as one group.

Six tools that behave identically towards the registry: same source, same
boundary, same confirmation. Listing them once here keeps the registry from
growing a branch per tool, and adding another stays a one-line change.

Each module carries its own tool; this file only says which ones there are.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from types import ModuleType
from typing import Any

from app.tools import (
    create_folder,
    datei_aendern,
    datei_lesen,
    datei_schreiben,
    datei_suchen,
    grenzen,
    ordner_lesen,
)
from app.tools.mcp_client import MCPWerkzeug

# The order the model sees them in: look, search, write, change, list,
# create a folder.
MODULE: tuple[ModuleType, ...] = (
    datei_lesen,
    datei_suchen,
    datei_schreiben,
    datei_aendern,
    ordner_lesen,
    create_folder,
)

NAMEN: tuple[str, ...] = tuple(m.WERKZEUG_NAME for m in MODULE)


def modul(name: str) -> ModuleType | None:
    """The module behind a tool name, or None if it is not one of ours."""
    for eintrag in MODULE:
        if eintrag.WERKZEUG_NAME == name:
            return eintrag
    return None


def beschreibungen() -> list[MCPWerkzeug]:
    return [m.werkzeug_beschreibung() for m in MODULE]


def aussenpfad(name: str, argumente: dict[str, Any], ordner: list[str]) -> str | None:
    eintrag = modul(name)
    return eintrag.aussenpfad(argumente, ordner) if eintrag else None


def private_target(
    name: str, argumente: dict[str, Any], ordner: list[str], private: Callable[[Path], bool]
) -> str | None:
    """The private place of the program this call names, or None. Every tool
    of the group names its path as ``path``."""
    eintrag = modul(name)
    # ``create_folder`` makes no folder in the data folder at all and says
    # so in its own words (``create_folder.ausfuehren``).
    if eintrag is None or eintrag is create_folder:
        return None
    return grenzen.private_target(argumente, ordner, private)


async def ausfuehren(
    name: str, argumente: dict[str, Any], ordner: list[str], modellbild=None, share=None,
    data_dir=None, private: Callable[[Path], bool] | None = None,
) -> str:
    """Runs one of these tools. The caller has already checked it is one.

    ``modellbild`` is how a picture reaches the model (app/werkzeugbild.py) and
    only the read tool has anything to do with it; ``share`` stores a folder
    ``create_folder`` made with the chat. ``data_dir`` is the data folder the
    run belongs to: create_folder must not make a folder there, the read
    tool keeps the model's picture copies under it — so a caller carrying its
    own folder never writes into the installed one — and every tool that
    refuses a missing path tells from it whether the chat shares no folder
    (``grenzen.missing``) and which first folder is the chat's own, made when
    a call runs (``grenzen.ziel``). The branch lives here
    rather than in the registry so the registry keeps ONE line for the whole
    group, which is the reason this module exists.
    """
    eintrag = modul(name)
    if eintrag is None:
        raise KeyError(name)
    if eintrag is datei_lesen:
        return await datei_lesen.ausfuehren(
            argumente, ordner, modellbild=modellbild, data_dir=data_dir
        )
    if eintrag is create_folder:
        return await create_folder.ausfuehren(argumente, ordner, share, data_dir)
    if eintrag is datei_suchen:
        # The walk goes past a private place of the program.
        return await datei_suchen.ausfuehren(argumente, ordner, data_dir=data_dir, private=private)
    if eintrag is datei_schreiben:
        # The one tool here with no refusal for a missing path: it makes the file.
        return await datei_schreiben.ausfuehren(argumente, ordner, data_dir=data_dir)
    return await eintrag.ausfuehren(argumente, ordner, data_dir=data_dir)
