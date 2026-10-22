"""Snapshots of a working folder, kept apart from the folder itself.

Before the model changes files in a shared folder, one snapshot of the whole
folder is put away — at most one per folder and per turn. The snapshots live
in a bare git repository inside the program's data folder, never in the
person's folder and never in a repository the person owns. The repository is
written and read with dulwich, a git in plain Python that ships with the
program: the git of the computer is never called, and the computer needs none.

Left out of every snapshot: a file over 10 MB, a nested git repository, a
link, and what the folder's own ``.gitignore`` names. A folder with more than
50 000 files gets no snapshot at all. The filesystem root and the home folder
are never snapshotted.

Next to the snapshots the program keeps an index per folder: the size and
the times of every file as they were when its content was last read into a
snapshot, with the id of that content. A snapshot, the list and a restore
read only the files whose size or times changed since — what the
index says of the rest is taken as it stands, as git does with its own. An
index that is missing or cannot be read is built anew, and the next call
reads everything once.

Next to the snapshots the program keeps a ledger: the checksum of every file
the model wrote. Restoring then puts back only what is still the model's own
text and leaves a file the person changed by hand afterwards alone.

Everything here is synchronous and takes a lock; a caller on the event loop
runs it in a thread.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import stat
import threading
import time
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from types import MappingProxyType
from typing import Any, NamedTuple

from dulwich.diff_tree import tree_changes
from dulwich.ignore import IgnoreFilterManager
from dulwich.index import commit_tree
from dulwich.object_store import iter_tree_contents
from dulwich.objects import Blob, Commit, ObjectID
from dulwich.refs import Ref
from dulwich.repo import Repo

from app import atomic_file

log = logging.getLogger(__name__)

# Bigger files stay out of every snapshot.
MAX_FILE_BYTES = 10 * 1024 * 1024
# A folder with more files than this gets no snapshot.
MAX_FILES = 50_000

_STORE = "store"
_LEDGERS = "ledgers"
_INDEXES = "indexes"
_PROJECTS = "projects"
_REF_PREFIX = "refs/snapshots"
_ID = re.compile(r"^[0-9a-f]{40}$")
_AUTHOR = b"Exe AI <snapshots@localhost>"
_PLAIN, _EXECUTABLE = 0o100644, 0o100755

# One lock for the whole store: a snapshot and a restore of the same folder
# must not run at the same time.
_lock = threading.Lock()
# folder -> the turn that last took a snapshot of it: "once per folder and
# turn" needs nothing more than this.
_last_turn: dict[str, str] = {}


class CheckpointError(Exception):
    """A request the store cannot serve. ``kind`` names why, for the caller
    to put in its own words: ``unknown_folder``, ``unknown_snapshot``,
    ``bad_file``, ``too_many`` or ``failed``."""

    def __init__(self, kind: str) -> None:
        super().__init__(kind)
        self.kind = kind


class _Project(NamedTuple):
    base: Path
    directory: Path
    key: str

    @property
    def store(self) -> Path:
        return self.base / _STORE

    @property
    def ledger(self) -> Path:
        return self.base / _LEDGERS / f"{self.key}.json"

    @property
    def index_file(self) -> Path:
        return self.base / _INDEXES / f"{self.key}.json"

    @property
    def meta(self) -> Path:
        return self.base / _PROJECTS / f"{self.key}.json"

    @property
    def ref(self) -> Ref:
        return Ref(f"{_REF_PREFIX}/{self.key}".encode())


def _project(base: Path, directory: Path | str) -> _Project:
    resolved = Path(directory).expanduser().resolve()
    key = hashlib.sha256(str(resolved).encode()).hexdigest()[:16]
    return _Project(Path(base), resolved, key)


def known(base: Path, directory: Path | str) -> bool:
    """Whether a snapshot of that folder was ever taken."""
    return _project(base, directory).meta.is_file()


@contextmanager
def _repo(project: _Project, *, create: bool = False) -> Iterator[Repo]:
    if create and not (project.store / "HEAD").exists():
        project.store.mkdir(parents=True, exist_ok=True)
        Repo.init_bare(str(project.store))
    repo = Repo(str(project.store))
    try:
        yield repo
    finally:
        repo.close()


def _tip(repo: Repo, project: _Project) -> ObjectID | None:
    try:
        return repo.refs[project.ref]
    except KeyError:
        return None


def _commit(repo: Repo, sha: ObjectID) -> Commit:
    found = repo[sha]
    if not isinstance(found, Commit):
        raise CheckpointError("failed")
    return found


def _chain(repo: Repo, tip: ObjectID | None) -> list[Commit]:
    """The snapshots of a folder, newest first."""
    chain: list[Commit] = []
    while tip is not None:
        commit = _commit(repo, tip)
        chain.append(commit)
        tip = commit.parents[0] if commit.parents else None
    return chain


# --- The folder, read ------------------------------------------------------------------------------


def _scan(directory: Path) -> tuple[bool, list[str]]:
    """The files a snapshot takes of the folder, as paths inside it: whether
    there are more files than a snapshot takes, and the paths. What the
    folder's own ignore rules name, a nested git repository, a link and a
    file over the size limit are not among them."""
    if not directory.is_dir():
        return False, []
    ignored = IgnoreFilterManager(str(directory), [], False)
    counted = 0
    files: list[str] = []
    for current, dirs, names in os.walk(directory):
        here = Path(current)
        prefix = "" if here == directory else here.relative_to(directory).as_posix() + "/"
        kept = []
        for name in sorted(dirs):
            child = here / name
            if name == ".git" or child.is_symlink() or (child / ".git").exists():
                continue
            if ignored.is_ignored(f"{prefix}{name}/") and ignored.may_prune_directory(f"{prefix}{name}/"):
                continue
            kept.append(name)
        dirs[:] = kept
        for name in sorted(names):
            relative = prefix + name
            try:
                info = (here / name).lstat()
            except OSError:
                continue
            if name == ".git" or not stat.S_ISREG(info.st_mode) or ignored.is_ignored(relative):
                continue
            counted += 1
            if counted > MAX_FILES:
                return True, files
            if info.st_size <= MAX_FILE_BYTES:
                files.append(relative)
    return False, files


class _Seen(NamedTuple):
    """What the index holds of a file: its size, modification time and
    change time when its content was read, the id of that content and its
    mode. The change time moves with every write, chmod and replacement,
    also where a tool puts the old modification time back."""

    size: int
    mtime: int
    ctime: int
    id: ObjectID
    mode: int


class _Index(NamedTuple):
    """The index of a folder: when the pass that wrote it began, and its files."""

    taken: int
    files: Mapping[str, _Seen]


_NO_INDEX = _Index(0, MappingProxyType({}))


def _read_index(project: _Project) -> _Index:
    """The index of the folder; an empty one where it is missing or cannot be read."""
    try:
        held = json.loads(project.index_file.read_text(encoding="utf-8"))
        files = {
            name: _Seen(int(size), int(mtime), int(ctime), _object_id(sha), int(mode))
            for name, (size, mtime, ctime, sha, mode) in held["files"].items()
        }
        return _Index(int(held["taken"]), files)
    except Exception:  # noqa: BLE001 - whatever is wrong with the cache, it is built anew
        return _NO_INDEX


def _object_id(value: object) -> ObjectID:
    if not isinstance(value, str) or not _ID.match(value):
        raise ValueError("not an object id")
    return ObjectID(value.encode())


def _write_index(project: _Project, index: _Index) -> None:
    """Stores the index. It only saves reading, so a folder that cannot take
    it costs time at the next pass and nothing else."""
    held = {
        "taken": index.taken,
        "files": {
            name: [seen.size, seen.mtime, seen.ctime, seen.id.decode(), seen.mode] for name, seen in index.files.items()
        },
    }
    try:
        project.index_file.parent.mkdir(parents=True, exist_ok=True)
        atomic_file.write(project.index_file, json.dumps(held))
    except OSError:
        log.warning("Index of %s could not be written", project.directory, exc_info=True)


def _mode(info: os.stat_result) -> int:
    return _EXECUTABLE if os.name != "nt" and info.st_mode & 0o111 else _PLAIN


def _unchanged(seen: _Seen, info: os.stat_result, taken: int) -> bool:
    """Whether the index still describes the file. A file whose time lies in
    the same second as the pass that wrote the index, or later, may have
    changed again within the clock's grain without the time showing it: it
    is read once more, as git reads such a file."""
    return (
        seen.size == info.st_size
        and seen.mtime == info.st_mtime_ns
        and seen.ctime == info.st_ctime_ns
        and seen.mode == _mode(info)
        and info.st_mtime_ns // 1_000_000_000 < taken // 1_000_000_000
    )


def _entries(
    directory: Path, files: list[str], index: _Index = _NO_INDEX, store: Any = None
) -> tuple[dict[str, tuple[ObjectID, int]], dict[str, _Seen]]:
    """Each file with the id of its content and its mode, and what the index
    would hold of it. A file the index still describes is not read. With a
    ``store`` the content is put into it too, unless it is there already."""
    entries: dict[str, tuple[ObjectID, int]] = {}
    seen: dict[str, _Seen] = {}
    for relative in files:
        path = directory / relative
        try:
            info = path.stat()
            held = index.files.get(relative)
            if held is not None and _unchanged(held, info, index.taken):
                entries[relative] = (held.id, held.mode)
                seen[relative] = held
                continue
            blob = Blob.from_string(path.read_bytes())
        except OSError:
            continue
        if store is not None and blob.id not in store:
            store.add_object(blob)
        mode = _mode(info)
        entries[relative] = (blob.id, mode)
        seen[relative] = _Seen(info.st_size, info.st_mtime_ns, info.st_ctime_ns, blob.id, mode)
    return entries, seen


def _flat(repo: Repo, tree: ObjectID) -> dict[str, tuple[ObjectID, int]]:
    """The files of a snapshot with the id of their content and their mode."""
    return {
        entry.path.decode("utf-8", "surrogateescape"): (entry.sha, entry.mode)
        for entry in iter_tree_contents(repo.object_store, tree)
        if entry.path is not None and entry.sha is not None and entry.mode is not None
    }


def _changed(project: _Project, repo: Repo, tree: ObjectID) -> list[str]:
    """The files that differ between a snapshot and the folder as it is now."""
    too_many, files = _scan(project.directory)
    if too_many:
        raise CheckpointError("too_many")
    # Read only: what is read afresh here is not in the store, so the index
    # is left as it is for the next snapshot to write.
    now, _ = _entries(project.directory, files, _read_index(project))
    then = _flat(repo, tree)
    names = {name for name in now.keys() | then.keys() if _id(now.get(name)) != _id(then.get(name))}
    return sorted(names)


def _id(entry: tuple[ObjectID, int] | None) -> ObjectID | None:
    return entry[0] if entry is not None else None


# --- Taking a snapshot ---------------------------------------------------------------------------


def snapshot(base: Path, directory: Path | str, turn: str, reason: str) -> bool:
    """Puts away one snapshot of the folder unless this turn already did.
    Returns whether a new one was taken; never raises."""
    try:
        with _lock:
            return _snapshot(_project(base, directory), turn, reason)
    except Exception:  # noqa: BLE001 - a snapshot must never stop the tool it precedes
        log.warning("Snapshot of %s failed", directory, exc_info=True)
        return False


def _snapshot(project: _Project, turn: str, reason: str) -> bool:
    directory = project.directory
    if directory == Path(directory.anchor) or directory == Path.home().resolve():
        return False
    if not directory.is_dir() or _last_turn.get(str(directory)) == turn:
        return False
    taken = _take(project, reason)
    # Noted only once the attempt ran through: a call that failed on the way
    # is tried again by the next call of the same turn.
    _last_turn[str(directory)] = turn
    return taken


def _take(project: _Project, reason: str, *, strict: bool = False) -> bool:
    """Puts one snapshot away now. False when the folder holds too many
    files or nothing changed since the last snapshot; ``strict`` raises
    for the first instead."""
    began = time.time_ns()
    too_many, files = _scan(project.directory)
    if too_many:
        if strict:
            raise CheckpointError("too_many")
        return False
    with _repo(project, create=True) as repo:
        _remember(project)
        tip = _tip(repo, project)
        # An index counts only where snapshots exist that hold its contents.
        index = _read_index(project) if tip is not None else _NO_INDEX
        entries, seen = _entries(project.directory, files, index, repo.object_store)
        _write_index(project, _Index(began, seen))
        # A first snapshot of an empty folder is still taken: it is what a
        # file the model makes there goes back to.
        tree = commit_tree(
            repo.object_store,
            [(name.encode("utf-8", "surrogateescape"), sha, mode) for name, (sha, mode) in entries.items()],
        )
        if tip is not None and _commit(repo, tip).tree == tree:
            return False
        commit = Commit()
        commit.tree = tree
        commit.parents = [tip] if tip is not None else []
        commit.author = commit.committer = _AUTHOR
        commit.author_time = commit.commit_time = int(time.time())
        commit.author_timezone = commit.commit_timezone = 0
        commit.encoding = b"UTF-8"
        commit.message = (" ".join(reason.split())[:200] or "snapshot").encode("utf-8", "replace")
        repo.object_store.add_object(commit)
        if tip is None:
            repo.refs.add_if_new(project.ref, commit.id)
        else:
            repo.refs.set_if_equals(project.ref, tip, commit.id)
        return True


def _remember(project: _Project) -> None:
    project.meta.parent.mkdir(parents=True, exist_ok=True)
    project.meta.write_text(json.dumps({"directory": str(project.directory)}), encoding="utf-8")


# --- The ledger of what the model wrote ----------------------------------------------------------


def _file_hash(path: Path) -> str | None:
    try:
        with open(path, "rb") as handle:
            return hashlib.file_digest(handle, "sha256").hexdigest()
    except OSError:
        return None


def _read_ledger(project: _Project) -> dict[str, str]:
    try:
        held = json.loads(project.ledger.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return held if isinstance(held, dict) else {}


def _write_ledger(project: _Project, ledger: dict[str, str]) -> None:
    project.ledger.parent.mkdir(parents=True, exist_ok=True)
    atomic_file.write(project.ledger, json.dumps(ledger))


def record_write(base: Path, directory: Path | str, file: Path | str) -> None:
    """Notes the checksum of a file the model has just written; never raises."""
    try:
        project = _project(base, directory)
        path = Path(file).resolve()
        digest = _file_hash(path)
        if digest is None:
            return
        with _lock:
            ledger = _read_ledger(project)
            ledger[str(path)] = digest
            _write_ledger(project, ledger)
    except Exception:  # noqa: BLE001 - a missing ledger line only makes a restore more careful
        log.warning("Ledger entry for %s failed", file, exc_info=True)


def record_changes(base: Path, directory: Path | str) -> None:
    """Notes every file that now differs from the newest snapshot as the
    model's — a file removed counts, with an empty checksum. For a command,
    which says nothing about the files it touched; never raises."""
    try:
        project = _project(base, directory)
        if not known(base, directory):
            return
        with _lock, _repo(project) as repo:
            tip = _tip(repo, project)
            if tip is None:
                return
            changed = _changed(project, repo, _commit(repo, tip).tree)
            ledger = _read_ledger(project)
            for name in changed:
                path = project.directory / name
                ledger[str(path)] = _file_hash(path) or ""
            _write_ledger(project, ledger)
    except Exception:  # noqa: BLE001 - a missing ledger line only makes a restore more careful
        log.warning("Ledger entries for %s failed", directory, exc_info=True)


# --- Reading the snapshots -----------------------------------------------------------------------


def snapshots(base: Path, directory: Path | str) -> list[dict[str, Any]]:
    """The snapshots of a folder, newest first and numbered from 1. Each
    carries the files that changed after it — against the next newer
    snapshot, and for the newest against the folder as it is now."""
    project = _project(base, directory)
    if not known(base, directory):
        return []
    try:
        with _lock, _repo(project) as repo:
            chain = _chain(repo, _tip(repo, project))
            result: list[dict[str, Any]] = []
            for number, commit in enumerate(chain, start=1):
                if number == 1:
                    try:
                        files = _changed(project, repo, commit.tree)
                    except CheckpointError as error:
                        # The folder outgrew the limit: its snapshots are
                        # still listed, so one file can still be named.
                        if error.kind != "too_many":
                            raise
                        files = []
                else:
                    files = _between(repo, commit.tree, chain[number - 2].tree)
                result.append(
                    {
                        "nr": number,
                        "id": commit.id.decode(),
                        "time": datetime.fromtimestamp(commit.commit_time, tz=timezone.utc).isoformat(),
                        "reason": commit.message.decode("utf-8", "replace").strip(),
                        "files": files,
                    }
                )
            return result
    except CheckpointError:
        raise
    except Exception:  # noqa: BLE001 - whatever went wrong is told as one thing
        log.warning("Listing the snapshots of %s failed", directory, exc_info=True)
        raise CheckpointError("failed") from None


def _between(repo: Repo, older: ObjectID, newer: ObjectID) -> list[str]:
    """The files that differ between two snapshots."""
    names: set[str] = set()
    for change in tree_changes(repo.object_store, older, newer):
        entry = change.new if change.new is not None and change.new.path is not None else change.old
        if entry is not None and entry.path is not None:
            names.add(entry.path.decode("utf-8", "surrogateescape"))
    return sorted(names)


# --- Restoring -------------------------------------------------------------------------------


def restore(
    base: Path, directory: Path | str, snapshot_id: str, *, file: str | None = None, everything: bool = False
) -> dict[str, list[str]]:
    """Puts files back to how a snapshot had them.

    By default only files that are still the model's own text — or that were
    removed since — are put back, and a file the model made after the snapshot
    is removed; a file changed by hand after the model wrote it is left alone
    and named under ``skipped``. ``everything`` puts back every file the
    snapshot has and that differs, and touches no other; ``file`` does that
    for one file, and removes it if the snapshot never had it. A file the
    ledger does not know is never the model's as far as the default goes.
    """
    project = _project(base, directory)
    if not known(base, directory):
        raise CheckpointError("unknown_folder")
    if not _ID.match(snapshot_id):
        raise CheckpointError("unknown_snapshot")
    target = _checked_file(project, file) if file else None
    wanted_id = ObjectID(snapshot_id.encode())
    try:
        with _lock:
            with _repo(project) as repo:
                if wanted_id not in {commit.id for commit in _chain(repo, _tip(repo, project))}:
                    raise CheckpointError("unknown_snapshot")
            # A folder that was deleted is what a restore is for.
            project.directory.mkdir(parents=True, exist_ok=True)
            # What a restore removes or overwrites has to be recoverable too.
            _take(project, "before restore", strict=True)
            with _repo(project) as repo:
                tree = _commit(repo, wanted_id).tree
                in_snapshot = _flat(repo, tree)
                skipped: list[str] = []
                if target is not None and target in in_snapshot:
                    # The snapshot holds it: nothing to scan for.
                    wanted, keep_new = [target], False
                else:
                    changed = _changed(project, repo, tree)
                    if target is not None:
                        # Only a file a snapshot could have held: one the
                        # folder ignores, or that lies outside every
                        # snapshot, is not this restore's to remove.
                        wanted, skipped, keep_new = ([target], [], False) if target in changed else ([], [target], False)
                    elif everything:
                        wanted, keep_new = changed, True
                    else:
                        wanted, skipped = _own_files(_read_ledger(project), project, changed)
                        keep_new = False
                done = _apply(project, repo, in_snapshot, wanted, skipped, keep_new)
            _note_restored(project, done["restored"])
            return done
    except CheckpointError:
        raise
    except Exception:  # noqa: BLE001 - whatever went wrong is told as one thing
        log.warning("Restoring %s from %s failed", directory, snapshot_id, exc_info=True)
        raise CheckpointError("failed") from None


def _note_restored(project: _Project, names: list[str]) -> None:
    """A file a restore wrote or removed is as the restore left it: the
    ledger takes that over, so a later restore to an older snapshot still
    counts it as the model's and not as a change by hand."""
    if not names:
        return
    ledger = _read_ledger(project)
    for name in names:
        path = project.directory / name
        ledger[str(path)] = _file_hash(path) or ""
    _write_ledger(project, ledger)


