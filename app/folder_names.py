"""Carrying the program's folders over from their former German names.

The program used to create folders a user reads in their own file manager as
``bilder``, ``modelle``, ``chatdateien`` and so on. They are English now, and
the key of each named location (app/speicherorte.py) is its folder name. What
an installation built under the former names is carried over at start, before
anything asks for a location — the construction the agent dock already used
for its record (app/agentendock.py, ``_altbestand_uebernehmen``):

* the former default folder is renamed while the location sits on its
  default: its config field empty (the folder under the data folder named
  after its former key), or naming the former or the new default folder —
  under the data folder, or where the shipped ``./data/…`` value put it. A
  location the user pointed at a folder of their own keeps that folder and
  its line;
* a line in config.yaml that names the former default folder is the shipped
  default, not a choice: that line gets the new name, and the rest of the
  file stays as it was (app/configwanderung.py). Only a line the file is
  known to take has its folder renamed, and a folder whose line then could
  not be written goes back, so the two never name different places;
* an override stored under a former key is kept under the new key; its path
  is the user's and is not changed;
* the companion folders inside the image models folder are renamed in the
  image models folder in force, wherever it lies — the program looks for
  them there by name, so under the former name they would simply be gone;
* stored paths below a renamed folder — uploads, and folders shared with a
  chat or a project — follow it (app/db/repositories/documents.py,
  app/db/repositories/chats.py). Every rename is noted in a small file in
  the data folder first, and the note goes once the paths have followed:
  a start that ends in between leaves the note for the next one.

A folder is renamed only while nothing stands under the new name but an
empty folder, and while nothing the user set names it or a folder inside it:
nothing is ever overwritten or merged. A step that cannot be done is logged
and tried again at the next start; none of them keeps the program from
starting.
"""

from __future__ import annotations

import functools
import json
import logging
import os
import time
import unicodedata
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import yaml

from app import atomic_file
from app import configwanderung, dokumentablage, instanzschloss, speicherorte
from app.paketierung import aufloesen

if TYPE_CHECKING:
    from app.config import Config
    from app.db import Repositories

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Rename:
    """One named location. ``old`` is the folder its config field named by
    default, ``old_key`` its former key — also the folder it stood in while
    the field was empty. ``new`` is both its folder and its key now."""

    old: str
    new: str
    old_key: str
    field: str


LOCATIONS: tuple[Rename, ...] = (
    Rename("bilder", "images", "bilder", "bilder_verzeichnis"),
    Rename("bildmodelle", "image_models", "bildmodelle", "bildmodelle_verzeichnis"),
    Rename("modelle", "models", "modelle", "modelle_verzeichnis"),
    Rename("einbettungsmodelle", "embedding_models", "einbettung", "einbettungsmodelle_verzeichnis"),
    Rename("sprachmodelle", "speech_models", "sprache", "sprachmodelle_verzeichnis"),
    Rename("skripte", "scripts", "skripte", "skripte_verzeichnis"),
    Rename("agentendock", "agent_dock", "agentendock", "agentendock_verzeichnis"),
)

# The chats' own folders: always under the data folder, never a location of
# their own (app/dokumentablage.py).
CHAT_FILES_OLD = "chatdateien"

# The model's smaller picture copies: a cache under the data folder, never a
# location of its own (app/speicherorte.py, ``MODELLBILDER_ORDNER``).
MODEL_IMAGES_OLD = "modellbilder"

# The companion folders inside the image models folder, former name → name.
COMPANIONS: tuple[tuple[str, str], ...] = (
    ("gesichter", "faces"),
    ("gesichter_aufbereitet", "faces_prepared"),
    ("textversteher", "text_encoders"),
)

# The note of folders renamed whose stored paths have not followed yet.
PENDING = "folder-renames.json"

# The lock every step of the move runs under, held on the data folder itself
# and not on a service's port. Two services on two ports that start at the
# same moment each find no other service yet, and each held only the lock of
# its own port: both renamed, and the one whose rename then failed took the
# pair of the one whose rename went through back out of the note — the
# stored paths of that move never followed.
MOVE_LOCK = "folder-renames.lock"

