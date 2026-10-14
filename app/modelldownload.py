"""Fetching a model file into the model folder.

The point of this module is that nobody has to open a terminal. Pick a model,
press one button, watch a bar fill — and afterwards the file lies where the
runner looks for it. A command to copy would have been quicker to build and
would have missed the whole purpose of the program.

Four rules, and each of them keeps a way out of the folder shut:

* **Only huggingface.co.** The address is built here from a repository and a
  file name; it never arrives from outside.
* **Only ``.gguf``.** That is what the runner can start. Anything else in
  the folder would be dead weight at best.
* **The name is a name.** It ends up in a folder, so a slash or a ``..`` in
  it would end up somewhere else.
* **One download at a time.** Two would fight over the same disk and give
  two half-files.

A file being written carries a ``.teil`` ending until it is complete, and is
only then renamed. Nothing half-downloaded is ever mistaken for a model —
which is what a model server would do, right before it fails to explain why.

A half file that is still there when the same file is asked for again — the
program was closed while it was fetched — is continued from its end by a
range request; a server that answers with the whole file starts it over.
Cancelling or a failed fetch removes it, as before.

A split GGUF (``-00001-of-0000N`` … ``-0000N-of-0000N``) is fetched whole:
naming part 1 fetches every part into the same folder, and only when all of
them are there are they renamed. The server is started with part 1 and finds
the others next to it.
"""

from __future__ import annotations

import hashlib
import os
import re
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import httpx

from app import atomic_file
from app import modellzuordnung

BASIS = "https://huggingface.co"
# What a chat or embedding model may be — the one form the runner starts.
ENDUNG = ".gguf"
# What an image model may be. The local drawer (sd.cpp) reads single-file
# safetensors and gguf, and the big image checkpoints on Hugging Face are
# almost all safetensors — so the image folder accepts those forms too. Which
# set applies is decided by the caller (per kind), not hardcoded here.
BILD_ENDUNGEN = (".safetensors", ".gguf", ".ckpt", ".pt", ".pth")
UNFERTIG = ".teil"
# The parts of a split GGUF: <stem>-00001-of-00003.gguf.
TEIL = re.compile(r"^(.*)-(\d{5})-of-(\d{5})\.gguf$", re.IGNORECASE)

# Big enough not to wake the loop for every packet, small enough that the bar
# still moves while a fibre line is running.
BROCKEN = 1024 * 1024


@dataclass
class Fortschritt:
    datei: str
    geladen: int
    gesamt: int
    fertig: bool = False
    fehler: str | None = None

    @property
    def anteil(self) -> float:
        return round(self.geladen / self.gesamt, 4) if self.gesamt else 0.0


def teil_von(name: str) -> tuple[str, int, int] | None:
    """Stem, part number and part count of a split GGUF; None for one file."""
    treffer = TEIL.match(name)
    if not treffer:
        return None
    nummer, anzahl = int(treffer.group(2)), int(treffer.group(3))
    if not 1 <= nummer <= anzahl:
        return None
    return treffer.group(1), nummer, anzahl


def alle_teile(name: str) -> list[str]:
    """Every part's name when ``name`` is part 1 of a split GGUF, else ``[name]``."""
    teil = teil_von(name)
    if teil is None or teil[1] != 1:
        return [name]
    stamm, _, anzahl = teil
    endung = name[-len(".gguf"):]
    return [f"{stamm}-{n:05d}-of-{anzahl:05d}{endung}" for n in range(1, anzahl + 1)]


def all_parts_there(folder: Path, name: str) -> bool:
    """Whether every part of the model ``name`` names lies in ``folder`` under
    its own name: for a split GGUF each of its parts, for any other file that
    file. The one rule of "there" for a model in several parts — the catalogue
    row and the download both read it."""
    return all((folder / part.rsplit("/", 1)[-1]).is_file() for part in alle_teile(name))


def _half_file(folder: Path, name: str, url: str) -> Path:
    """Where the file ``name``, fetched from ``url``, is written while it is
    incomplete. The address is part of the name, so the half file of another
    repository's file of the same name is never continued as this one."""
    tag = hashlib.sha256(url.encode()).hexdigest()[:12]
    return folder / f"{name}.{tag}{UNFERTIG}"


# Written next to a half file: the version of the file in the repository it
# was begun from (its ETag). A half file is continued only while the file
# there is still that version.
FASSUNG = ".fassung"


def _version_file(half: Path) -> Path:
    return half.with_name(half.name + FASSUNG)


def _drop_half(half: Path) -> None:
    """A half file and the version it was begun from."""
    half.unlink(missing_ok=True)
    _version_file(half).unlink(missing_ok=True)


