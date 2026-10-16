"""Fetching the model server itself, so nobody has to install it.

The program starts models with llama.cpp's ``llama-server`` — a plain
program with prebuilt, MIT-licensed packages for every system. A machine
that does not have it gets a button instead of an instruction: the fitting
package is fetched from the official llama.cpp release, unpacked into the
user's data folder, and found there from then on.

The build number is pinned. "Latest" would mean every fresh installation
gets a different server than the one this program was tested with — an
update stays a decision, not an accident. That decision has a button of its
own: the newest build is fetched when somebody asks for it, and the pinned
one comes back the same way.

Every build lies in a folder named after its tag — and, where it is not the
CPU build, its variant: ``b11429`` and ``b11429-cuda12``. The one that runs
is the one with the highest build number, and a fetch that succeeded removes
the others — so the folder on disk is the whole answer to "which build is
this, and which variant", and nothing has to be remembered beside it.

Windows on x64 offers the variants of the same build the picture generator
offers (``app/sddownload.py``): the CPU build, CUDA, Vulkan and ROCm. The
CPU build stays the default — it runs everywhere; the graphics card builds
are a choice somebody makes, not a gamble on drivers.

Same shape as the model download next door: one at a time, watchable
progress, a part-file until complete. The archive is unpacked next to the
download and the archive itself removed — what remains is the folder the
runner searches.
"""

from __future__ import annotations

import logging
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import threading
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import httpx

from app import atomic_file
from app.no_console import no_window

log = logging.getLogger(__name__)

# The pinned llama.cpp build and the packages per system. CPU builds on
# purpose where a GPU flavour would gamble on drivers: they run everywhere,
# and macOS carries its Metal support inside the plain package. Windows on
# x64 is the one system with a choice, in the table further down.
BUILD = "b11429"

_REPO = "ggml-org/llama.cpp"

# The project's releases, newest first. Its "latest" release is a version
# tag that carries no packages at all; the packages hang on the build tags,
# and those are published as pre-releases — so the list is read, not the
# one release the project calls latest.
_RELEASES = f"https://api.github.com/repos/{_REPO}/releases"

# The package of each system, with the build tag left open: every build
# names its files the same way, so the tag is all that changes.
_PAKETE: dict[tuple[str, str], str] = {
    ("darwin", "arm64"): "llama-{build}-bin-macos-arm64.tar.gz",
    ("darwin", "x86_64"): "llama-{build}-bin-macos-x64.tar.gz",
    ("win32", "arm64"): "llama-{build}-bin-win-cpu-arm64.zip",
    ("linux", "x86_64"): "llama-{build}-bin-ubuntu-x64.tar.gz",
    ("linux", "aarch64"): "llama-{build}-bin-ubuntu-arm64.tar.gz",
}

# Windows on x64: the variants of one build, each with its package (tag left
# open) and its size in bytes, measured on the pinned build's release. CUDA
# additionally needs the runtime archive below: the shipped build fails to
# start without those DLLs on a machine that lacks a CUDA Toolkit, and
# whether one is installed cannot be told reliably, so it is always fetched
# alongside — the name carries no build tag, it hangs on the same release.
_PAKETE_WIN32: dict[str, tuple[str, int]] = {
    "cpu": ("llama-{build}-bin-win-cpu-x64.zip", 19_398_918),
    "cuda12": ("llama-{build}-bin-win-cuda-12.4-x64.zip", 264_478_423),
    "vulkan": ("llama-{build}-bin-win-vulkan-x64.zip", 33_337_769),
    "rocm": ("llama-{build}-bin-win-rocm-10.0-x64.zip", 256_958_369),
}
_CUDART: tuple[str, int] = ("cudart-llama-bin-win-cuda-12.4-x64.zip", 391_443_627)

VORGABE_VARIANTE = "cpu"

BROCKEN = 1024 * 1024
UNFERTIG = ".teil"

# Where it lands, and where the runner looks.
ORDNER = "llama.cpp"

# A build tag is the letter b and the build number, nothing else.
_BUILD_TAG = re.compile(r"b(\d+)")

# A build folder: the tag, and for a variant other than the default its name.
_BAUORDNER = re.compile(r"(b\d+)(?:-([a-z0-9]+))?")