# How long a start that did not get the lock waits for the service moving to
# give it back, and how often it asks in between. Both are the bounds Windows
# sets on a waiting lock: ``msvcrt.locking`` with ``LK_LOCK`` tries ten
# times, a second apart, before it gives up (Python documentation, module
# ``msvcrt``, ``locking``). Past the wait the names are read as they stand
# and the start goes on — a move hanging on a disk that does not answer
# must not hold this start for good.
MOVE_WAIT_SECONDS = 10.0
MOVE_WAIT_STEP = 1.0


def _data_dir(config: "Config") -> Path:
    """The data folder as every step of the move names it: absolute, with
    links left as they are (``_plain``) — the folder the renames, the note
    and the lock on the move all lie in, reached one way for all of them."""
    return _plain(aufloesen(config.app.data_dir, schreibbar=True))


def lock_path(config: "Config") -> Path:
    """Where the lock on the move (``MOVE_LOCK``) lives — worked out once by
    the service's start and handed to both halves of the move. The data folder is
    made for it, the way the note's writer makes it (``_write_note``): the
    folders to carry over need not lie in it — the shipped defaults beside
    the program, the companions in the image models folder — and a data
    folder not made yet must not hold their move back."""
    data_dir = _data_dir(config)
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        # The lock cannot be taken then, and the try at it says why.
        pass
    return data_dir / MOVE_LOCK


def _lock_within_wait(
    path: Path, step: str
) -> tuple["instanzschloss.Schloss | None", OSError | None, bool]:
    """The lock on the move, tried at once and then every ``MOVE_WAIT_STEP``
    for at most ``MOVE_WAIT_SECONDS``; answered as ``instanzschloss.try_lock``
    answers its last try, and with whether another service held it on the
    way — said in the log once, naming ``step``. Not waited for where the
    lock cannot be taken at all: nobody can be moving under it then, and
    waiting would change nothing.

    The wait blocks the thread it runs on, also where that thread runs the
    event loop: the service's start (``app/main.py``, the lifespan) calls
    in from there, before it serves anything — there is nothing on the loop
    yet that the wait could hold up, and nothing may ask for a location
    before the folder names are settled."""
    end = time.monotonic() + MOVE_WAIT_SECONDS
    waited = False
    while True:
        lock, error = instanzschloss.try_lock(path)
        if lock is not None or error is not None or time.monotonic() >= end:
            return lock, error, waited
        if not waited:
            log.info("%s not carried over yet: another service holds %s", step, path)
            waited = True
        time.sleep(MOVE_WAIT_STEP)


def _say_without_lock(step: str, path: Path, error: OSError) -> None:
    """The log line of a step done without the lock on the move because
    that lock cannot be taken at all: the step runs as it ran before there
    was a lock, and nothing keeps a second service from moving alongside."""
    log.warning("%s carried over without the lock: %s cannot be taken (%s)", step, path, error)


def carry_over(config: "Config", path: Path | None = None) -> bool:
    """Everything but the stored paths, which need the database: folders,
    config lines, stored keys. Runs before the first location is asked
    for, and under the lock on the move.

    Whoever gets the lock — at once, or after waiting for the service that
    held it — reads the folder names again first (``names_read_again``) and
    then carries over whatever is still left: another service may have
    moved the folders and written the new names after this one read its
    configuration, and may have stopped half way. Carrying over again is
    harmless: what was done already is found done. A lock still held when
    the wait ends leaves the folders to its holder; only the names are read
    again then. Where the lock cannot be taken at all, nobody can move under
    it either: the folders are carried over without it, as they were before
    there was one, and the log says so.

    ``path`` is the lock's file (``lock_path``). Answers whether the stored
    paths are this start's to follow (``paths_carried_over``): not where the
    lock was still held when the wait ended — the holder moves them, and a
    second wait of the same length would only hold this start up twice."""
    if path is None:
        path = lock_path(config)
    lock, error, waited = _lock_within_wait(path, "Folders")
    if error is not None:
        _say_without_lock("Folders", path, error)
    elif lock is None:
        log.warning(
            "Folder names read again: another service still holds %s after %.0f s",
            path, MOVE_WAIT_SECONDS,
        )
    try:
        # Read again under the lock, or where somebody was moving a moment
        # ago; a lock that cannot be taken at all says nobody was.
        if lock is not None or waited:
            names_read_again(config)
        # Carried over by whoever may: the holder of the lock, or anybody
        # where there is no lock to hold. A lock still held when the wait
        # ends leaves the folders to its holder.
        if lock is not None or error is not None:
            _carry_over(config)
    finally:
        instanzschloss.loslassen(lock)
    return lock is not None or error is not None


