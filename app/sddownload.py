"""Fetching the picture generator itself, so nobody has to build it.

The sibling of ``app/serverdownload.py``, and for the same reason. Drawing a
picture needs ``sd-cli`` from stable-diffusion.cpp — a plain program with
prebuilt, MIT-licensed packages for every system this program ships on. A
machine that does not have it used to get a sentence ("the generator is not
set up on this PC") and no way to act on it. Now it gets a button: the
fitting package is fetched from a release of stable-diffusion.cpp,
unpacked into the user's data folder, and found there from then on.

Fetching instead of shipping is deliberate. The packages carry a few dozen
to a few hundred megabytes of shared libraries per system and, on Windows,
per GPU backend; putting every one of them into the installer would grow it
by more than the program itself, and building on the user's machine would
need a compiler nobody agreed to install. There is no Linux package — this
program does not ship a Linux build.

The build is pinned. "Latest" would mean every fresh installation gets a
different generator than the one this program was tested with — an update
stays a decision, not an accident.

**Windows can choose a GPU backend; every other system has one package.**
macOS carries its Metal support inside its single plain build and never
picks. Windows additionally offers CUDA, Vulkan and ROCm builds on top of
the CPU fallback — each variant is its own package, and each lands in its
own folder so switching between them never mixes two builds.

**Each build folder is flat.** The binary looks for its shared library next
to itself (``@executable_path`` on macOS, the same idea elsewhere), so an
archive is unpacked flat inside its folder and nothing is sorted afterwards.
"""

from __future__ import annotations

import os
import platform
import re
import shutil
import sys
import threading
import zipfile
from dataclasses import dataclass
from pathlib import Path

import httpx

# The progress record is the model server's, on purpose: what a download
# reports is the same three numbers whichever program it is fetching, and a
# second copy of it would only be a second thing to keep in step.
from app.serverdownload import Fortschritt

# The pinned stable-diffusion.cpp build and the packages per system.
#
# NOTE ON THE FILE NAMES: they carry the version of the machine that BUILT
# them ("macOS-26.6.2"), not the version they run on. That is the upstream
# project's naming, so a new pin means reading the release's asset list
# again rather than substituting the tag. Which is why the table stands
# here, in one place, complete, and nothing is assembled from parts at
# call time.
#
# There is no Linux package. This program does not ship a Linux build, so
# there is nothing to fetch a generator for there.
BAU = "master-948-228c707"


# Upstream stable-diffusion.cpp. Its releases carry the prebuilt packages
# this program fetches, and they are the ones an update is looked for in;
# a repository without published releases would leave every fresh
# installation without a generator.
_REPO = "leejet/stable-diffusion.cpp"


def _basis(bau: str) -> str:
    """Where a build's own packages are downloaded from — the pinned
    build's URL and a fetched release's both come from here, so the two
    never drift into two different templates."""
    return f"https://github.com/{_REPO}/releases/download/{bau}"


_BASIS = _basis(BAU)

# Where a newer build is read from before anybody presses anything — the
# repository's OWN newest release, not this program's pin.
_VEROEFFENTLICHUNGEN = f"https://api.github.com/repos/{_REPO}/releases/latest"

# One universal binary for both kinds of Mac — the arm64 package carries an
# x86_64 slice as well, so an Intel Mac is served by the same file. Metal
# support is built into this one build, so there is nothing to choose from.
_PAKET_DARWIN = "sd-master-228c707-bin-Darwin-macOS-26.6.2-arm64.zip"

# Windows offers a GPU backend on top of the CPU fallback. Each entry pairs
# the package name with its size in bytes, checked against the release
# itself — a caller building a picker needs the size without a second
# table. CUDA additionally needs the runtime archive below it: the shipped
# build fails to start without those DLLs on a machine that lacks a CUDA
# Toolkit, and whether one is installed cannot be reliably detected, so it
# is always fetched alongside.
_PAKETE_WIN32: dict[str, tuple[str, int]] = {
    "cpu": ("sd-master-228c707-bin-win-cpu-x64.zip", 17_517_910),
    "cuda12": ("sd-master-228c707-bin-win-cuda12-x64.zip", 337_979_057),
    "vulkan": ("sd-master-228c707-bin-win-vulkan-x64.zip", 30_098_372),
    "rocm": ("sd-master-228c707-bin-win-rocm-7.14.0-x64.zip", 251_568_217),
}
_CUDART: tuple[str, int] = ("cudart-sd-bin-win-cu12-x64.zip", 563_452_046)