# The two ways the program itself states its build: the number after the
# word "build", since the project numbers its versions, and before that the
# bare number.
_VERSION_LINES = (
    re.compile(r"\(build (\d+)"),
    re.compile(r"^version:\s*(\d+)\s*\(", re.MULTILINE),
)

# How long a program may take to say its version.
_VERSION_TIMEOUT = 5.0


def _basis(build: str) -> str:
    """Where a build's own packages are downloaded from."""
    return f"https://github.com/{_REPO}/releases/download/{build}"


def _maschine() -> str:
    maschine = platform.machine().lower()
    if maschine == "x64":
        maschine = "amd64" if sys.platform == "win32" else "x86_64"
    return maschine


def paketname(build: str = BUILD, variante: str | None = None) -> str | None:
    """The package of ``build`` for this machine and ``variante`` (the CPU
    build where none is named), or nothing when llama.cpp has none. Only
    Windows on x64 has variants: on any other machine a variant other than
    the default has no package, and is refused rather than fetched into a
    folder named after a backend the machine does not have."""
    variante = variante or VORGABE_VARIANTE
    maschine = _maschine()
    if sys.platform == "win32" and maschine == "amd64":
        paket = _PAKETE_WIN32.get(variante)
        return paket[0].format(build=build) if paket else None
    if variante != VORGABE_VARIANTE:
        return None
    schluessel = (
        "win32" if sys.platform == "win32" else "darwin" if sys.platform == "darwin" else "linux"
    )
    form = _PAKETE.get((schluessel, maschine))
    return form.format(build=build) if form else None


def waehlbare_varianten() -> list[tuple[str, int]]:
    """The variants a picker could offer on THIS machine, with the size of
    what each one downloads — CUDA with its runtime. Empty everywhere but
    Windows on x64: every other machine has one package and nothing to
    choose from."""
    if sys.platform != "win32" or _maschine() != "amd64":
        return []
    return [
        (variante, groesse + (_CUDART[1] if variante == "cuda12" else 0))
        for variante, (_, groesse) in _PAKETE_WIN32.items()
    ]


def bauordner_name(build: str, variante: str | None = None) -> str:
    """The default variant keeps the plain build folder; every other one
    gets its own, so a variant switch never mixes two builds."""
    variante = variante or VORGABE_VARIANTE
    return build if variante == VORGABE_VARIANTE else f"{build}-{variante}"


def _bauordner_teile(name: str) -> tuple[str, str] | None:
    """A build folder's name, split into its tag and its variant — the
    default variant when the name carries none. Nothing when the name is no
    build folder of this program: a suffix it never names a folder with
    does not qualify."""
    treffer = _BAUORDNER.fullmatch(name)
    if treffer is None:
        return None
    variante = treffer.group(2)
    if variante is not None and variante not in _PAKETE_WIN32:
        return None
    return treffer.group(1), variante or VORGABE_VARIANTE


def build_number(build: str) -> int | None:
    """The number out of a tag like "b11429" — or nothing when the name is
    not a build tag."""
    match = _BUILD_TAG.fullmatch(build)
    return int(match.group(1)) if match else None


def _server_name() -> str:
    return "llama-server.exe" if sys.platform == "win32" else "llama-server"


@dataclass
class Fortschritt:
    geladen: int
    gesamt: int
    fertig: bool = False
    fehler: str | None = None

    @property
    def anteil(self) -> float:
        return round(self.geladen / self.gesamt, 4) if self.gesamt else 0.0


class ServerdownloadFehler(Exception):
    """Carries the key of the sentence to show, not the sentence itself."""

    def __init__(self, grund: str) -> None:
        super().__init__(grund)
        self.grund = grund


# Build folders a fetch is unpacking into right now. An archive is written
# out file by file, so for a moment the folder holds a server that is not
# whole yet — and a server starting in that moment must still get the build
# that was there before.
_unpacking: set[Path] = set()
_unpacking_lock = threading.Lock()


def _is_unpacking(folder: Path) -> bool:
    with _unpacking_lock:
        if not _unpacking:
            return False
        busy = set(_unpacking)
    try:
        return folder.resolve() in busy
    except OSError:
        return False