def _range_start(value: str | None) -> int | None:
    """The first byte of a ``Content-Range: bytes <first>-<last>/<size>``."""
    match = re.match(r"^bytes (\d+)-\d+/(\d+|\*)$", (value or "").strip())
    return int(match.group(1)) if match else None


@dataclass(frozen=True)
class Place:
    """Where a file of the hub would be kept in a folder, and whether it is
    there already."""

    # The name it is kept under: its own, ``<repo>-<name>`` when another file
    # holds its own, or ``<owner>-<repo>-<name>`` when another file holds that
    # one too.
    name: str
    # A file of that name and of the size the hub states lies there.
    da: bool
    # All the names it may take are held by other files: nothing can be stored
    # without overwriting one of them.
    collision: bool = False


def place_for(
    folder: Path,
    name: str,
    size: int | None,
    repo: str,
    also_in: tuple[Path, ...] = (),
) -> Place:
    """The one rule for "is it there": a file counts as there when a file of
    its name and of its size in bytes, as the hub states it, lies in the
    folder — or in one of ``also_in``, the other places the same file may lie
    in. A file of the same name and another size is another file: the new one
    is kept under ``<repo>-<name>`` (the repo without its owner), and both
    stay. When another file holds that name too, the new one is kept under
    ``<owner>-<repo>-<name>``. Without a size the name alone decides, as it
    did before.

    A third name that is held by yet another file — or a repo that names no
    owner, so there is no third name — is a collision, which nothing here
    resolves."""
    places = (folder, *also_in)
    # A size of 0 is a size the hub did not state, not an empty model.
    if size is not None and size <= 0:
        size = None

    def find(wanted: str) -> list[Path]:
        return [where / wanted for where in places if (where / wanted).is_file()]

    def same(found: list[Path]) -> bool:
        return any(path.stat().st_size == size for path in found)

    existing = find(name)
    if size is None:
        return Place(name, bool(existing))
    if not existing:
        return Place(name, False)
    if same(existing):
        return Place(name, True)
    second = f"{repo.rsplit('/', 1)[-1]}-{name}"
    others = find(second)
    if not others:
        return Place(second, False)
    if same(others):
        return Place(second, True)
    owner = repo.rpartition("/")[0]
    if not owner:
        return Place(second, False, True)
    third = f"{owner}-{second}"
    last = find(third)
    if not last:
        return Place(third, False)
    if same(last):
        return Place(third, True)
    return Place(third, False, True)


class DownloadFehler(Exception):
    """Carries the key of the sentence to show, not the sentence itself."""

    def __init__(self, grund: str) -> None:
        super().__init__(grund)
        self.grund = grund


def _pruefen(datei: str, endungen: tuple[str, ...] = (ENDUNG,)) -> str:
    """The LOCAL name: strictly flat, no path at all — it names a file that
    lands directly in a folder we chose, so a slash or a dot-prefix could only
    be an attempt to write somewhere else."""
    if "/" in datei or "\\" in datei or ".." in datei or datei.startswith("."):
        raise DownloadFehler("name")
    if not datei.lower().endswith(endungen):
        raise DownloadFehler("endung")
    return datei


def _pruefen_fern(datei: str, endungen: tuple[str, ...] = (ENDUNG,)) -> str:
    """The REMOTE name on the hub: may sit in a sub-folder — a drafter lives at
    ``MTP/mtp-….gguf``, a projector sometimes one level down — so a forward
    slash between segments is allowed. Never a traversal, a backslash, a
    leading slash or dot, or an empty segment: the address is built from this,
    and the local name is derived from its last segment (flat, re-checked)."""
    # The per-segment check below already rejects a leading slash (an empty
    # first segment) and a leading dot (a hidden segment), so those need no
    # separate guard here; only a traversal and a backslash do.
    if "\\" in datei or ".." in datei:
        raise DownloadFehler("name")
    if any(not teil or teil.startswith(".") for teil in datei.split("/")):
        raise DownloadFehler("name")
    if not datei.lower().endswith(endungen):
        raise DownloadFehler("endung")
    return datei