VORGABE_VARIANTE = "cpu"

# Where it lands, and where ``bildrunner.programm_finden`` looks.
ORDNER = "stable-diffusion.cpp"


def program_name() -> str:
    """The program's file name on this system: Windows adds ``.exe``.

    Asked at every search rather than fixed at import, so a test that plays
    another system by switching ``sys.platform`` also looks for that
    system's name.
    """
    return "sd-cli.exe" if sys.platform == "win32" else "sd-cli"


BROCKEN = 1024 * 1024
UNFERTIG = ".teil"


def paketname(variante: str | None = None) -> str | None:
    """The pinned build's package for this machine, or nothing when there
    is none. ``veroeffentlichung_paket`` on ``pinned_build()``: the pinned table and
    a fetched release pass through one and the same platform switch."""
    package = veroeffentlichung_paket(pinned_build(), variante)
    return package[0] if package else None


def _bauordner_name_von(bau: str, variante: str) -> str:
    """The default variant keeps the plain build folder; every other
    variant gets its own, so a variant switch never mixes two builds. Takes
    the build tag explicitly, so a fetch of a newer release than ``BAU``
    lands under its own tag rather than the pinned one."""
    return bau if variante == VORGABE_VARIANTE else f"{bau}-{variante}"


# A build tag always has this shape: "<name>-<number>-<hash>". The name is
# "master" for the upstream builds this program fetched before, and
# "exe<N>" for the fork's own: a release is published for a pushed tag
# "exe<N>" and named "<tag>-<commit count>-<short hash>" (the fork's
# .github/workflows/build.yml). The number is what orders one release
# against another — the commit count, so the two kinds compare; a variant
# suffix, when present, is whatever comes after it.
_TAG_FORM = r"(?:master|exe\d+)"
_BAU_MUSTER = re.compile(rf"^({_TAG_FORM}-\d+-[0-9a-f]+)(?:-(.+))?$")


def _bau_nummer(bau: str) -> int | None:
    """The number out of a tag like "master-889-c678dfe" — or nothing when
    the tag does not have this shape (a release this program would not
    recognise as its own project)."""
    treffer = _BAU_MUSTER.match(bau)
    return int(treffer.group(1).split("-")[1]) if treffer else None


def _ordner_aufschluesseln(name: str) -> tuple[str, str] | None:
    """A build folder's name, split into its build tag and its variant —
    the variant is ``VORGABE_VARIANTE`` when the folder carries no suffix.
    Nothing when the name is not a build folder this program made at all."""
    treffer = _BAU_MUSTER.match(name)
    if not treffer:
        return None
    return treffer.group(1), (treffer.group(2) or VORGABE_VARIANTE)


def gueltige_variante(variante: str) -> bool:
    """Is this a variant this program knows how to fetch at all — on any
    platform. Used to refuse a typo before it ever reaches ``starten()``;
    whether THIS machine has a package for it is ``veroeffentlichung_paket``'s
    answer, given there."""
    return variante in _PAKETE_WIN32


def waehlbare_varianten() -> list[tuple[str, int]]:
    """The variants a picker could offer on THIS machine, with their
    download size. Empty outside win32 — every other system has one
    package and nothing to choose from."""
    if sys.platform != "win32":
        return []
    return [(variante, groesse) for variante, (_, groesse) in _PAKETE_WIN32.items()]


def _program_files(folder: Path, name: str) -> list[Path]:
    """Every file below ``folder`` called ``name``, in a fixed order.

    A fetch removes other build folders from its own thread (a finished one
    the older builds, a failed one what it unpacked), so a folder can vanish
    while it is being read. What was found before it vanished is kept and
    the rest counts as not there, instead of failing the request that read
    it.
    """
    found: list[Path] = []
    try:
        for path in folder.rglob(name):
            found.append(path)
    except OSError:
        pass
    return sorted(found)


