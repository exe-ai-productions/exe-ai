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

* **"There" means the same file.** A row says it is there only when a file of
  its name and of its size in bytes, as the hub states it, lies in the
  kind's folder (``app/modelldownload.py``, ``place_for``). Another file
  under the name is not it: the row then carries the name the new file would
  be kept under (``local_name``, ``<repo>-<name>``). The window and the terminal
  client read these fields; neither decides it again.

* **A picture model comes with its kit.** A file whose own head — its
  weights' names and shapes, read from the front of the remote file by range
  requests — shows a family that is assembled from parts carries them, the
  name deciding only where the head is not readable (a locked repository
  without a token, ``.ckpt``/``.pt``/``.pth``, no answer): the model itself, its text
  encoders and its VAE, each with the repository it is fetched from, its
  size and whether the picture side has it already. A name that shows no
  family, and a file that is a companion itself, carries none.

* **A picture row says what the file is.** The same head tells ``art`` —
  ``modell`` (with its ``familie``), ``vae`` or ``textleser`` — for every
  safetensors or GGUF file of the list; a head that cannot be read, or is a
  LoRA or a ControlNet, leaves the row without. The name never answers this.

* **The list does not wait for the heads.** The list of a picture repository
  is the tree and where each file would be kept — as fast as the hub answers.
  What a file is and its kit come per row from ``POST /models/files/head``,
  which the window asks for each row once the list stands; a row without that
  answer has neither.

Smallest first, because that is the order in which the question "which one
fits my machine" gets answered.