def _own_build(data_folder: Path) -> tuple[str, str, Path] | None:
    """The fetched build that runs, as its tag, its variant and its server:
    of the build folders below the data folder, the one with the highest
    build number that holds a server — and at the same number a folder named
    for a variant ahead of the plain one, so a build fetched in two variants
    runs as the one that was fetched last, never as the one before it.

    A build older than the pinned one does not count. It was left behind by
    an earlier version of this program, which pinned it — it is not the
    server this version was tested with, and finding it would keep the
    pinned one from being fetched.
    """
    root = Path(data_folder).expanduser() / ORDNER
    try:
        entries = list(root.iterdir())
    except OSError:
        return None
    floor = build_number(BUILD) or 0
    candidates: list[tuple[tuple[int, bool], str, str, Path]] = []
    for entry in entries:
        parts = _bauordner_teile(entry.name)
        number = build_number(parts[0]) if parts else None
        if parts is None or number is None or number < floor:
            continue
        candidates.append(((number, parts[1] != VORGABE_VARIANTE), parts[0], parts[1], entry))
    candidates.sort(key=lambda candidate: candidate[0], reverse=True)
    name = _server_name()
    for _, tag, variant, entry in candidates:
        if _is_unpacking(entry):
            continue
        try:
            hits = sorted(entry.rglob(name))
        except OSError:
            # A fetch removes the other builds from its own thread, so a
            # folder can vanish while it is being read.
            continue
        if hits:
            return tag, variant, hits[0]
    return None


def gefundener_server(ordner: Path) -> Path | None:
    """The unpacked llama-server below the data folder, or nothing — of
    several fetched builds, the one with the highest build number."""
    own = _own_build(ordner)
    return own[2] if own else None


def installed_build(data_folder: Path) -> str | None:
    """The tag of the fetched build that runs, or nothing."""
    own = _own_build(data_folder)
    return own[0] if own else None


def installed_variant(data_folder: Path) -> str | None:
    """The variant of the fetched build that runs, read off its folder's
    name — or nothing when there is none, or when the machine has no
    variants to name (a plain folder there is the one package it has)."""
    own = _own_build(data_folder)
    if own is None or not waehlbare_varianten():
        return None
    return own[1]


def installed_folder(data_folder: Path) -> Path | None:
    """The build folder of the fetched build that runs, or nothing — what
    lies in it belongs to the same build."""
    own = _own_build(data_folder)
    if own is None:
        return None
    root = Path(data_folder).expanduser() / ORDNER
    return root / own[2].relative_to(root).parts[0]


def fetched_build(program: Path, data_folder: Path) -> str | None:
    """The tag of the build folder ``program`` lies in — or nothing when
    it is not a build this program fetched."""
    parts = _fetched_parts(program, data_folder)
    return parts[0] if parts else None


def fetched_variant(program: Path, data_folder: Path) -> str | None:
    """The variant of the build folder ``program`` lies in — or nothing when
    it is not a build this program fetched."""
    parts = _fetched_parts(program, data_folder)
    return parts[1] if parts else None


def _fetched_parts(program: Path, data_folder: Path) -> tuple[str, str] | None:
    root = Path(data_folder).expanduser() / ORDNER
    try:
        inside = Path(program).resolve().relative_to(root.resolve())
    except (OSError, ValueError):
        return None
    if not inside.parts:
        return None
    parts = _bauordner_teile(inside.parts[0])
    if parts is None or build_number(parts[0]) is None:
        return None
    return parts


def stated_build(program: Path) -> str | None:
    """Which build a program this one did not fetch says it is, as a build
    tag — or nothing when it does not say, see ``_stated_build``."""
    number = _stated_build(Path(program))
    return f"b{number}" if number is not None else None


# What a program said its build is, by the file it was read from. Asking
# means starting the program, and the window asks every two seconds — so
# each file is asked once, and again only after it changed on disk.
_stated: dict[tuple[str, int, int], int | None] = {}