def _holds_program(folder: Path, name: str) -> bool:
    """Whether a file called ``name`` lies anywhere below ``folder`` —
    stops at the first one. A folder that vanishes counts as empty."""
    try:
        return next(folder.rglob(name), None) is not None
    except OSError:
        return False


def _first_runnable(paths: list[Path]) -> Path | None:
    for path in paths:
        if path.is_file() and os.access(path, os.X_OK):
            return path
    return None


@dataclass
class _BuildFolder:
    """One unpacked build folder: where it is, its build tag, its variant."""

    folder: Path
    tag: str
    variant: str


def _chosen_build_folder(datenordner: Path, bau: str | None = None) -> _BuildFolder | None:
    """The build folder this program both runs and reports, by one rule on
    every system: the highest build number, and at the same number a folder
    named for a known variant (``_PAKETE_WIN32``) ahead of the plain one; a
    suffix this program never names a folder with ranks as plain. ``bau``
    narrows the choice to that one build. The root is read once.

    More than one build folder can stay on disk for good: the cleanup after
    a fetch leaves a NEWER build standing (``_andere_bauten_entfernen``).
    """
    root = Path(datenordner).expanduser() / ORDNER
    try:
        entries = sorted(root.iterdir())
    except OSError:
        return None
    name = program_name()
    chosen: _BuildFolder | None = None
    best: tuple[int, bool] | None = None
    for entry in entries:
        parts = _ordner_aufschluesseln(entry.name)
        if parts is None:
            continue
        entry_tag, variant = parts
        number = _bau_nummer(entry_tag)
        if number is None or (bau is not None and entry_tag != bau):
            continue
        rank = (number, variant != VORGABE_VARIANTE and variant in _PAKETE_WIN32)
        # Strictly greater: among equal folders the first by name stays. A
        # folder that cannot outrank the pick is not searched at all.
        if best is not None and rank <= best:
            continue
        if not entry.is_dir() or not _holds_program(entry, name):
            continue
        chosen, best = _BuildFolder(entry, entry_tag, variant), rank
    return chosen


def installierter_bau(datenordner: Path) -> str | None:
    """The tag of whichever build is unpacked and runnable, or nothing.

    Not just the pinned ``BAU`` any more: a fetch can now land
    a newer release than the one this program ships with, and the folder it
    lands in carries THAT release's own tag. When more than one build
    folder sits on disk at once, it is the one ``_chosen_build_folder``
    picks — the build ``gefundenes_programm`` starts.
    """
    chosen = _chosen_build_folder(datenordner)
    return chosen.tag if chosen else None


def _hand_install(datenordner: Path) -> Path | None:
    """A generator somebody unpacked into the bare folder by hand, or
    nothing. It runs ahead of every build folder and belongs to the user."""
    direkt = Path(datenordner).expanduser() / ORDNER / program_name()
    if direkt.is_file() and os.access(direkt, os.X_OK):
        return direkt
    return None


def restorable(datenordner: Path) -> bool:
    """Whether there is a tested build to go back to: the build that runs
    was fetched and is not the pinned one. Beside a hand install there is
    nothing to offer — it runs whatever is fetched, and it blocks a fetch."""
    if _hand_install(datenordner) is not None:
        return False
    installed = installierter_bau(datenordner)
    return installed is not None and installed != BAU


def installierte_variante(datenordner: Path, bau: str | None = None) -> str | None:
    """Which variant the build that runs is, read off its build folder's
    name — or nothing when there is none. The folder is the one
    ``gefundenes_programm`` starts (``_chosen_build_folder``), so the name
    shown is the build that runs. A hand install in the bare root has no
    variant name to read and answers nothing here; it is still found and
    used by ``gefundenes_programm``, it just cannot be named.

    The plain build folder names a variant only on win32, where it holds
    the CPU build of the table above. Every other system has one universal
    package whose name has no backend in it — macOS runs its Metal support
    inside that same build — and refuses to fetch any other variant
    (``veroeffentlichung_paket``). Its plain folder answers nothing, so the
    caller keeps to its plain sentence instead of a name from the Windows
    table; a folder named for a variant, left from before that refusal, is
    still read by its name.

    ``bau`` narrows the answer to that build, for a caller that already
    holds it from ``installierter_bau()``. Either way the folder is read
    once.
    """
    chosen = _chosen_build_folder(datenordner, bau)
    if chosen is None:
        return None
    if chosen.variant == VORGABE_VARIANTE and sys.platform != "win32":
        return None
    return chosen.variant


