"""Which model files a found repository actually offers.

The search answers "which repository" — this answers "which file", and only
with files the one-button download can finish alone:

* **The forms the kind's server starts.** A chat, embedding or speech model
  is ``.gguf``; an image model may be any single-file form the image server
  reads (``BILD_ENDUNGEN``).
* **Every folder.** Many repositories keep each quantisation in its own
  sub-folder; the tree is read recursively, page by page, and a file keeps
  its full path in the repository.
* **A split GGUF is one row.** Its parts ``-00001-of-0000N`` to
  ``-0000N-of-0000N`` belong together: the row names part 1, carries the sum
  of all parts and how many there are, and the download fetches them all.
  A version with a part missing is no model and is not offered. Split
  safetensors are never offered — the image server reads single files.
* **``mmproj`` companions ride along separately.** A vision projector
  cannot start on its own, so it is never offered as a model — but the
  answer says whether the repository has one, and the download fetches it
  next to the model so its eyes arrive with it.

* **A picture model comes with its kit.** A file whose name shows a family
  that is assembled from parts carries them: the model itself, its text
  encoders and its VAE, each with the repository it is fetched from, its
  size and whether the picture side has it already. A name that shows no
  family, and a file that is a companion itself, carries none.

Smallest first, because that is the order in which the question "which one
fits my machine" gets answered.

The list is fetched on the server, same reason as the search itself: the
page would otherwise hand every user's address to a foreign host.
"""

from __future__ import annotations

import asyncio
import re
from pathlib import Path
from typing import Any, Literal

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel

from app import bildrunner, image_families, kit_bond
from app.api.abhaengigkeiten import hole_sprache
from app.i18n import t
from app.modelldownload import BILD_ENDUNGEN, teil_von

router = APIRouter(prefix="/models", tags=["modellsuche"])

HF_BASIS = "https://huggingface.co/api/models"

# A repository is owner/name — anything else does not go into an address.
REPO = re.compile(r"^[A-Za-z0-9][\w.-]{0,95}/[\w.-]{1,96}$")

ENDUNG = ".gguf"
SHARD = re.compile(r"-\d{5}-of-\d{5}\.(gguf|safetensors)$", re.IGNORECASE)


class Bausatzteil(BaseModel):
    # What the part is in the kit: the model itself, a text encoder or the VAE.
    rolle: Literal["modell", "textleser", "vae"]
    # The field of the model's kit the part fills (``llm``, ``t5xxl``,
    # ``clip_l``, ``vae``); empty for the model itself.
    feld: str = ""
    repo: str
    # The file's path in its repository, and its name in the folder.
    datei: str
    name: str
    # The sub-folder of the picture folder it lies in; empty for the model.
    ordner: str
    # The size Hugging Face reports; None where it could not be read.
    groesse_gb: float | None = None
    da: bool = False


class Bausatz(BaseModel):
    familie: str
    label: str
    teile: list[Bausatzteil]


class Datei(BaseModel):
    datei: str
    groesse_gb: float
    # How many files make this model: 1, or the parts of a split GGUF.
    teile: int = 1
    # The kit the file's name shows, when its family has one.
    bausatz: Bausatz | None = None


class Dateiliste(BaseModel):
    dateien: list[Datei]
    # The repository's vision projector, if it has one — the smallest,
    # because they only differ in precision and the small one sees the same.
    mmproj: Datei | None = None


def _brauchbar(pfad: str, endungen: tuple[str, ...] = (ENDUNG,)) -> bool:
    name = pfad.lower()
    if not name.endswith(endungen):
        return False
    if SHARD.search(name):
        return False
    if "mmproj" in name:
        return False
    return True


def _ist_mmproj(pfad: str) -> bool:
    name = pfad.lower()
    return name.endswith(ENDUNG) and "mmproj" in name and not SHARD.search(name)


def _gb(groesse: int) -> float:
    return round(groesse / 1e9, 1)


def _geteilte_bauen(eintraege: list[dict[str, Any]]) -> list[Datei]:
    """One row per complete split GGUF: part 1's path, the sum of all parts."""
    fassungen: dict[tuple[str, int], dict[int, dict[str, Any]]] = {}
    for e in eintraege:
        teil = teil_von(e["path"])
        if teil is None or "mmproj" in e["path"].lower():
            continue
        stamm, nummer, anzahl = teil
        fassungen.setdefault((stamm.lower(), anzahl), {})[nummer] = e
    zeilen = []
    for (_, anzahl), teile in fassungen.items():
        if set(teile) != set(range(1, anzahl + 1)):
            continue
        summe = sum(int(e.get("size") or 0) for e in teile.values())
        zeilen.append(Datei(datei=teile[1]["path"], groesse_gb=_gb(summe), teile=anzahl))
    return zeilen


def _dateien_bauen(eintraege: list[Any], art: str = "chat") -> Dateiliste:
    gueltig = [
        e for e in eintraege
        if isinstance(e, dict)
        and isinstance(e.get("path"), str)
        and e.get("type", "file") == "file"
    ]
    endungen = BILD_ENDUNGEN if art == "bild" else (ENDUNG,)
    dateien = sorted(
        [
            Datei(datei=e["path"], groesse_gb=_gb(int(e.get("size") or 0)))
            for e in gueltig
            if _brauchbar(e["path"], endungen)
        ]
        + _geteilte_bauen(gueltig),
        key=lambda d: d.groesse_gb,
    )
    projektoren = sorted(
        (
            Datei(datei=e["path"], groesse_gb=_gb(int(e.get("size") or 0)))
            for e in gueltig
            if _ist_mmproj(e["path"])
        ),
        key=lambda d: d.groesse_gb,
    )
    return Dateiliste(dateien=dateien, mmproj=projektoren[0] if projektoren else None)