The list is fetched on the server, same reason as the search itself: the
page would otherwise hand every user's address to a foreign host.
"""

from __future__ import annotations

import asyncio
import os
import re
from pathlib import Path
from typing import Any, Literal
from urllib.parse import quote

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel

from app import bildinhalt, bildrunner, image_families, kit_bond
from app.api.abhaengigkeiten import hole_sprache
from app.i18n import t
from app.modelldownload import BILD_ENDUNGEN, all_parts_there, place_for, teil_von

router = APIRouter(prefix="/models", tags=["modellsuche"])

HF_BASIS = "https://huggingface.co/api/models"
# Where a file of a repository is fetched from, by range.
HF_FILE_BASE = "https://huggingface.co"
# How much of a file's front is read to tell its family: the first request,
# and for a GGUF file the further pieces and the most it may take. A
# safetensors header says its own length; the first request holds it for
# nearly every model, a second fetches the rest (``REMOTE_SAFETENSORS_HEADER_MAX``).
HEAD_FIRST_REQUEST = 100_000
HEAD_GGUF_PIECE = 2_000_000
HEAD_GGUF_MAX = 50_000_000
# The most requests one head may take, and the time it may take — what is
# not read by then is left to its name (the same seconds as one request of
# the list itself).
HEAD_REQUESTS_PER_FILE = 30
HEAD_TIME_LIMIT = 15.0

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
    # The same size in bytes — what "the same file" is measured by.
    bytes: int | None = None
    # The name the part is kept under in its folder, and whether a file of
    # that name and size lies there. ``collision``: both its own name and
    # the second one are held by other files.
    local_name: str = ""
    da: bool = False
    collision: bool = False


class Bausatz(BaseModel):
    familie: str
    label: str
    teile: list[Bausatzteil]


class Datei(BaseModel):
    datei: str
    groesse_gb: float
    # The size in bytes; for a split model that of part 1, whose name and
    # size decide whether it is there.
    bytes: int = 0
    # The name the file is kept under in the kind's folder — its own, or
    # ``<repo>-<name>`` when another file holds its own — and whether a file
    # of that name and size lies there. ``collision``: both names are held by
    # other files, so nothing is offered.
    local_name: str = ""
    da: bool = False
    collision: bool = False
    # How many files make this model: 1, or the parts of a split GGUF.
    teile: int = 1
    # The kit the file's name shows, when its family has one.
    bausatz: Bausatz | None = None
    # What the file's own head says it is — ``modell``, ``textleser`` or
    # ``vae`` — and, for a model, the family it names. None where the head is
    # not readable or names nothing, for a LoRA or a ControlNet, and for every
    # tab but the picture one.
    art: Literal["modell", "textleser", "vae"] | None = None
    familie: str | None = None


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
        zeilen.append(
            Datei(
                datei=teile[1]["path"], groesse_gb=_gb(summe), teile=anzahl,
                bytes=int(teile[1].get("size") or 0),
            )
        )
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
            Datei(
                datei=e["path"], groesse_gb=_gb(int(e.get("size") or 0)),
                bytes=int(e.get("size") or 0),
            )
            for e in gueltig
            if _brauchbar(e["path"], endungen)
        ]
        + _geteilte_bauen(gueltig),
        key=lambda d: d.groesse_gb,
    )
    projektoren = sorted(
        (
            Datei(
                datei=e["path"], groesse_gb=_gb(int(e.get("size") or 0)),
                bytes=int(e.get("size") or 0),
            )
            for e in gueltig
            if _ist_mmproj(e["path"])
        ),
        key=lambda d: d.groesse_gb,
    )
    return Dateiliste(dateien=dateien, mmproj=projektoren[0] if projektoren else None)


async def _part_size(client: httpx.AsyncClient, teil: image_families.KitPart) -> int | None:
    """The size of one part in bytes, as the hub states it; None where it
    cannot be read. A part without a size is still a part, so nothing here
    fails the list."""
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
            return groesse if isinstance(groesse, int) else None
    return None


def _belegen(liste: Dateiliste, repo: str, ordner: Path | None) -> None:
    """Says for every file whether it is there and under which name it would
    be kept. Without a folder for the kind nothing lies anywhere: every file
    keeps its own name and is not there."""
    for datei in liste.dateien:
        name = datei.datei.rsplit("/", 1)[-1]
        datei.local_name = name
        if ordner is None:
            continue
        if datei.teile > 1:
            # A split model keeps the names of its parts (never renamed): it
            # is there when part 1 is, by name and size, and every other part
            # lies under its own name; another file under part 1's name is a
            # collision.
            place = place_for(ordner, name, datei.bytes, "")
            datei.da = place.da and all_parts_there(ordner, name)
            datei.collision = not place.da and place.name != name
            continue
        place = place_for(ordner, name, datei.bytes, repo)
        datei.local_name, datei.da, datei.collision = place.name, place.da, place.collision


async def _fetch_range(
    client: httpx.AsyncClient, repo: str, path: str, start: int, stop: int, token: str
) -> bytes | None:
    """Bytes ``start`` up to ``stop`` of a file of the repository, by a range
    request; None where the hub does not answer with exactly that (a 200
    would be the whole file — never read) or answers badly.

    The token goes to ``huggingface.co`` only: the hub answers with a redirect
    to a host of its own for the bytes, and that hop is made without it."""
    url = f"{HF_FILE_BASE}/{repo}/resolve/main/{quote(path)}"
    headers = {"Range": f"bytes={start}-{stop - 1}"}
    hop = 0
    while hop < 4:
        hop_headers = dict(headers)
        if token and url.startswith(HF_FILE_BASE + "/"):
            hop_headers["Authorization"] = f"Bearer {token}"
        async with client.stream(
            "GET", url, headers=hop_headers, follow_redirects=False
        ) as answer:
            if answer.status_code in (301, 302, 303, 307, 308):
                target = answer.headers.get("location")
                if not target:
                    return None
                url = str(httpx.URL(url).join(target))
                # The bytes of a file come over https, nothing else.
                if not url.startswith("https://"):
                    return None
                hop += 1
                continue
            if answer.status_code != 206:
                return None
            data = bytearray()
            async for piece in answer.aiter_bytes():
                data += piece
                if len(data) >= stop - start:
                    break
            return bytes(data[: stop - start])
    return None


async def _head_family(
    client: httpx.AsyncClient, repo: str, datei: Datei, token: str
) -> bildinhalt.HeadReading | None:
    """What the head of the remote file says — family, kind, whether it is a
    LoRA or a ControlNet: read from the front of the file, a first piece of
    ``HEAD_FIRST_REQUEST`` bytes, then what a safetensors header says it
    takes, or for a GGUF file pieces of ``HEAD_GGUF_PIECE`` up to
    ``HEAD_GGUF_MAX``. None where the head cannot be read — the name then
    decides, as it did."""
    size = datei.bytes
    if size <= 0:
        return None
    data = b""
    stop = min(HEAD_FIRST_REQUEST, size)
    for _ in range(HEAD_REQUESTS_PER_FILE):
        piece = await _fetch_range(client, repo, datei.datei, len(data), stop, token)
        if piece is None or not piece:
            return None
        data += piece
        try:
            head = bildinhalt.header_from_bytes(data, size)
        except bildinhalt.HeaderIncomplete as more:
            limit = (
                HEAD_GGUF_MAX
                if data[:4] == b"GGUF"
                else bildinhalt.REMOTE_SAFETENSORS_HEADER_MAX + 8
            )
            wanted = more.needed or len(data) + HEAD_GGUF_PIECE
            if wanted > limit or len(data) >= size:
                return None
            stop = min(wanted, size)
            continue
        if head is None:
            return None
        is_gguf, architecture, names, vision = head
        return bildinhalt.read_header(names, architecture, is_gguf=is_gguf, vision=vision)
    return None


async def _read_head(
    repo: str, datei: Datei, token: str
) -> bildinhalt.HeadReading | None:
    """The head of a file that can have one — a safetensors or GGUF file —
    within ``HEAD_TIME_LIMIT``. Any failure leaves the file to its name."""
    if not datei.datei.lower().endswith((".safetensors", ".gguf")):
        return None
    # Not the client of the list: it carries the token on every request,
    # and the hop to the host that serves the bytes must not.
    async with httpx.AsyncClient(timeout=15, follow_redirects=False) as client:
        try:
            return await asyncio.wait_for(
                _head_family(client, repo, datei, token), HEAD_TIME_LIMIT
            )
        except Exception:  # noqa: BLE001 - a head that cannot be read is left to the name
            return None


_ART_OF_KIND = {
    bildinhalt.BILDMODELL: "modell",
    bildinhalt.VAE: "vae",
    bildinhalt.TEXTVERSTEHER: "textleser",
    # A vision projector is kept with the text encoders, so it is fetched
    # into the same folder as one.
    bildinhalt.SEHTEIL: "textleser",
}


def _name_kinds(liste: Dateiliste, heads: dict[str, bildinhalt.HeadReading | None]) -> None:
    """Tells each row what its own head says it is: model (with its family),
    VAE or text encoder. A head that is not readable, names no kind, or is a
    LoRA or a ControlNet leaves the row without."""
    for datei in liste.dateien:
        head = heads.get(datei.datei)
        if head is None or head.companion:
            continue
        datei.art = _ART_OF_KIND.get(head.kind)
        if datei.art == "modell" and head.family is not None:
            datei.familie = head.family


async def _add_kits(
    client: httpx.AsyncClient, repo: str, liste: Dateiliste, ordner: Path | None,
    heads: dict[str, bildinhalt.HeadReading | None],
) -> None:
    """Gives each model file whose family — told by its own head, by its name
    where the head cannot be read — has a kit that kit: the model itself and
    every part, each with its size and whether it is there already. Files of
    one family share their parts, so each part's size is asked for once."""
    def family_of(datei: Datei) -> tuple[image_families.Family | None, bool]:
        """The family of the file and whether it is a companion by its head."""
        head = heads.get(datei.datei)
        if head is not None:
            if head.companion:
                return None, True
            if head.family is not None and image_families.get(head.family) is not None:
                return image_families.get(head.family), False
        return image_families.family_of_file(datei.datei), False

    families = {datei.datei: family_of(datei) for datei in liste.dateien}

    def kit_of(datei: Datei) -> tuple[image_families.KitPart, ...]:
        familie, companion = families[datei.datei]
        if companion or familie is None:
            return ()
        return kit_bond.kit_parts(datei.datei, familie.name)

    # Every part of every kit seen, asked for at once and only once.
    seen = {
        (teil.repo, teil.file): teil
        for datei in liste.dateien
        for teil in kit_of(datei)
    }
    if not seen:
        return
    answers = await asyncio.gather(*(_part_size(client, teil) for teil in seen.values()))
    sizes: dict[tuple[str, str], int | None] = dict(zip(seen, answers, strict=True))
    # A part is there when the picture side offers it: in its own sub-folder,
    # or loose in the main folder where its content names it. Asked of the
    # same lists a drawing reads, so "there" means the same in both places.
    vaes: set[str] = set()
    encoders: set[str] = set()
    vision: set[str] = set()
    if ordner is not None:
        vaes = set(await asyncio.to_thread(bildrunner.vaes, ordner))
        encoders = set(await asyncio.to_thread(bildrunner.textversteher, ordner))
        vision = set(await asyncio.to_thread(bildrunner.sehteile, ordner))
    # What the drawing takes of a family's parts by itself, asked once per
    # family: a part counts as there when the drawing finds a file of the
    # right kind for it, whatever its name or quantisation.
    taken: dict[str, dict[str, str]] = {}
    for datei in liste.dateien:
        kit = kit_of(datei)
        familie = families[datei.datei][0]
        if not kit or familie is None:
            continue
        name = datei.datei.rsplit("/", 1)[-1]
        if ordner is not None and familie.name not in taken:
            taken[familie.name] = await asyncio.to_thread(
                kit_bond.matching_parts, ordner, familie
            )
        teile = [
            Bausatzteil(
                rolle="modell", repo=repo, datei=datei.datei, name=name, ordner="",
                groesse_gb=datei.groesse_gb, bytes=datei.bytes or None,
                local_name=datei.local_name or name, da=datei.da, collision=datei.collision,
            )
        ]
        for teil in kit:
            part_size = sizes[(teil.repo, teil.file)]
            listed = teil.name in {"vae": vaes, "llm_vision": vision}.get(teil.part, encoders)
            local_name, da, collision = teil.name, listed, False
            fitting = taken.get(familie.name, {}).get(teil.part)
            if fitting is not None:
                # The drawing sets this part in by itself: the file it takes
                # is the part, and nothing of it is fetched.
                local_name, da, collision = fitting, True, False
            elif ordner is not None and part_size is not None:
                # In its own sub-folder, or loose in the main folder where
                # its content names it: a file of its name and size is it.
                place = place_for(
                    ordner / teil.folder, teil.name, part_size, teil.repo, also_in=(ordner,)
                )
                local_name, da, collision = place.name, place.da, place.collision
                if local_name == teil.name and not da:
                    # The name is free in the two places above: a file the
                    # lists still show under it was found by its content.
                    da = listed
            teile.append(
                Bausatzteil(
                    rolle="vae" if teil.part == "vae" else "textleser", feld=teil.part,
                    repo=teil.repo, datei=teil.file, name=teil.name, ordner=teil.folder,
                    groesse_gb=None if part_size is None else _gb(part_size), bytes=part_size,
                    local_name=local_name, da=da, collision=collision,
                )
            )
        datei.bausatz = Bausatz(familie=familie.name, label=familie.label, teile=teile)