# The release's file names carry the same shape the pinned table above
# already assumes — hash and, on macOS, the building machine's own OS
# version are the two parts that change release to release and cannot be
# guessed, so they are left free; everything else is matched exactly.
_MUSTER_DARWIN = re.compile(rf"^sd-{_TAG_FORM}-[0-9a-f]+-bin-Darwin-macOS-[\d.]+-arm64\.zip$")
_MUSTER_WIN32: dict[str, re.Pattern[str]] = {
    "cpu": re.compile(rf"^sd-{_TAG_FORM}-[0-9a-f]+-bin-win-cpu-x64\.zip$"),
    "cuda12": re.compile(rf"^sd-{_TAG_FORM}-[0-9a-f]+-bin-win-cuda12-x64\.zip$"),
    "vulkan": re.compile(rf"^sd-{_TAG_FORM}-[0-9a-f]+-bin-win-vulkan-x64\.zip$"),
    "rocm": re.compile(rf"^sd-{_TAG_FORM}-[0-9a-f]+-bin-win-rocm-[\d.]+-x64\.zip$"),
}


@dataclass
class Veroeffentlichung:
    """One build of the generator: its tag, its build number, and — for
    every package this program knows how to use — the one asset that
    matches it. The pinned build is one (``pinned_build()``, from the tables
    above); a release read straight off GitHub is another, found by
    matching the release's own file list rather than assembled from the
    tag, because the file names carry the building machine's own OS
    version (see the note above ``BAU``)."""

    bau: str
    nummer: int
    darwin: tuple[str, int | None] | None
    varianten: dict[str, tuple[str, int]]
    cudart: int | None


def pinned_build() -> Veroeffentlichung:
    """The pinned build, described the same way as a fetched release, so a
    fetch of either takes one path. Made from the tables above at each call,
    so it can never drift from them. The Mac package's size is not in those
    tables and nothing reads it: sizes serve the Windows picker and the
    cuda12 progress bar only."""
    number = _bau_nummer(BAU)
    if number is None:
        raise RuntimeError(f"The pinned build tag {BAU!r} does not contain a build number.")
    return Veroeffentlichung(
        bau=BAU,
        nummer=number,
        darwin=(_PAKET_DARWIN, None),
        varianten=dict(_PAKETE_WIN32),
        cudart=_CUDART[1],
    )


def _einzelner_treffer(
    namen_und_groessen: dict[str, int], muster: re.Pattern[str]
) -> tuple[str, int] | None:
    """The one asset matching ``muster`` — or nothing when there is not
    exactly one. Several matches and none are the same case here: a name
    this program cannot pin down with certainty is a name it does not guess
    at."""
    treffer = [
        (name, groesse) for name, groesse in namen_und_groessen.items() if muster.match(name)
    ]
    return treffer[0] if len(treffer) == 1 else None


def neueste_veroeffentlichung(zeitgrenze: float = 10.0) -> Veroeffentlichung | None:
    """The newest release's tag and asset list, read straight off the
    project's own GitHub page — no access token, a short deadline. Nothing
    when the request fails, times out, or the release carries no tag this
    program recognises as one of its own (``_bau_nummer`` says so).
    """
    try:
        antwort = httpx.get(
            _VEROEFFENTLICHUNGEN,
            timeout=zeitgrenze,
            headers={"Accept": "application/vnd.github+json"},
        )
        antwort.raise_for_status()
        daten = antwort.json()
    except (httpx.HTTPError, ValueError):
        return None

    bau = daten.get("tag_name")
    nummer = _bau_nummer(bau) if isinstance(bau, str) else None
    if nummer is None:
        return None

    namen_und_groessen = {
        eintrag["name"]: eintrag["size"]
        for eintrag in daten.get("assets") or []
        if isinstance(eintrag, dict)
        and isinstance(eintrag.get("name"), str)
        and isinstance(eintrag.get("size"), int)
    }

    return Veroeffentlichung(
        bau=bau,
        nummer=nummer,
        darwin=_einzelner_treffer(namen_und_groessen, _MUSTER_DARWIN),
        varianten={
            variante: treffer
            for variante, muster in _MUSTER_WIN32.items()
            if (treffer := _einzelner_treffer(namen_und_groessen, muster)) is not None
        },
        cudart=namen_und_groessen.get(_CUDART[0]),
    )