async def _part_size(client: httpx.AsyncClient, teil: image_families.KitPart) -> float | None:
    """The size of one part, as the hub states it; None where it cannot be
    read. A part without a size is still a part, so nothing here fails the
    list."""
    try:
        antwort = await client.post(
            f"{HF_BASIS}/{teil.repo}/paths-info/main", data={"paths": teil.file}
        )
        antwort.raise_for_status()
        zeilen = antwort.json()
    except (httpx.HTTPError, ValueError):
        return None
    if not isinstance(zeilen, list):
        return None
    for zeile in zeilen:
        if isinstance(zeile, dict) and zeile.get("path") == teil.file:
            groesse = zeile.get("size")
            return _gb(int(groesse)) if isinstance(groesse, int) else None
    return None


async def _add_kits(
    client: httpx.AsyncClient, repo: str, liste: Dateiliste, ordner: Path | None
) -> None:
    """Gives each model file whose name shows a family with a kit that kit:
    the model itself and every part, each with its size and whether it is
    there already. Files of one family share their parts, so each part's
    size is asked for once."""
    # Every part of every kit seen, asked for at once and only once.
    seen = {
        (teil.repo, teil.file): teil
        for datei in liste.dateien
        for teil in kit_bond.kit_parts(datei.datei)
    }
    if not seen:
        return
    answers = await asyncio.gather(*(_part_size(client, teil) for teil in seen.values()))
    sizes = dict(zip(seen, answers, strict=True))
    # A part is there when the picture side offers it: in its own sub-folder,
    # or loose in the main folder where its content names it. Asked of the
    # same lists a drawing reads, so "there" means the same in both places.
    vaes: set[str] = set()
    encoders: set[str] = set()
    if ordner is not None:
        vaes = set(await asyncio.to_thread(bildrunner.vaes, ordner))
        encoders = set(await asyncio.to_thread(bildrunner.textversteher, ordner))
    for datei in liste.dateien:
        kit = kit_bond.kit_parts(datei.datei)
        familie = image_families.family_of_file(datei.datei)
        if not kit or familie is None:
            continue
        name = datei.datei.rsplit("/", 1)[-1]
        teile = [
            Bausatzteil(
                rolle="modell", repo=repo, datei=datei.datei, name=name, ordner="",
                groesse_gb=datei.groesse_gb,
                da=ordner is not None and (ordner / name).is_file(),
            )
        ]
        for teil in kit:
            teile.append(
                Bausatzteil(
                    rolle="vae" if teil.part == "vae" else "textleser", feld=teil.part,
                    repo=teil.repo, datei=teil.file, name=teil.name, ordner=teil.folder,
                    groesse_gb=sizes[(teil.repo, teil.file)],
                    da=teil.name in (vaes if teil.part == "vae" else encoders),
                )
            )
        datei.bausatz = Bausatz(familie=familie.name, label=familie.label, teile=teile)


@router.get("/files", response_model=Dateiliste, summary="Files of a repository")
async def dateien(
    request: Request,
    repo: str = Query(min_length=3, max_length=200),
    # The catalogue tab the repository was found in; it decides which file
    # forms count, the same kinds the download takes.
    art: Literal["chat", "einbettung", "sprache", "bild"] = "chat",
    sprache: str = Depends(hole_sprache),
) -> Dateiliste:
    if not REPO.match(repo):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, t("fehler.dateiliste_repo", sprache)
        )

    try:
        import os

        kopf = {}
        wert = os.environ.get("HF_TOKEN", "").strip()
        if wert:
            kopf["Authorization"] = f"Bearer {wert}"
        daten: list[Any] = []
        adresse: str | None = f"{HF_BASIS}/{repo}/tree/main?recursive=true"
        seen: set[str] = set()
        # A renamed repository answers at its old name with a redirect to the
        # new one; following it keeps an older search hit working.
        async with httpx.AsyncClient(timeout=15, headers=kopf, follow_redirects=True) as client:
            # A large tree comes in pages; each answer names the next one in
            # its Link header. Only an address on the hub itself is followed,
            # and none twice.
            while adresse and adresse not in seen:
                seen.add(adresse)
                antwort = await client.get(adresse)
                antwort.raise_for_status()
                seite = antwort.json()
                if not isinstance(seite, list):
                    raise HTTPException(
                        status.HTTP_502_BAD_GATEWAY, t("fehler.dateiliste_fern", sprache)
                    )
                daten.extend(seite)
                weiter = antwort.links.get("next", {}).get("url")
                adresse = weiter if weiter and weiter.startswith(HF_BASIS + "/") else None
            liste = _dateien_bauen(daten, art)
            if art == "bild":
                wurzel = getattr(request.app.state, "modellordner_je_art", {}).get("bild")
                await _add_kits(
                    client, repo, liste, Path(wurzel).expanduser() if wurzel else None
                )
    except httpx.HTTPError:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, t("fehler.dateiliste_fern", sprache)
        ) from None

    return liste