@router.get("/files", response_model=Dateiliste, summary="Repository files")
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
            wurzel = getattr(request.app.state, "modellordner_je_art", {}).get(art)
            ordner = Path(wurzel).expanduser() if wurzel else None
            _belegen(liste, repo, ordner)
    except httpx.HTTPError:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, t("fehler.dateiliste_fern", sprache)
        ) from None

    return liste


class HeadQuestion(BaseModel):
    repo: str
    # The row of the list the answer is wanted for.
    datei: Datei


def _remote_path_ok(path: str) -> bool:
    """A path inside a repository: segments only, no ``..``, no leading
    slash — the address of the file is built from it."""
    return bool(path) and "\\" not in path and all(
        segment not in ("", ".", "..") for segment in path.split("/")
    )


@router.post("/files/head", response_model=Datei, summary="What one picture file is")
async def file_head(
    question: HeadQuestion,
    request: Request,
    sprache: str = Depends(hole_sprache),
) -> Datei:
    """One row of a picture repository's list with what its own head says:
    what the file is and its kit. Where the head cannot be read, the name
    decides the kit and the row says nothing of what it is."""
    if not REPO.match(question.repo):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, t("fehler.dateiliste_repo", sprache)
        )
    # What the window sends back is only which file it is; the rest is
    # asked of the hub and of the folder again. A split model's size is the
    # sum of its parts, which only the list knows.
    given = question.datei
    row = Datei(
        datei=given.datei,
        groesse_gb=given.groesse_gb if given.teile > 1 else _gb(given.bytes),
        bytes=given.bytes,
        teile=given.teile,
    )
    listing = Dateiliste(dateien=[row])
    root = getattr(request.app.state, "modellordner_je_art", {}).get("bild")
    folder = Path(root).expanduser() if root else None
    _belegen(listing, question.repo, folder)
    if not _remote_path_ok(row.datei):
        return row
    token = os.environ.get("HF_TOKEN", "").strip()
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    heads = {row.datei: await _read_head(question.repo, row, token)}
    _name_kinds(listing, heads)
    try:
        async with httpx.AsyncClient(timeout=15, headers=headers, follow_redirects=True) as client:
            await _add_kits(client, question.repo, listing, folder, heads)
    except httpx.HTTPError:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, t("fehler.dateiliste_fern", sprache)
        ) from None
    return row