def neuere_fassung(eigener_bau: str, zeitgrenze: float = 10.0) -> Veroeffentlichung | None:
    """The newest release, only when it is actually ahead of
    ``eigener_bau`` — nothing when it is the same, unreachable, or its tag
    cannot be read as a build number."""
    veroeffentlichung = neueste_veroeffentlichung(zeitgrenze)
    if veroeffentlichung is None or not ist_voraus(veroeffentlichung, eigener_bau):
        return None
    return veroeffentlichung


def ist_voraus(veroeffentlichung: Veroeffentlichung, eigener_bau: str) -> bool:
    """Whether a release is ahead of ``eigener_bau``. A build whose name
    carries no number is taken as behind any release — it cannot be shown
    to be current."""
    eigene_nummer = _bau_nummer(eigener_bau)
    return eigene_nummer is None or veroeffentlichung.nummer > eigene_nummer


def veroeffentlichung_paket(
    veroeffentlichung: Veroeffentlichung, variante: str | None = None
) -> tuple[str, int | None] | None:
    """The asset ``veroeffentlichung`` carries for THIS machine and
    ``variante`` — the one platform switch, for the pinned build and a
    fetched release alike. Only win32 offers variants; on any other system
    a variant other than the default has no package, so it is refused
    rather than fetched into a folder named after a backend it does not
    have."""
    maschine = platform.machine().lower()
    if sys.platform == "darwin":
        if (variante or VORGABE_VARIANTE) != VORGABE_VARIANTE:
            return None
        return veroeffentlichung.darwin if maschine in {"arm64", "aarch64", "x86_64"} else None
    if sys.platform == "win32":
        if maschine not in {"x64", "amd64", "x86_64"}:
            return None
        return veroeffentlichung.varianten.get(variante or VORGABE_VARIANTE)
    return None


class SddownloadFehler(Exception):
    """Carries the key of the sentence to show, not the sentence itself."""

    def __init__(self, grund: str) -> None:
        super().__init__(grund)
        self.grund = grund


def gefundenes_programm(datenordner: Path) -> Path | None:
    """The unpacked sd-cli below the data folder, or nothing.

    Three places, in this order: the bare folder, which is where somebody
    who unpacked a build by hand puts it; the build folder a fetch landed
    in — one level down, named after the build, so a later pin never mixes
    two builds in one directory — and of several, the one
    ``installierte_variante`` reports from (``_chosen_build_folder``), so
    the build the panel names is the build that runs; and failing both,
    any runnable sd-cli below the root, as it was always found.
    """
    root = Path(datenordner).expanduser() / ORDNER
    if not root.is_dir():
        return None
    name = program_name()
    direkt = root / name
    if direkt.is_file() and os.access(direkt, os.X_OK):
        return direkt
    chosen = _chosen_build_folder(datenordner)
    if chosen is not None:
        program = _first_runnable(_program_files(chosen.folder, name))
        if program is not None:
            return program
    return _first_runnable(_program_files(root, name))