def names_read_again(config: "Config") -> None:
    """The folder of every location as the configuration file names it now.
    Also asked by a start that moves nothing because another service is
    using the folder (``app/main.py``): that one may have moved the folders
    and written the new names after this one read its configuration.
    Only those fields, read straight from the file the configuration came
    from, the value as written. Nothing else is done: the file is not
    written, nothing else in the configuration changes. A file that cannot
    be read or holds no ``app`` mapping, a line the file does not carry, or
    a value that is no text, leaves the name as it was read at start."""
    source = config._source
    if source is None:
        return
    try:
        raw = yaml.safe_load(source.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as error:
        log.warning("Folder names not read again from %s: %s", source, error)
        return
    # An empty file, or one that is no mapping, or one whose ``app`` is no
    # mapping, names no folder: the names stay as they were read at start.
    if not isinstance(raw, dict) or not raw:
        return
    section = raw.get("app")
    if not isinstance(section, dict):
        return
    for location in LOCATIONS:
        value = section.get(location.field)
        if isinstance(value, str):
            setattr(config.app, location.field, value)


def paths_carried_over(
    config: "Config", repositories: "Repositories", path: Path | None = None
) -> None:
    """Points stored paths below the folders the note names at their new
    names, under the lock on the move: a note read while another process is
    in the middle of moving can lose the pair that process is writing.

    Waited for as a start without the lock waits (``_lock_within_wait``):
    a service that found the lock taken asks for it again and again until
    it is free, and each time holds it for a moment — the service that
    moved the folders, coming here right after, must not leave its stored
    paths behind because one of those moments fell on its own try. Where
    the lock cannot be taken at all, the paths follow without it, as the
    folders were moved without it. ``path`` is the lock's file
    (``lock_path``)."""
    if path is None:
        path = lock_path(config)
    lock, error, _waited = _lock_within_wait(path, "Stored paths")
    if error is not None:
        _say_without_lock("Stored paths", path, error)
        _paths_carried_over(config, repositories)
        return
    if lock is None:
        log.info("Stored paths not carried over: another service holds %s", path)
        return
    try:
        _paths_carried_over(config, repositories)
    finally:
        instanzschloss.loslassen(lock)


def _carry_over(config: "Config") -> None:
    """Everything but the stored paths, which need the database: folders,
    config lines, stored keys."""
    data_dir = _data_dir(config)
    # Where a shipped relative value of a model folder sat: beside the
    # program's data, as the shipped data folder does.
    shipped = _plain(aufloesen(type(config.app).model_fields["data_dir"].default, schreibbar=True))
    pending = data_dir / PENDING
    # Read once: the pins and the carrying over of former keys decide on
    # the same file.
    stored = speicherorte.stored_as_written(config)
    pins = _pins(config, stored)
    # Every folder no location names — the set each rename is judged against.
    # One folder of the user's anywhere in a path holds that path back, and
    # each pin is compared by the rule of the disk it lies on (`_keys`),
    # the same rule the folder being renamed is compared by (`_rename`).
    unnamed = set().union(*pins.values())
    lines: list[tuple[str, str, str]] = []
    folders: dict[str, tuple[Path, Path, set[str]]] = {}
    for location in LOCATIONS:
        pinned = set().union(*(keys for field, keys in pins.items() if field != location.field))
        value = getattr(config.app, location.field) or ""
        if not value.strip():
            _rename(data_dir / location.old_key, data_dir / location.new, pinned, pending)
            continue
        named = _plain(aufloesen(value, schreibbar=True))
        if named.name == location.new and named.parent in (data_dir, shipped):
            # Already the new default — written by the configuration's own
            # update for a key the file did not have.
            _rename(named.parent / location.old, named, pinned, pending)
            continue
        new_value = _renamed_value(value, location)
        if new_value is None or named.parent not in (data_dir, shipped):
            # A folder of the user's own: the location is not on its default.
            continue
        lines.append((location.field, value, new_value))
        folders[location.field] = (named, named.parent / location.new, pinned)
    if lines:
        _config_lines(config, lines, folders, pending)
    speicherorte.keys_renamed(config, stored)
    _rename(
        data_dir / CHAT_FILES_OLD,
        data_dir / dokumentablage.CHATDATEIEN,
        unnamed,
        pending,
    )
    _rename(
        data_dir / MODEL_IMAGES_OLD,
        data_dir / speicherorte.MODELLBILDER_ORDNER,
        unnamed,
        pending,
    )
    # The companions lie inside the image models folder, which can lie on a
    # disk other than the data folder's. `_rename` compares each of them by
    # the rule of the disk it lies on, so nothing is said about it here.
    image_models = speicherorte.ort(config, "image_models")
    for old, new in COMPANIONS:
        _rename(image_models / old, image_models / new, unnamed, pending)


def _paths_carried_over(config: "Config", repositories: "Repositories") -> None:
    """Points stored paths below the folders the note names at their new
    names: uploads, and folders shared with a chat or a project — only where
    the file or folder really lies at the new place. The note goes once
    that is done; without one there is nothing to do."""
    pending = _data_dir(config) / PENDING
    pairs = _noted(pending)
    if not pairs:
        if pairs is None:
            # Said out loud, like everywhere else this state is met: the
            # stored paths below the renamed folders do not follow, and
            # nothing else would ever mention them.
            log.warning(
                "Note %s cannot be read: stored paths below renamed folders"
                " are left as they are",
                pending,
            )
        return
    # Every pair is compared by the rule of the disk its own folder lies on
    # (`following`): the folders renamed on one start need not all lie on the
    # disk the data folder lies on.
    follow = following(pairs)
    # One transaction for both: a start that ends in between leaves every
    # row as it was and the note in place, and the next start does it all.
    with repositories.db.transaktion():
        documents = repositories.documents.all_paths_moved(follow)
        shares = repositories.chats.shares_moved(follow)
    pending.unlink(missing_ok=True)
    log.info(
        "Renamed folders: %d document path(s) and %d share list(s) moved along",
        documents, shares,
    )


def following(
    pairs: Iterable[Sequence[str]], ignore_case: bool | None = None
) -> Callable[[str], Path | None]:
    """A function telling where a stored path lies after the renames in
    ``pairs``, taken in the order they were done — a companion folder
    renamed inside a models folder renamed on the same start is followed
    through both. It answers None when no rename touched the path. Stored
    paths are written with links followed, and so are the noted folders,
    so this compares names only: in one Unicode form, and letter case aside
    where the disk sets it aside. Which disk sets it aside is measured per
    pair — on the folder the pair renames, since the companions inside the
    image models folder can lie on a disk of their own — unless
    ``ignore_case`` names the rule for all of them. What lies below the
    renamed folder is kept as written."""
    # (the former folder's parts, the new folder, how this pair is compared:
    # measured on its own disk, or the one rule a caller gave)
    folders: list[tuple[list[str], str, Callable[[str], str]]] = []
    for old, new in pairs:
        renamed = _resolved(Path(old))
        text = _text_for(renamed) if ignore_case is None else _comparable(ignore_case)
        folders.append((
            [text(part) for part in renamed.parts],
            str(_resolved(Path(new))),
            text,
        ))

    def follow(path: str) -> Path | None:
        current = Path(str(path))
        moved = False
        for old, new, text in folders:
            parts = current.parts
            if len(parts) >= len(old) and [text(part) for part in parts[: len(old)]] == old:
                current, moved = Path(new, *parts[len(old):]), True
        return current if moved else None

    return follow


def _comparable(ignore_case: bool) -> Callable[[str], str]:
    """How two path texts are made comparable. Always in one Unicode form:
    a name with an umlaut can come composed from one place (config.yaml)
    and decomposed from another (a folder dialog on macOS). Letter case
    aside only where the disk sets it aside too — on one that does not,
    ``Images`` and ``images`` are two folders."""
    if ignore_case:
        # Folded from the decomposed form, so both forms fold alike.
        return lambda text: unicodedata.normalize(
            "NFC", unicodedata.normalize("NFD", text).casefold()
        )
    return lambda text: unicodedata.normalize("NFC", text)


def _text_for(folder: Path) -> Callable[[str], str]:
    """How two path texts on the disk holding ``folder`` are compared. The
    one place that answers this: the folder being renamed and every folder
    the user set are compared by the rule of the disk each of them lies on,
    and two folders of the same comparison must be on the same disk for the
    question to mean anything — the folder named and the folder renaming it
    are."""
    return _comparable(_ignores_case(folder))


@functools.lru_cache(maxsize=None)
def _ignores_case(folder: Path) -> bool:
    """Whether the disk holding ``folder`` takes a name in other letter
    case for the same folder, as the usual disks of macOS and Windows do.
    Measured once per folder and start, with links followed, on the nearest
    folder that exists and has a letter in its name: the same name with its
    letter case turned is looked up. Where nothing can be measured, letter
    case is set aside."""
    try:
        probe = _resolved(folder)
        while probe != probe.parent and not (
            probe.exists() and probe.name != probe.name.swapcase()
        ):
            probe = probe.parent
    except OSError:
        return True
    if probe == probe.parent:
        return True
    try:
        return os.path.samefile(probe, probe.with_name(probe.name.swapcase()))
    except OSError:
        return False


def _resolved(path: Path) -> Path:
    try:
        return path.resolve()
    except (OSError, RuntimeError):
        return _plain(path)


def _renamed_value(value: str, location: Rename) -> str | None:
    """The config value with the new folder name, written the way it was —
    absolute or relative. None for a value that does not end in the former
    name as written (a trailing ``/.``, other letter case)."""
    raw = value.rstrip("/\\")
    if not raw.endswith(location.old) or Path(raw).name != location.old:
        return None
    return raw[: -len(location.old)] + location.new


def _config_lines(
    config: "Config",
    lines: list[tuple[str, str, str]],
    folders: dict[str, tuple[Path, Path, set[str]]],
    pending: Path,
) -> None:
    """Renames the folders of the lines the file is known to take, then
    writes those lines in one go — and into the configuration already read
    from it. A folder whose line could not be written after all goes back
    to its former name; where that fails too, the configuration names it
    where it lies for this start."""
    source = config._source
    if source is None:
        return
    takes = configwanderung.values_found(source, lines)
    ready = []
    renamed: dict[str, tuple[Path, Path]] = {}
    for field, value, new_value in lines:
        if field not in takes:
            continue
        old_folder, new_folder, pinned = folders[field]
        if _touches(new_folder, pinned, _text_for(new_folder)):
            # Another location already uses the new name: two locations
            # never share a folder.
            continue
        if _present(old_folder):
            if not _rename(old_folder, new_folder, pinned, pending):
                # The folder stays under its former name, so the line keeps
                # naming it; the next start tries both again.
                continue
            renamed[field] = (new_folder, old_folder)
        ready.append((field, value, new_value))
    written = configwanderung.values_replaced(source, ready) if ready else set()
    for field, value, new_value in ready:
        if field in written:
            setattr(config.app, field, new_value)
            log.info("Config %s: %s -> %s", field, value, new_value)
        elif field in renamed:
            new_folder, old_folder = renamed[field]
            if not _rename(new_folder, old_folder, set(), pending):
                # The folder is under the new name and the file still names
                # the former one: this start reads it where it lies, and the
                # next one writes the line.
                setattr(config.app, field, new_value)
                log.warning(
                    "Config %s not written and folder %s not moved back to %s:"
                    " using %s until the next start writes the line",
                    field, new_folder, old_folder, new_folder,
                )


def _pins(config: "Config", stored: dict | None) -> dict[str | None, set[str]]:
    """Every folder something the user set names, by where it was set: the
    stored overrides (``stored``, the file as written), under any key
    (``None``), and the config field of each location. Such a folder, and
    one inside it, is theirs: it is not renamed, and not taken over by a
    rename. Each path is kept as written and with its links followed, since
    an override is stored with its links followed and a folder under the
    data folder is compared as written.

    Each of them is compared by the rule of the disk it lies on (``_keys``),
    which is the rule the rename of a folder on that disk is compared by:
    one folder of the user's can lie on a disk other than the data folder's,
    and there "Faces" and "faces" are the same folder — a pin written in
    either spelling is theirs either way."""
    stored_values = [
        value for value in (stored or {}).values() if isinstance(value, str) and value
    ]
    pins: dict[str | None, set[str]] = {None: _keys(stored_values)}
    for location in LOCATIONS:
        value = getattr(config.app, location.field) or ""
        pins[location.field] = _keys([value] if value.strip() else [])
    return pins


def _keys(values: list[str]) -> set[str]:
    """Every spelling of every one of the user's paths, each in both letter
    cases: what is written and what it resolves to, once as it stands and
    once folded together.

    Not by the rule of the disk the path lies on. The comparison this feeds
    (``_touches``) asks whether a pin names the folder being renamed or a
    folder inside it — and it folds the folder being renamed by the rule of
    ITS disk. Folding each side by its own disk would compare two texts that
    were folded differently, and a folder the user named would go unnamed
    whenever the two disks disagree about letter case — a pin behind a mount
    point or a link, most plainly. Keeping both forms of the pin leaves the
    choice with the side that has to be exact: on a disk that sets letter
    case aside, the folded form matches; on one that does not, only the path
    as written does, and there "Images" and "images" are two folders anyway.
    The safe direction is also the one taken here: a pin that is missed
    renames a folder the user set, while a pin that matches one time too
    often only puts the rename off to the next start."""
    keys: set[str] = set()
    for value in values:
        path = _plain(aufloesen(value, schreibbar=True))
        for spelling in (path, _resolved(path)):
            for ignore_case in (False, True):
                keys.add(_key(spelling, _comparable(ignore_case)))
    return keys


def _plain(path: Path) -> Path:
    """An absolute path with ``.`` and ``..`` taken out and links left as
    they are: a link under the data folder is itself what gets renamed."""
    return Path(os.path.normpath(os.path.abspath(path)))


def _key(path: Path, text: Callable[[str], str]) -> str:
    """A path as a comparable text (``_comparable``)."""
    return text(str(_plain(path)))


def _resolved_key(path: Path, text: Callable[[str], str]) -> str:
    try:
        return text(str(path.resolve()))
    except (OSError, RuntimeError):
        return _key(path, text)


def _touches(path: Path, pinned: set[str], text: Callable[[str], str]) -> bool:
    """Whether a pin names ``path`` or a folder inside it. A link is taken
    as written: renaming it moves nothing of what it points at."""
    keys = (
        {_key(path, text)} if path.is_symlink() else {_key(path, text), _resolved_key(path, text)}
    )
    return any(pin == key or pin.startswith(key + os.sep) for key in keys for pin in pinned)


# What a file manager leaves in a folder it only showed: not the user's.
_VIEWER_FILES = {".DS_Store", "Thumbs.db", "desktop.ini"}


def _only_viewer_files(folder: Path) -> bool:
    return all(entry.name in _VIEWER_FILES and entry.is_file() for entry in folder.iterdir())


def _present(path: Path) -> bool:
    """A folder, or a link to one — also a link whose drive is not
    mounted right now, which renames just as well."""
    return path.is_dir() or path.is_symlink()


def _rename(old: Path, new: Path, pinned: set[str], pending: Path) -> bool:
    """Renames ``old`` to ``new`` and notes it in ``pending``. Not while
    something the user set names ``old``, ``new`` or a folder inside either,
    and not over anything but an empty folder under the new name — one the
    program made itself on a start that could not rename yet, with at most
    what a file manager leaves behind. True when it was renamed.

    ``old`` decides how names are compared: it is the folder that moves, and
    the rule is the one of the disk it lies on (`_text_for`). Without a note
    that takes its pair, nothing moves — the note is what makes a move
    survivable, and a move nothing noted never gets its stored paths
    followed."""
    if not _present(old):
        return False
    text = _text_for(old)
    if _touches(old, pinned, text) or _touches(new, pinned, text):
        log.warning("Folder %s not renamed: a location you set names it", old)
        return False
    try:
        if new.is_dir() and not new.is_symlink() and _only_viewer_files(new):
            for entry in new.iterdir():
                entry.unlink()
            new.rmdir()
        if new.exists() or new.is_symlink():
            # Logged at every start until it is resolved, so the line says
            # how: nothing is ever merged by the program itself.
            log.warning(
                "Folder %s not renamed: %s already exists and is not an empty folder."
                " To finish, move the contents of %s into %s and delete %s",
                old, new, old, new, old,
            )
            return False
        if not _note(pending, old, new):
            return False
        try:
            old.rename(new)
        except OSError:
            # Nothing moved, so its pair must not stay in the note: the note
            # is read in both directions, and a new → old pair would carry
            # stored paths back to a folder that is not there — the paths of
            # a folder renamed for real would never follow again.
            _forget(pending, old, new)
            raise
    except OSError as error:
        # Not fatal: the location simply reads as empty this time round and
        # the next start tries again.
        log.warning("Folder %s could not be renamed to %s: %s", old, new, error)
        return False
    log.info("Folder renamed: %s -> %s", old, new)
    return True


def _noted(pending: Path) -> list[list[str]] | None:
    """The note as a list of pairs — or None for a note that is there and
    cannot be read.

    A note that is not there is an empty note: the ordinary state of a folder
    nothing was renamed in yet. A note that IS there and cannot be read is
    something else, and writing over it would take every rename in it along —
    that is what None says. Something readable that is not a list of pairs
    holds none, so it reads as empty; a pair that is not a pair is left
    out."""
    try:
        text = pending.read_text(encoding="utf-8")
    except FileNotFoundError:
        return []
    except (OSError, UnicodeError):
        # UnicodeError is a ValueError and not an OSError: a note restored
        # from a backup in another encoding lands here, and it must not
        # travel up as an exception out of the whole carry-over.
        return None
    if not text.strip():
        return []
    try:
        entries = json.loads(text)
    except ValueError:
        # Not readable as a list of pairs at all. Nothing readable is lost
        # by leaving it alone, and nothing readable can be kept from it
        # either — so the move waits rather than writing over it.
        return None
    if not isinstance(entries, list):
        return None
    return [
        list(entry) for entry in entries
        if isinstance(entry, list) and len(entry) == 2
        and all(isinstance(part, str) for part in entry)
    ]


def _note(pending: Path, old: Path, new: Path) -> bool:
    """Adds a rename to the note before it is done: a note of a rename that
    then failed only costs a look at paths that are not there. False when the
    note cannot be read or written — then the rename does not happen either,
    because a move without its pair in the note is a move whose stored paths
    are never followed (``paths_carried_over``)."""
    entries = _noted(pending)
    if entries is None:
        log.warning("Note %s cannot be read: %s is not renamed", pending, old)
        return False
    entries.append(_pair(old, new))
    try:
        _write_note(pending, entries)
    except OSError as error:
        log.warning("Note %s cannot be written (%s): %s is not renamed", pending, error, old)
        return False
    return True


def _forget(pending: Path, old: Path, new: Path) -> None:
    """Takes the pair of a rename back out of the note after that rename
    failed. It moved nothing, and a pair left behind is not harmless: the
    note is read in both directions, so a new → old pair would carry every
    stored path of the new folder back to a folder that is not there.

    Written back only when the pair was really taken out: a note that cannot
    be read is not an empty note, and writing what was read would throw the
    pairs of every earlier rename away."""
    pair = _pair(old, new)
    entries = _noted(pending)
    if entries is None:
        log.warning(
            "Note %s cannot be read and %s did not move: the pair stays in it"
            " and stored paths below it will not follow",
            pending,
            old,
        )
        return
    for index in range(len(entries) - 1, -1, -1):
        if entries[index] == pair:
            del entries[index]
            try:
                _write_note(pending, entries)
            except OSError as error:
                # The pair stays, and the stored paths of this folder will
                # not follow; said out loud, because nothing else would ever
                # mention them.
                log.warning(
                    "Folder %s did not move and its pair could not be taken out of %s"
                    " (%s): stored paths below it will not follow",
                    old,
                    pending,
                    error,
                )
            return
    log.warning(
        "Note %s does not carry %s: the pair of the failed move of %s stays"
        " out of it, stored paths below it will not follow",
        pending,
        pair,
        old,
    )


def _pair(old: Path, new: Path) -> list[str]:
    """One rename as the note writes it. With the parent's links followed,
    the way stored paths are written; the folder itself is named, since it
    is the one that moves."""
    return [str(_resolved(old.parent) / old.name), str(_resolved(new.parent) / new.name)]


def _write_note(pending: Path, entries: list[list[str]]) -> None:
    """The note, written whole (app/atomic_file.py): a reader landing in
    the middle must never see half of it, and a rename that failed leaves
    no half-written file in the folder."""
    pending.parent.mkdir(parents=True, exist_ok=True)
    atomic_file.write(pending, json.dumps(entries, ensure_ascii=False))