def _checked_file(project: _Project, name: str) -> str:
    """The file as a path inside the folder, written the way git writes it."""
    candidate = Path(name)
    if not name.strip() or candidate.is_absolute():
        raise CheckpointError("bad_file")
    try:
        # Written out, not resolved: a file that became a link is still the
        # file that was named.
        relative = Path(os.path.normpath(project.directory / candidate)).relative_to(project.directory)
    except ValueError:
        raise CheckpointError("bad_file") from None
    if not relative.parts:
        raise CheckpointError("bad_file")
    return relative.as_posix()


def _own_files(
    ledger: dict[str, str], project: _Project, changed: list[str]
) -> tuple[list[str], list[str]]:
    """Splits the changed files into those still as the model left them
    (or removed since) and those changed by hand."""
    own: list[str] = []
    hand: list[str] = []
    for name in changed:
        path = project.directory / name
        recorded = ledger.get(str(path))
        if recorded is not None and _file_hash(path) in (None, recorded):
            own.append(name)
        else:
            hand.append(name)
    return own, hand


def _inside(directory: Path, path: Path) -> bool:
    """Whether the file lies in the folder once the links on the way to it
    are followed: a link to elsewhere must not carry a write out of it."""
    try:
        path.parent.resolve().relative_to(directory)
    except (ValueError, OSError):
        return False
    return True


