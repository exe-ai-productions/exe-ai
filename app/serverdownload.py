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

Every build lies in a folder named after its tag. The one that runs is the
one with the highest build number, and a fetch that succeeded removes the
others — so the folder on disk is the whole answer to "which build is
this", and nothing has to be remembered beside it.

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

import httpx

from app.no_console import no_window

log = logging.getLogger(__name__)

# The pinned llama.cpp build and the packages per system. CPU builds on
# purpose where a GPU flavour would gamble on drivers: they run everywhere,
# and macOS carries its Metal support inside the plain package.
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
    ("win32", "amd64"): "llama-{build}-bin-win-cpu-x64.zip",
    ("win32", "arm64"): "llama-{build}-bin-win-cpu-arm64.zip",
    ("linux", "x86_64"): "llama-{build}-bin-ubuntu-x64.tar.gz",
    ("linux", "aarch64"): "llama-{build}-bin-ubuntu-arm64.tar.gz",
}

BROCKEN = 1024 * 1024
UNFERTIG = ".teil"

# Where it lands, and where the runner looks.
ORDNER = "llama.cpp"

# A build tag is the letter b and the build number, nothing else.
_BUILD_TAG = re.compile(r"b(\d+)")

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


def paketname(build: str = BUILD) -> str | None:
    """The package of ``build`` for this machine, or nothing when llama.cpp
    has none."""
    maschine = platform.machine().lower()
    if maschine == "x64":
        maschine = "amd64" if sys.platform == "win32" else "x86_64"
    schluessel = (
        "win32" if sys.platform == "win32" else "darwin" if sys.platform == "darwin" else "linux"
    )
    form = _PAKETE.get((schluessel, maschine))
    return form.format(build=build) if form else None


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


def _own_build(data_folder: Path) -> tuple[str, Path] | None:
    """The fetched build that runs, as its tag and its server: of the build
    folders below the data folder, the one with the highest build number
    that holds a server.

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
    candidates = sorted(
        (
            (number, entry)
            for entry in entries
            if (number := build_number(entry.name)) is not None and number >= floor
        ),
        key=lambda pair: pair[0],
        reverse=True,
    )
    name = _server_name()
    for _, entry in candidates:
        if _is_unpacking(entry):
            continue
        try:
            hits = sorted(entry.rglob(name))
        except OSError:
            # A fetch removes the other builds from its own thread, so a
            # folder can vanish while it is being read.
            continue
        if hits:
            return entry.name, hits[0]
    return None


def gefundener_server(ordner: Path) -> Path | None:
    """The unpacked llama-server below the data folder, or nothing — of
    several fetched builds, the one with the highest build number."""
    own = _own_build(ordner)
    return own[1] if own else None


def installed_build(data_folder: Path) -> str | None:
    """The tag of the fetched build that runs, or nothing."""
    own = _own_build(data_folder)
    return own[0] if own else None


def fetched_build(program: Path, data_folder: Path) -> str | None:
    """The tag of the build folder ``program`` lies in — or nothing when
    it is not a build this program fetched."""
    root = Path(data_folder).expanduser() / ORDNER
    try:
        inside = Path(program).resolve().relative_to(root.resolve())
    except (OSError, ValueError):
        return None
    if inside.parts and build_number(inside.parts[0]) is not None:
        return inside.parts[0]
    return None


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


class Serverdownload:
    """One fetch of the model server, watchable while it runs."""

    def __init__(self, ordner: Path) -> None:
        self._ordner = Path(ordner).expanduser() / ORDNER
        self._stand: Fortschritt | None = None
        self._schloss = threading.Lock()

    def stand(self) -> Fortschritt | None:
        return self._stand

    def laeuft(self) -> bool:
        return self._stand is not None and not self._stand.fertig and not self._stand.fehler

    def starten(self, build: str | None = None, previous: str | None = None) -> Fortschritt:
        """Fetches the pinned build — or, given ``build``, that one in place
        of whatever is installed.

        Without ``build`` this is the first fetch of a machine that has no
        server of its own, and one that has is left alone. With it, the
        named build replaces the installed one: a newer build for an update,
        the pinned one to come back from it. Either way the new build lands
        in its own folder, and the others are only removed once the fetch
        has succeeded — a failed one leaves the working server exactly as it
        was.

        ``previous`` is the build that ran until now, for the one line the
        log gets about the change.
        """
        with self._schloss:
            if self.laeuft():
                raise ServerdownloadFehler("laeuft_schon")
            installed = installed_build(self._ordner.parent)
            if installed is not None and (build is None or build == installed):
                raise ServerdownloadFehler("schon_da")
            target = build or BUILD
            name = paketname(target)
            if name is None:
                raise ServerdownloadFehler("kein_paket")

            self._stand = Fortschritt(geladen=0, gesamt=0)
            threading.Thread(
                target=self._holen, args=(target, name, previous or installed), daemon=True
            ).start()
            return self._stand

    def _holen(self, build: str, name: str, previous: str | None) -> None:
        archiv = self._ordner / (name + UNFERTIG)
        folder = self._ordner / build
        hidden = folder.resolve()

        with _unpacking_lock:
            _unpacking.add(hidden)
        try:
            # Inside the guard: a folder that cannot be made would end this
            # thread before the state could say so, and the bar would stand
            # at nought for good.
            self._ordner.mkdir(parents=True, exist_ok=True)
            with httpx.stream(
                "GET", f"{_basis(build)}/{name}", follow_redirects=True, timeout=60
            ) as antwort:
                antwort.raise_for_status()
                if self._stand:
                    self._stand.gesamt = int(antwort.headers.get("content-length") or 0)
                with archiv.open("wb") as schreiben:
                    for brocken in antwort.iter_bytes(BROCKEN):
                        schreiben.write(brocken)
                        if self._stand:
                            self._stand.geladen += len(brocken)

            self._entpacken(archiv, name, folder)
            archiv.unlink(missing_ok=True)

            hits = sorted(folder.rglob(_server_name()))
            if not hits:
                raise ServerdownloadFehler("fehlgeschlagen")
            if sys.platform != "win32":
                hits[0].chmod(hits[0].stat().st_mode | 0o111)
        except Exception as fehler:  # noqa: BLE001 - the reason belongs in the state
            archiv.unlink(missing_ok=True)
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

        self._remove_other_builds(build)
        log.info("Model server program: build %s replaced by build %s", previous or "none", build)
        if self._stand:
            self._stand.fertig = True

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
        """Every other build folder goes: one build stays on disk, the one
        just fetched. Only folders named like a build tag qualify — whatever
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
            if entry.name == current or build_number(entry.name) is None or not entry.is_dir():
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
