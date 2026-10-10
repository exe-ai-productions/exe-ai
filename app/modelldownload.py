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

A split GGUF (``-00001-of-0000N`` … ``-0000N-of-0000N``) is fetched whole:
naming part 1 fetches every part into the same folder, and only when all of
them are there are they renamed. The server is started with part 1 and finds
the others next to it.
"""

from __future__ import annotations

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
    ) -> Fortschritt:
        """``ziel`` is the local name, when it must differ from the remote one.

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
            if (zielordner / ziel).is_file():
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
        halbe = [zielordner / (name + UNFERTIG) for name in namen]
        adressen = [f"{BASIS}/{repo}/resolve/main/{datei}" for datei in fern]

        # A Hugging Face token, when the user set one: lifts rate limits and
        # opens gated models. Everything public works without it.
        import os

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
                with httpx.stream(
                    "GET", adresse, follow_redirects=True, timeout=60, headers=kopf
                ) as antwort:
                    antwort.raise_for_status()
                    if len(adressen) == 1 and self._stand:
                        self._stand.gesamt = int(antwort.headers.get("content-length") or 0)

                    with halb.open("wb") as schreiben:
                        for brocken in antwort.iter_bytes(BROCKEN):
                            if self._abbruch.is_set():
                                raise DownloadFehler("abgebrochen")
                            schreiben.write(brocken)
                            if self._stand:
                                self._stand.geladen += len(brocken)

            # Only now does it become a model. Renaming is the one step that
            # makes a finished file visible to the runner — for a split model
            # only once every part has arrived.
            for halb, name in zip(halbe, namen, strict=True):
                atomic_file.rename_onto(halb, zielordner / name)

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
                halb.unlink(missing_ok=True)
            if self._stand:
                self._stand.fehler = (
                    fehler.grund if isinstance(fehler, DownloadFehler) else "fehlgeschlagen"
                )