def _blob(repo: Repo, sha: ObjectID) -> bytes:
    found = repo.object_store[sha]
    if not isinstance(found, Blob):
        raise OSError("not a file")
    return found.data


def _too_big(path: Path) -> bool:
    try:
        return path.lstat().st_size > MAX_FILE_BYTES
    except OSError:
        return False


def _apply(
    project: _Project, repo: Repo, in_snapshot: dict[str, tuple[ObjectID, int]], wanted: list[str],
    skipped: list[str], keep_new: bool,
) -> dict[str, list[str]]:
    restored: list[str] = []
    failed: list[str] = []
    for name in wanted:
        path = project.directory / name
        held = in_snapshot.get(name)
        if not _inside(project.directory, path):
            failed.append(name)
            continue
        if held is not None:
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                if path.is_symlink():
                    # The link is replaced by the file, never followed.
                    path.unlink()
                atomic_file.write(path, _blob(repo, held[0]))
                if os.name != "nt" and held[1] & 0o111:
                    path.chmod(path.stat().st_mode | 0o111)
                restored.append(name)
            except OSError:
                log.warning("Could not put back %s", path, exc_info=True)
                failed.append(name)
        elif keep_new:
            # Not in the snapshot, and nothing says the model made it: it
            # may be the person's own new file.
            continue
        elif path.is_file() or path.is_symlink():
            # Not in the snapshot: the model made it afterwards. A file too
            # big for any snapshot is kept — no copy of it exists to go back to.
            if _too_big(path):
                skipped.append(name)
                continue
            try:
                path.unlink()
                restored.append(name)
            except OSError:
                failed.append(name)
    return {"restored": sorted(restored), "skipped": sorted(skipped), "failed": sorted(failed)}


def forget_turns() -> None:
    """Lets the next call of every folder take its snapshot again. For
    tests, which run many turns in one process."""
    _last_turn.clear()