def _stated_build(program: Path) -> int | None:
    """The build number a llama-server states when asked for its version,
    or nothing when it does not answer in a form read here.

    The answer is kept with the file's size and change time, so a program
    replaced by a package manager is asked again, and one that never
    answers is not started over and over.
    """
    try:
        facts = program.stat()
    except OSError:
        return None
    key = (str(program), facts.st_mtime_ns, facts.st_size)
    if key in _stated:
        return _stated[key]
    number: int | None = None
    try:
        answer = subprocess.run(
            [str(program), "--version"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=_VERSION_TIMEOUT,
            **no_window(),
        )
    except (OSError, subprocess.TimeoutExpired):
        answer = None
    if answer is not None:
        # The version goes to the error stream in some builds and to the
        # plain one in others; both are read.
        number = stated_build_number(f"{answer.stdout}\n{answer.stderr}")
    _stated[key] = number
    return number


def stated_build_number(text: str) -> int | None:
    """The build number out of what ``llama-server --version`` prints, in
    either of its two forms — "version: 10310 (cb26014d9)" and
    "version: 0.6.0 (build 11429, commit d81235049)"."""
    for pattern in _VERSION_LINES:
        match = pattern.search(text)
        if match:
            return int(match.group(1))
    return None


def newest_build(timeout: float = 10.0) -> str | None:
    """The newest build this machine can fetch, read straight off the
    project's release list — no access token, a short deadline.

    The topmost entry whose tag is a build tag and which carries this
    machine's package. An entry without a build number is the project's
    version release, which has no packages; one without the package is a
    build still being published, or one this system was left out of.
    Nothing when the list cannot be read or holds no such entry.
    """
    if paketname() is None:
        return None
    try:
        answer = httpx.get(
            _RELEASES,
            timeout=timeout,
            headers={"Accept": "application/vnd.github+json"},
        )
        answer.raise_for_status()
        releases = answer.json()
    except (httpx.HTTPError, ValueError):
        return None
    if not isinstance(releases, list):
        return None
    for release in releases:
        build = release.get("tag_name") if isinstance(release, dict) else None
        if not isinstance(build, str) or build_number(build) is None:
            continue
        wanted = paketname(build)
        if any(
            isinstance(asset, dict) and asset.get("name") == wanted
            for asset in release.get("assets") or []
        ):
            return build
    return None


def is_ahead(build: str, running: str | None) -> bool:
    """Whether ``build`` is ahead of the build that runs. A program whose
    build cannot be told is taken as behind any build — it cannot be shown
    to be current."""
    number = build_number(build)
    if number is None:
        return False
    running_number = build_number(running) if running else None
    return running_number is None or number > running_number


def _groesse(url: str) -> int:
    """How many bytes the file at ``url`` has, read off the head of the
    answer — the body is not read, the connection is closed with it."""
    with httpx.stream("GET", url, follow_redirects=True, timeout=60) as antwort:
        antwort.raise_for_status()
        return int(antwort.headers.get("content-length") or 0)


class ServerRestart(Protocol):
    """What a fetch asks of the servers that run while a new build comes in
    (``app/server_restart.py``): end them, start them again once the new
    build is the one that starts — False when that failed — and forget them
    when the fetch is over."""

    def stop(self) -> None: ...

    def start(self) -> bool: ...

    def forget(self) -> None: ...


class Serverdownload:
    """One fetch of the model server, watchable while it runs.

    ``restart`` stands for the servers that run when a build comes in: they
    start again on it, and the build that ran until then stays on disk until
    every one of them has loaded its model. Without one the old builds go as
    soon as the new one is unpacked.
    """

    def __init__(self, ordner: Path, restart: ServerRestart | None = None) -> None:
        self._ordner = Path(ordner).expanduser() / ORDNER
        self._stand: Fortschritt | None = None
        self._schloss = threading.Lock()
        self._restart = restart

    def stand(self) -> Fortschritt | None:
        return self._stand

    def laeuft(self) -> bool:
        return self._stand is not None and not self._stand.fertig and not self._stand.fehler

    def starten(
        self,
        build: str | None = None,
        previous: str | None = None,
        variante: str | None = None,
    ) -> Fortschritt:
        """Fetches the pinned build — or, given ``build``, that one in place
        of whatever is installed.

        Without ``build`` or ``variante`` this is the first fetch of a
        machine that has no server of its own, and one that has is left
        alone. With ``build``, the named build replaces the installed one: a
        newer build for an update, the pinned one to come back from it. With
        ``variante`` alone, the installed build comes again in that variant —
        a switch of backend, not of build. Either way the new build lands in
        its own folder, and the others are only removed once the fetch has
        succeeded — a failed one leaves the working server exactly as it
        was.

        ``previous`` is the build that ran until now, for the one line the
        log gets about the change.
        """
        wanted = variante or VORGABE_VARIANTE
        with self._schloss:
            if self.laeuft():
                raise ServerdownloadFehler("laeuft_schon")
            own = _own_build(self._ordner.parent)
            installed = own[0] if own else None
            if installed is not None and build is None and variante is None:
                raise ServerdownloadFehler("schon_da")
            # A switch of variant keeps the build that runs: the pinned one
            # would not outrank a newer one that was fetched, and the switch
            # would not take.
            target = build or installed or BUILD
            if own is not None and (target, wanted) == (own[0], own[1]):
                raise ServerdownloadFehler("schon_da")
            name = paketname(target) if wanted == VORGABE_VARIANTE else paketname(target, wanted)
            if name is None:
                raise ServerdownloadFehler("kein_paket")

            self._stand = Fortschritt(geladen=0, gesamt=0)
            threading.Thread(
                target=self._holen,
                args=(target, name, previous or installed, wanted),
                daemon=True,
            ).start()
            return self._stand

    def _holen(
        self, build: str, name: str, previous: str | None, variante: str = VORGABE_VARIANTE
    ) -> None:
        archiv = self._ordner / (name + UNFERTIG)
        folder = self._ordner / bauordner_name(build, variante)
        hidden = folder.resolve()
        # CUDA brings its runtime in a second archive, unpacked beside it.
        cudart = _CUDART[0] if variante == "cuda12" else None
        cudart_archiv = self._ordner / (cudart + UNFERTIG) if cudart else None

        with _unpacking_lock:
            _unpacking.add(hidden)
        try:
            # Inside the guard: a folder that cannot be made would end this
            # thread before the state could say so, and the bar would stand
            # at nought for good.
            self._ordner.mkdir(parents=True, exist_ok=True)
            if cudart and self._stand:
                # Fixed upfront from both archives, not measured from the
                # first one while it comes down: the bar would reach its end
                # and fall back once the second archive adds its size.
                self._stand.gesamt = _groesse(f"{_basis(build)}/{name}") + _groesse(
                    f"{_basis(build)}/{cudart}"
                )
            self._laden(build, name, archiv, fest=cudart is not None)
            self._entpacken(archiv, name, folder)
            archiv.unlink(missing_ok=True)
            if cudart and cudart_archiv is not None:
                self._laden(build, cudart, cudart_archiv, fest=True)
                self._entpacken(cudart_archiv, cudart, folder)
                cudart_archiv.unlink(missing_ok=True)

            hits = sorted(folder.rglob(_server_name()))
            if not hits:
                raise ServerdownloadFehler("fehlgeschlagen")
            if sys.platform != "win32":
                hits[0].chmod(hits[0].stat().st_mode | 0o111)
        except Exception as fehler:  # noqa: BLE001 - the reason belongs in the state
            archiv.unlink(missing_ok=True)
            if cudart_archiv is not None:
                cudart_archiv.unlink(missing_ok=True)
            shutil.rmtree(folder, ignore_errors=True)
            if self._stand:
                self._stand.fehler = (
                    fehler.grund
                    if isinstance(fehler, ServerdownloadFehler)
                    else "fehlgeschlagen"
                )
            return
        finally:
            # Whole or gone: either way the folder is no longer half-written.
            with _unpacking_lock:
                _unpacking.discard(hidden)

        if not self._install(folder):
            log.warning(
                "Model server program: build %s (%s) did not start the servers, build %s stays",
                build, variante, previous or "none",
            )
            if self._stand:
                self._stand.fehler = "fehlgeschlagen"
            return
        log.info(
            "Model server program: build %s replaced by build %s (%s)",
            previous or "none", build, variante,
        )
        if self._stand:
            self._stand.fertig = True

    def _install(self, folder: Path) -> bool:
        """Makes the unpacked build the one that starts and starts the servers
        that ran on it. The builds that ran until now are kept — with their
        server put aside by name, so that the new build is the one found — and
        go only once every server has loaded its model. When a server does
        not start, the new build goes instead, the old one is the program
        again and the servers start on it.
        """
        restart = self._restart
        if restart is None:
            self._remove_other_builds(folder.name)
            return True
        parked: list[tuple[Path, Path]] = []
        try:
            try:
                restart.stop()
                self._park_other_builds(folder.name, parked)
                started = restart.start()
            except Exception:  # noqa: BLE001 - the way back is the same for every reason
                log.warning("Model server program: the new build could not be put in place", exc_info=True)
                started = False
            if started:
                self._remove_other_builds(folder.name)
                return True
            try:
                restart.stop()
                shutil.rmtree(folder, ignore_errors=True)
                for before, after in parked:
                    atomic_file.rename_onto(after, before)
                restart.start()
            except Exception:  # noqa: BLE001 - nothing is left to fall back on, the log says so
                log.warning("Model server program: the old build could not be put back", exc_info=True)
            return False
        finally:
            restart.forget()

    def _park_other_builds(self, current: str, parked: list[tuple[Path, Path]]) -> None:
        """Puts the server of every other build aside by name, so that the
        highest build that holds a server is ``current`` whatever its number.
        The folders stay. Each rename is added to ``parked`` as (name, name
        aside) the moment it is made, so a failure half way leaves the list
        of what to put back."""
        for entry in self._ordner.iterdir():
            if entry.name == current or _bauordner_teile(entry.name) is None or not entry.is_dir():
                continue
            for server in sorted(entry.rglob(_server_name())):
                aside = server.with_name(server.name + ".old")
                atomic_file.rename_onto(server, aside)
                parked.append((server, aside))

    def _laden(self, build: str, name: str, ziel: Path, fest: bool = False) -> None:
        """One archive, streamed to disk. Called once for the package and,
        for CUDA, a second time for its runtime — both add to the same
        ``Fortschritt``, so ``geladen`` runs through both and never resets.

        ``fest`` means the caller fixed ``gesamt`` upfront: this call must
        not measure it again from the response, or the bytes count twice.
        """
        with httpx.stream(
            "GET", f"{_basis(build)}/{name}", follow_redirects=True, timeout=60
        ) as antwort:
            antwort.raise_for_status()
            if self._stand and not fest:
                self._stand.gesamt = int(antwort.headers.get("content-length") or 0)
            with ziel.open("wb") as schreiben:
                for brocken in antwort.iter_bytes(BROCKEN):
                    schreiben.write(brocken)
                    if self._stand:
                        self._stand.geladen += len(brocken)

    def _entpacken(self, archiv: Path, name: str, folder: Path) -> None:
        """Into a folder named after the build, so an update never mixes."""
        folder.mkdir(parents=True, exist_ok=True)
        if name.endswith(".zip"):
            with zipfile.ZipFile(archiv) as zf:
                zf.extractall(folder)
        else:
            with tarfile.open(archiv, "r:gz") as tf:
                tf.extractall(folder, filter="data")

    def _remove_other_builds(self, current: str) -> None:
        """Every other build folder goes — another build, and another
        variant of the same one alike: one build stays on disk, the one just
        fetched. Only folders named like a build folder qualify — whatever
        else lies in the folder is not this program's to remove.

        A folder that cannot be removed right now stays and is not in the
        way: a server still running from it keeps its files open, and on
        Windows those cannot be deleted. An older build is never picked
        beside a newer one anyway. A newer one would be, so a server left
        in such a folder is moved aside by name — the running process keeps
        going, and the next start finds the build that was just fetched.
        """
        try:
            entries = list(self._ordner.iterdir())
        except OSError:
            return
        for entry in entries:
            if entry.name == current or _bauordner_teile(entry.name) is None or not entry.is_dir():
                continue
            shutil.rmtree(entry, ignore_errors=True)
            try:
                left = sorted(entry.rglob(_server_name()))
            except OSError:
                continue
            for server in left:
                try:
                    server.rename(server.with_name(server.name + ".old"))
                except OSError:
                    pass