class Modelldownload:
    """One download, watchable while it runs."""

    def __init__(self, ordner: Path) -> None:
        self._ordner = Path(ordner).expanduser()
        self._stand: Fortschritt | None = None
        self._abbruch = threading.Event()
        self._schloss = threading.Lock()

    def stand(self) -> Fortschritt | None:
        return self._stand

    def laeuft(self) -> bool:
        return self._stand is not None and not self._stand.fertig and not self._stand.fehler

    def abbrechen(self) -> bool:
        if not self.laeuft():
            return False
        self._abbruch.set()
        return True

    def starten(
        self,
        repo: str,
        datei: str,
        ziel: str | None = None,
        gehoert_zu: str | None = None,
        rolle: str | None = None,
        ordner: Path | None = None,
        endungen: tuple[str, ...] = (ENDUNG,),
        manifest_ordner: Path | None = None,
        nach: Callable[[], None] | None = None,
        size: int | None = None,
    ) -> Fortschritt:
        """``ziel`` is the local name, when it must differ from the remote one.

        ``size`` is the size in bytes the hub states for the file. With it,
        a name that another file holds is not a reason to refuse: the file is
        kept under ``<repo>-<name>`` (``place_for``). A file that is there
        already, by name and size, is still refused. A split model keeps the
        names of its parts; for it the name alone decides.

        Vision companions need this: several repositories call their
        projector plainly ``mmproj-BF16.gguf``, and two of those in one
        folder would silently overwrite each other. The remote name stays in
        the address, the local name keeps the model it belongs to.

        ``gehoert_zu`` and ``rolle`` declare that this file is a companion of
        another model: when both are set, the bond is written into the folder
        manifest once the file is truly in place, so the runner reads it
        instead of guessing. Left absent, a download behaves as before.

        ``ordner`` is the destination folder, when it is not the chat model
        folder this instance was built on. Each server reads only its own
        folder, so the file must land where its kind of server looks — an
        embedding model in the chat folder is invisible to the embedding
        server and a broken entry in the chat list.

        ``nach`` runs once the file is truly in place — the place for a bond
        that is not a companion's (a VAE tied to the model it came for) — and
        never for a cancelled or failed fetch.
        """
        with self._schloss:
            if self.laeuft():
                raise DownloadFehler("laeuft_schon")

            zielordner = Path(ordner).expanduser() if ordner else self._ordner
            _pruefen_fern(datei, endungen)
            # The local name: the given one, or the remote's last segment — the
            # sub-folder never rides along into our folder. A split model keeps
            # its parts' own names, because the server finds part 2 by name.
            fern = alle_teile(datei)
            if len(fern) > 1:
                ziel = None
            ziel = _pruefen(ziel, endungen) if ziel else _pruefen(datei.rsplit("/", 1)[-1], endungen)
            if size is not None and len(fern) == 1:
                place = place_for(zielordner, ziel, size, repo)
                if place.da or place.collision:
                    raise DownloadFehler("schon_da")
                ziel = _pruefen(place.name, endungen)
            if len(fern) > 1:
                # A split model is there when every one of its parts is; a
                # part that lies there already is kept and not fetched again
                # (``_holen``).
                if all_parts_there(zielordner, datei):
                    raise DownloadFehler("schon_da")
            elif (zielordner / ziel).is_file():
                raise DownloadFehler("schon_da")

            # The manifest belongs to the MODEL folder, not the companion's
            # sub-folder: the runner reads the bond from where the model lies.
            manifest = Path(manifest_ordner).expanduser() if manifest_ordner else zielordner
            self._abbruch.clear()
            self._stand = Fortschritt(datei=ziel, geladen=0, gesamt=0)
            threading.Thread(
                target=self._holen,
                args=(repo, fern, ziel, gehoert_zu, rolle, zielordner, manifest, nach),
                daemon=True,
            ).start()
            return self._stand

    def _fetch_part(
        self, url: str, half: Path, headers: dict[str, str], single: bool
    ) -> None:
        """Streams one file into its half file. A half file that lies there
        already is continued from its end; an answer that is not the rest
        starts the file over. ``single``: the bar is this one file's."""
        have = half.stat().st_size if half.is_file() else 0
        version_file = _version_file(half)
        try:
            known = version_file.read_text(encoding="utf-8").strip()
        except (OSError, ValueError):
            known = ""
        if have and not known:
            # Begun from a version nobody wrote down: there is nothing to
            # tell whether the file in the repository is still that one.
            _drop_half(half)
            have = 0
        while True:
            asked = dict(headers)
            if have:
                asked["Range"] = f"bytes={have}-"
            with httpx.stream(
                "GET", url, follow_redirects=True, timeout=60, headers=asked
            ) as answer:
                if have and answer.status_code == 416:
                    # The half file is whole or longer than the file: it is
                    # of no use, the file begins again.
                    _drop_half(half)
                    have = 0
                    continue
                answer.raise_for_status()
                current = (
                    answer.headers.get("x-linked-etag") or answer.headers.get("etag") or ""
                ).strip()
                if have and current != known:
                    # The repository holds another file under this name now:
                    # the half file is the beginning of a different one.
                    _drop_half(half)
                    have = 0
                    continue
                resumed = (
                    have > 0
                    and answer.status_code == 206
                    and _range_start(answer.headers.get("content-range")) == have
                )
                if not resumed:
                    have = 0
                length = int(answer.headers.get("content-length") or 0)
                if single and self._stand:
                    self._stand.gesamt = have + length if length else 0
                if self._stand:
                    self._stand.geladen += have
                if not resumed:
                    # The version is written before the first byte, so a
                    # half file that is left lying always carries the
                    # version it was begun from; a server that names none
                    # leaves a half file that is never continued.
                    _version_file(half).unlink(missing_ok=True)
                    if current:
                        _version_file(half).write_text(current, encoding="utf-8")
                with half.open("ab" if resumed else "wb") as out:
                    for chunk in answer.iter_bytes(BROCKEN):
                        if self._abbruch.is_set():
                            raise DownloadFehler("abgebrochen")
                        out.write(chunk)
                        if self._stand:
                            self._stand.geladen += len(chunk)
            return

    def _holen(
        self,
        repo: str,
        fern: list[str],
        ziel_name: str,
        gehoert_zu: str | None = None,
        rolle: str | None = None,
        ordner: Path | None = None,
        manifest_ordner: Path | None = None,
        nach: Callable[[], None] | None = None,
    ) -> None:
        zielordner = ordner if ordner is not None else self._ordner
        manifest_ordner = manifest_ordner if manifest_ordner is not None else zielordner
        zielordner.mkdir(parents=True, exist_ok=True)
        # One file keeps the chosen local name; the parts of a split model
        # keep their own, each landing next to part 1.
        namen = [ziel_name] if len(fern) == 1 else [d.rsplit("/", 1)[-1] for d in fern]
        # A part of a split model that lies in the folder already is kept
        # as it is and not fetched again: replacing it would overwrite a
        # file nobody asked to replace.
        vorhanden = (
            {name for name in namen if (zielordner / name).is_file()} if len(fern) > 1 else set()
        )
        zu_holen = [name for name in namen if name not in vorhanden]
        fern_geholt = [d for d, name in zip(fern, namen, strict=True) if name not in vorhanden]
        adressen = [f"{BASIS}/{repo}/resolve/main/{datei}" for datei in fern_geholt]
        halbe = [
            _half_file(zielordner, name, adresse)
            for name, adresse in zip(zu_holen, adressen, strict=True)
        ]
        # A half file under the plain ``.teil`` name is no half file of any
        # address; it is of no use and is not left lying.
        for name in zu_holen:
            (zielordner / (name + UNFERTIG)).unlink(missing_ok=True)

        # A Hugging Face token, when the user set one: lifts rate limits and
        # opens gated models. Everything public works without it.
        kopf = {}
        wert = os.environ.get("HF_TOKEN", "").strip()
        if wert:
            kopf["Authorization"] = f"Bearer {wert}"

        try:
            # A split model's bar spans all parts, so its full size is asked
            # for before the first byte; one file learns it from its answer.
            if len(adressen) > 1 and self._stand:
                groessen = []
                for adresse in adressen:
                    if self._abbruch.is_set():
                        raise DownloadFehler("abgebrochen")
                    kopfantwort = httpx.head(
                        adresse, follow_redirects=True, timeout=60, headers=kopf
                    )
                    kopfantwort.raise_for_status()
                    groessen.append(int(kopfantwort.headers.get("content-length") or 0))
                # One unknown size makes the whole unknown — a partial sum
                # would run the bar past its end.
                self._stand.gesamt = sum(groessen) if all(groessen) else 0

            for adresse, halb in zip(adressen, halbe, strict=True):
                self._fetch_part(adresse, halb, kopf, single=len(adressen) == 1)

            # Only now does it become a model. Renaming is the one step that
            # makes a finished file visible to the runner — for a split model
            # only once every part has arrived.
            for halb, name in zip(halbe, zu_holen, strict=True):
                atomic_file.rename_onto(halb, zielordner / name)
                _version_file(halb).unlink(missing_ok=True)

            # The bond is recorded only after the file is truly in place, so a
            # cancelled or failed fetch leaves no dangling manifest entry.
            if gehoert_zu and rolle:
                modellzuordnung.eintragen(manifest_ordner, gehoert_zu, rolle, ziel_name)
            if nach is not None:
                nach()

            if self._stand:
                self._stand.geladen = sum((zielordner / name).stat().st_size for name in namen)
                self._stand.gesamt = self._stand.geladen
                self._stand.fertig = True

        except Exception as fehler:  # noqa: BLE001 - the reason belongs in the state
            for halb in halbe:
                _drop_half(halb)
            if self._stand:
                self._stand.fehler = (
                    fehler.grund if isinstance(fehler, DownloadFehler) else "fehlgeschlagen"
                )