class Sddownload:
    """One fetch of the picture generator, watchable while it runs."""

    def __init__(self, datenordner: Path) -> None:
        self._datenordner = Path(datenordner).expanduser()
        self._ordner = self._datenordner / ORDNER
        self._stand: Fortschritt | None = None
        self._schloss = threading.Lock()

    def stand(self) -> Fortschritt | None:
        return self._stand

    def laeuft(self) -> bool:
        return self._stand is not None and not self._stand.fertig and not self._stand.fehler

    def starten(
        self,
        variante: str | None = None,
        veroeffentlichung: Veroeffentlichung | None = None,
        replace_newer: bool = False,
    ) -> Fortschritt:
        """Fetches the pinned build (``pinned_build()``), or — given
        ``veroeffentlichung`` — a newer release read off GitHub; both are
        described alike and take the same path. Either way the new build lands in
        its own folder; an existing, older one is only removed once the
        fetch has succeeded (``_andere_bauten_entfernen``), so a failed
        update leaves the working install exactly as it was.

        ``replace_newer`` is the way back from an update: the fetched build
        takes the place of a newer one as well, which the plain fetch
        leaves standing. The build is fetched anew even where its folder
        is still on disk — beside a newer one it is not the build that
        runs, and nothing says it is whole."""
        variante = variante or VORGABE_VARIANTE
        build = veroeffentlichung or pinned_build()
        with self._schloss:
            if self.laeuft():
                raise SddownloadFehler("laeuft_schon")
            # A hand install sits loose in the root, ahead of any build
            # folder this program would ever make — it belongs to the user
            # and blocks a fetch no matter which variant is asked for.
            if self._hand_installation() is not None:
                raise SddownloadFehler("schon_da")
            bauordner = _bauordner_name_von(build.bau, variante)
            if not replace_newer and self._bau_vorhanden(bauordner) is not None:
                raise SddownloadFehler("schon_da")
            paket = veroeffentlichung_paket(build, variante)
            # cuda12 needs the runtime archive beside it; a release that
            # does not carry it uniquely is a release this program
            # cannot safely offer that variant of, not a guess to make.
            if paket is None or (variante == "cuda12" and build.cudart is None):
                raise SddownloadFehler("kein_paket")

            self._stand = Fortschritt(geladen=0, gesamt=0)
            threading.Thread(
                target=self._holen, args=(variante, build, paket[0], replace_newer), daemon=True
            ).start()
            return self._stand

    def _hand_installation(self) -> Path | None:
        return _hand_install(self._datenordner)

    def _bau_vorhanden(self, bauordner: str) -> Path | None:
        return _first_runnable(_program_files(self._ordner / bauordner, program_name()))

    def _holen(
        self, variante: str, build: Veroeffentlichung, name: str, replace_newer: bool = False
    ) -> None:
        bauordner = _bauordner_name_von(build.bau, variante)
        basis = _basis(build.bau)
        archiv = self._ordner / (name + UNFERTIG)
        # cuda12 needs the runtime archive right beside the build — without
        # it the binary cannot find its DLLs and refuses to start.
        cudart_name = _CUDART[0] if variante == "cuda12" else None
        cudart_archiv = self._ordner / (cudart_name + UNFERTIG) if cudart_name else None

        if cudart_name and self._stand:
            # Fixed upfront, not measured from either response: measuring
            # would only know the first file's length while it downloads, so
            # the bar would reach 100% and then fall back once the total
            # grows for the second file. `starten()` already made sure both
            # sizes exist before this thread was started.
            haupt_groesse = build.varianten[variante][1]
            cudart_groesse = build.cudart
            assert cudart_groesse is not None
            self._stand.gesamt = haupt_groesse + cudart_groesse

        try:
            # Inside the guard: a folder that cannot be made (a file or a
            # dangling link in its place, no right to write) ended this
            # thread before the state could say so, and the bar stood at
            # nought for good.
            self._ordner.mkdir(parents=True, exist_ok=True)
            self._laden(basis, name, archiv, fest=cudart_name is not None)
            self._entpacken(archiv, bauordner)
            archiv.unlink(missing_ok=True)

            if cudart_name:
                assert cudart_archiv is not None
                self._laden(basis, cudart_name, cudart_archiv, fest=True)
                self._entpacken(cudart_archiv, bauordner)
                cudart_archiv.unlink(missing_ok=True)

            programm = self._rechte_setzen(bauordner)
            if programm is None:
                raise SddownloadFehler("fehlgeschlagen")

            # Only one build stays on disk — a leftover from a different
            # variant, or from an older release, would otherwise sit next to
            # the new one, unused. The old one stays until this point: a
            # failed fetch above never reaches here, so it is never removed.
            self._andere_bauten_entfernen(bauordner, replace_newer)

            if self._stand:
                self._stand.fertig = True
        except Exception as fehler:  # noqa: BLE001 - the reason belongs in the state
            archiv.unlink(missing_ok=True)
            if cudart_archiv is not None:
                cudart_archiv.unlink(missing_ok=True)
            shutil.rmtree(self._ordner / bauordner, ignore_errors=True)
            if self._stand:
                self._stand.fehler = (
                    fehler.grund if isinstance(fehler, SddownloadFehler) else "fehlgeschlagen"
                )

    def _laden(self, basis: str, name: str, ziel: Path, fest: bool = False) -> None:
        """One archive, streamed to disk. Called once for the main package
        and, for cuda12, a second time for the runtime archive — both add to
        the same ``Fortschritt``, so ``geladen`` runs through both downloads
        and never resets between them.

        ``fest`` means the caller already fixed ``gesamt`` upfront (cuda12):
        this call must not also measure it from the response, or the total
        would count the same bytes twice.
        """
        with httpx.stream(
            "GET", f"{basis}/{name}", follow_redirects=True, timeout=60
        ) as antwort:
            antwort.raise_for_status()
            if self._stand and not fest:
                self._stand.gesamt += int(antwort.headers.get("content-length") or 0)
            with ziel.open("wb") as schreiben:
                for brocken in antwort.iter_bytes(BROCKEN):
                    schreiben.write(brocken)
                    if self._stand:
                        self._stand.geladen += len(brocken)

    def _entpacken(self, archiv: Path, bauordner: str) -> None:
        """Into a folder named after the build (and variant), so an update
        or a variant switch never mixes two builds.

        Flat inside that folder, because the binary finds its shared library
        beside itself and nowhere else. Every package is a zip file — the
        upstream project publishes nothing else.
        """
        ziel = self._ordner / bauordner
        ziel.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(archiv) as zf:
            zf.extractall(ziel)

    def _rechte_setzen(self, bauordner: str) -> Path | None:
        """The executable bit, which a zip file does not carry across.

        Python's zip reader drops the mode bits, so an unpacked ``sd-cli``
        arrives without permission to run — and a generator that cannot be
        started is the same as one that was never fetched. The search that
        follows deliberately looks for the FILE first and sets the bit
        afterwards: looking for something executable before there is
        anything executable would never find it.
        """
        ziel = self._ordner / bauordner
        gefunden = sorted(ziel.rglob(program_name()))
        if not gefunden:
            return None
        programm = gefunden[0]
        if sys.platform != "win32":
            for datei in programm.parent.iterdir():
                # The shared libraries beside it need the bit as well on
                # some systems, and setting it on a plain text file next to
                # them costs nothing.
                if datei.is_file():
                    datei.chmod(datei.stat().st_mode | 0o111)
        return programm

    def _andere_bauten_entfernen(self, aktuell: str, newer_too: bool = False) -> None:
        """Only folders this program itself names (``_BAU_MUSTER``) qualify —
        loose files directly in the root are a hand install and are never
        touched, they belong to the user.

        A folder from a NEWER release than the one just landed is left
        standing, though: the plain variant picker still only ever fetches
        the pinned ``BAU``, and running it after an update to a newer
        release must not silently throw that release away — cleanup is for
        catching up an old build, not for undoing a newer one.

        ``newer_too`` is that undoing, asked for: the build just landed is
        the one to run, so a newer one goes as well — left standing, it
        would still be the build that is picked.
        """
        aufgeschluesselt = _ordner_aufschluesseln(aktuell)
        aktuelle_nummer = _bau_nummer(aufgeschluesselt[0]) if aufgeschluesselt else None
        for eintrag in self._ordner.iterdir():
            if not eintrag.is_dir() or eintrag.name == aktuell:
                continue
            eintrag_teile = _ordner_aufschluesseln(eintrag.name)
            if eintrag_teile is None:
                continue
            eintrag_nummer = _bau_nummer(eintrag_teile[0]) if eintrag_teile else None
            if (
                not newer_too
                and aktuelle_nummer is not None
                and eintrag_nummer is not None
                and eintrag_nummer > aktuelle_nummer
            ):
                continue
            shutil.rmtree(eintrag, ignore_errors=True)
