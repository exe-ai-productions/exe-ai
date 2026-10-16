"""The named storage locations, in one place.

Every folder the terminal writes the user's things into — the pictures it
draws, the picture models, the language models — is a NAMED location here,
not a path spelled out at each call site. One function answers "where does
X live", so the places that need a folder ask by name instead of building
the path by hand.

Why a module of its own: the same wish ("let me put this somewhere else",
"open that folder", "show me the path") turned up for pictures, for models
and for the catalogue's downloads. Four scattered answers would be four
things to keep in step; one place is one truth.

Two layers decide where a location lives:

  * the DEFAULT, a field in config.yaml (``bilder_verzeichnis`` and its
    siblings) — the as-installed place, next to the other data;
  * the OVERRIDE, a line in ``speicherorte.json`` in the data folder,
    written when the user moves a location elsewhere.

The override wins when present. It lives in its own small file on purpose:
config.yaml is full of explaining comments, and rewriting it would strip
every one of them — a JSON file the module owns can be rewritten freely.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from app import atomic_file

if TYPE_CHECKING:
    from app.config import Config

log = logging.getLogger(__name__)

# Serialises the read-modify-write on the overrides file. FastAPI runs the
# sync route handlers in a threadpool, so two saves can land at once; without
# this, both read the same starting file and the second write drops the
# first's entry.
_SCHLOSS = threading.Lock()

# The overrides file, kept in the data folder — isolated per installation
# and never mixed into the commented config.yaml.
UEBERSCHREIBUNGEN_DATEI = "speicherorte.json"


class SpeicherortFehler(Exception):
    """Carries the key of the sentence to show, not the sentence itself —
    same shape as the other runtime errors, so the route can localise it."""

    def __init__(self, grund: str) -> None:
        super().__init__(grund)
        self.grund = grund


@dataclass(frozen=True)
class Ort:
    """One named location: its key and the config field that holds its
    default path. Every location is read fresh each time it is needed, so a
    move takes hold at once and no restart is ever asked for."""

    name: str
    feld: str


# The known locations, in the order the settings screen lists them. The
# database file is deliberately NOT here: moving an open database is its own
# undertaking, and until it is one, its place stays fixed.
ORTE: tuple[Ort, ...] = (
    # The pictures are written and read fresh per request.
    Ort("images", "bilder_verzeichnis"),
    # The model folders are asked for by name at every listing, start and
    # download (``LiveFolders`` below, ``Modellrunner``'s folder source): a
    # server that is up keeps the model it loaded, the next start and the
    # next listing read the new folder.
    Ort("image_models", "bildmodelle_verzeichnis"),
    Ort("models", "modelle_verzeichnis"),
    Ort("embedding_models", "einbettungsmodelle_verzeichnis"),
    Ort("speech_models", "sprachmodelle_verzeichnis"),
    # The scripts a cron entry may start. Resolved fresh at every
    # firing — and it has to be: this folder is not only where the scripts
    # are kept, it is the boundary that decides what may run at all. A path
    # bound at startup would leave a moved folder running the old one's files.
    Ort("scripts", "skripte_verzeichnis"),
    # The agents' delivery shelf. Resolved fresh every time the
    # shelf is opened — a delivery, a listing, a download. The shelf keeps
    # its own record INSIDE this folder (app/agentendock.py), so the folder
    # is the whole shelf and a move can never leave a list here pointing at
    # files over there.
    Ort("agent_dock", "agentendock_verzeichnis"),
)

_NACH_NAME = {o.name: o for o in ORTE}

# The keys the locations had while their folders carried German names
# (app/folder_names.py). An override stored under one is read under the new
# key until the start that renames it has written the file anew.
FORMER_KEYS = {
    "bilder": "images",
    "bildmodelle": "image_models",
    "modelle": "models",
    "einbettung": "embedding_models",
    "sprache": "speech_models",
    "skripte": "scripts",
    "agentendock": "agent_dock",
}


def _ueberschreibungen_datei(config: "Config") -> Path:
    return config.datenverzeichnis / UEBERSCHREIBUNGEN_DATEI


def ueberschreibungen(config: "Config") -> dict[str, str]:
    """The stored overrides, name → absolute path. Empty when the file is
    missing (the as-shipped state) or unreadable (counts as none, so a
    broken file never takes a location down — the next save overwrites it)."""
    datei = _ueberschreibungen_datei(config)
    if not datei.exists():
        return {}
    try:
        roh = json.loads(datei.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as fehler:
        log.warning("Location overrides cannot be read (%s): %s", datei, fehler)
        return {}
    if not isinstance(roh, dict):
        return {}
    # Only known names, only string paths — a stale or hand-edited entry for
    # a location that no longer exists is ignored, not carried around. A
    # former key counts for its new one while no entry has the new key.
    found = {
        name: wert
        for name, wert in roh.items()
        if name in _NACH_NAME and isinstance(wert, str) and wert
    }
    for old, new in FORMER_KEYS.items():
        value = roh.get(old)
        if new not in found and isinstance(value, str) and value:
            found[new] = value
    return found


def standard(config: "Config", name: str) -> Path:
    """The as-installed folder for a location, ignoring any override — what
    'reset to default' returns to.

    An empty config field means "under the data folder": the location follows
    a moved data_dir exactly as ``datenverzeichnis / name`` did, instead of a
    hardcoded path that would strand old files when someone set data_dir."""
    eintrag = _NACH_NAME.get(name)
    if eintrag is None:
        raise KeyError(f"Unknown storage location: {name!r}")
    wert = getattr(config.app, eintrag.feld)
    if not wert:
        return config.datenverzeichnis / name
    return config.pfad(wert)


def ort(config: "Config", name: str) -> Path:
    """The absolute folder for a named location: the override if one is set,
    otherwise the installed default. Raises ``KeyError`` for an unknown name
    so a typo fails loud, not silently at some wrong folder."""
    if name not in _NACH_NAME:
        raise KeyError(f"Unknown storage location: {name!r}")
    ueber = ueberschreibungen(config).get(name)
    if ueber:
        return Path(ueber).expanduser().resolve()
    return standard(config, name)


class LiveFolders(Mapping[str, Path]):
    """Folders by kind that follow the locations: every lookup asks ``ort``
    again, so a folder moved a moment ago is the one a request sees. Handed
    to the places that used to be given one folder at startup (the download
    router's folder per kind) — a plain dict built once would still name the
    old folder after the move."""

    def __init__(self, config: "Config", names: dict[str, str]) -> None:
        self._config = config
        self._names = dict(names)

    def __getitem__(self, art: str) -> Path:
        return ort(self._config, self._names[art])

    def __iter__(self):
        return iter(self._names)

    def __len__(self) -> int:
        return len(self._names)


# Where the smaller copies for the model live (app/model_image.py). A cache,
# not one of the user's places: it is derived from the pictures, never moved,
# and deliberately NOT an entry in ORTE — the settings screen lists what is
# listed there, and a cache does not belong on it. It sits under
# the DATA folder and no longer beside the pictures: moving the picture
# folder neither takes the cache along nor can strand it next to the old one.
# A copies folder under its former German name is carried over at start
# (app/folder_names.py).
MODELLBILDER_ORDNER = "model-images"


def bildkopien_verzeichnis_fuer(daten_dir: str | Path) -> Path:
    """The same folder for a caller that carries the data folder along
    instead of reading the running process's config — the tool path
    (app/tools/datei_lesen.py): a run hands its own data folder over, and a
    test's copies land under the test's folder, never in the installed one.

    The path is resolved first: a relative one (a raw ``./data`` from a
    config field) would otherwise be read against whatever working directory
    the process happens to have when the copies folder is first used —
    and the next start would not find it again."""
    return Path(daten_dir).expanduser().resolve() / MODELLBILDER_ORDNER


def bildkopien_verzeichnis(config: "Config") -> Path:
    """Where the model's picture copies live, asked for by name.

    ``config.datenverzeichnis`` is resolved already (``Config.pfad``), so
    it is not resolved a second time: ``resolve`` walks every part of the
    path on disk, and an absolute, resolved path gains nothing from that."""
    return config.datenverzeichnis / MODELLBILDER_ORDNER


# Where the picture studio's working pictures lie: the frames taken from a
# video, and the starting image and mask the drawing surface puts together.
# They are made for a draw and no message names them, so they never lie in
# the picture folder and never reach the wall. Like the copies above no
# entry in ORTE, and under the data folder for the same reason. The service
# empties the folder when it starts (app/main.py).
SCRATCH_PICTURES_FOLDER = "scratch-pictures"


def scratch_pictures_dir(config: "Config") -> Path:
    """Where the studio's working pictures lie, asked for by name."""
    return config.datenverzeichnis / SCRATCH_PICTURES_FOLDER


def _gleicher_ort(a: Path, b: Path) -> bool:
    """Do two paths point at the same real folder? ``samefile`` follows
    symlinks and matches the case-insensitive filesystem on macOS, where a
    plain string compare would call ``/Users/x/Bilder`` and ``.../bilder``
    different. It needs both to exist; when one does not, fall back to a
    case-folded string compare."""
    try:
        return a.samefile(b)
    except OSError:
        return os.path.normcase(str(a)) == os.path.normcase(str(b))


def _verschachtelt(a: Path, b: Path) -> bool:
    """Does one folder sit inside the other? Case-folded so a nesting is not
    missed on a case-insensitive filesystem."""
    na, nb = os.path.normcase(str(a)), os.path.normcase(str(b))
    if na == nb:
        return False
    return na.startswith(nb + os.sep) or nb.startswith(na + os.sep)


def _pruefen(config: "Config", name: str, pfad: str | Path) -> Path:
    """A path fit to store this location's things in: absolute, a folder that
    exists or can be made, writable, and not colliding with another location.
    Raises ``SpeicherortFehler`` with a specific key otherwise — a path the
    program cannot use must be refused where it is set, not discovered as a
    failed picture later."""
    ziel = Path(pfad).expanduser()
    if not str(ziel).strip():
        raise SpeicherortFehler("speicherorte.leer")
    ziel = ziel.resolve()
    if ziel.exists() and not ziel.is_dir():
        raise SpeicherortFehler("speicherorte.kein_ordner")
    try:
        ziel.mkdir(parents=True, exist_ok=True)
    except OSError:
        raise SpeicherortFehler("speicherorte.nicht_anlegbar") from None
    if not os.access(ziel, os.W_OK):
        raise SpeicherortFehler("speicherorte.nicht_schreibbar")
    # Never the data folder itself, nor a folder above it: the dock and the
    # picture folder are in the folder list of every run, and the data
    # folder holds the chats, the keys and the configuration. A folder
    # INSIDE it is fine — that is where every location lies by default.
    daten = Path(config.datenverzeichnis).resolve()
    if _gleicher_ort(ziel, daten) or os.path.normcase(str(daten)).startswith(
        os.path.normcase(str(ziel)).rstrip(os.sep) + os.sep
    ):
        raise SpeicherortFehler("speicherorte.ueberschneidung")
    # No location may share a folder with another, nor sit inside it: two
    # kinds of files in one folder would mix, and a cleanup of one kind could
    # take the other's files with it.
    for anderer in ORTE:
        if anderer.name == name:
            continue
        fremd = ort(config, anderer.name)
        if _gleicher_ort(ziel, fremd) or _verschachtelt(ziel, fremd):
            raise SpeicherortFehler("speicherorte.ueberschneidung")
    # And the copies' cache is no ORTE entry, so the loop above cannot see
    # it: a picture folder pointing AT it (or holding it) would put the
    # model's copies on the wall the module docstring promises they never
    # reach. The same for the studio's working pictures, whose folder is
    # emptied at every start: a location laid there would lose its files.
    for hidden in (bildkopien_verzeichnis(config), scratch_pictures_dir(config)):
        if _gleicher_ort(ziel, hidden) or _verschachtelt(ziel, hidden):
            raise SpeicherortFehler("speicherorte.ueberschneidung")
    return ziel


def setzen(config: "Config", name: str, pfad: str | Path) -> Path:
    """Point a location at a new folder. The path is checked first (see
    ``_pruefen``); a path equal to the installed default removes the override
    instead of storing it, so 'back to default' leaves no dead line behind.
    Returns the resolved folder now in force."""
    if name not in _NACH_NAME:
        raise KeyError(f"Unknown storage location: {name!r}")
    ziel = _pruefen(config, name, pfad)
    if _gleicher_ort(ziel, standard(config, name)):
        loeschen(config, name)
        return ziel
    with _SCHLOSS:
        daten = ueberschreibungen(config)
        daten[name] = str(ziel)
        _schreiben(config, daten)
    return ziel


def loeschen(config: "Config", name: str) -> Path:
    """Drop a location's override, back to the installed default. Returns the
    default now in force. Doing nothing when there was no override is fine —
    the end state is the same."""
    if name not in _NACH_NAME:
        raise KeyError(f"Unknown storage location: {name!r}")
    with _SCHLOSS:
        daten = ueberschreibungen(config)
        if name in daten:
            del daten[name]
            _schreiben(config, daten)
    return standard(config, name)


def _schreiben(config: "Config", daten: dict[str, str]) -> None:
    """Write the overrides whole (app/atomic_file.py), so an interrupted
    write leaves the old file intact rather than a half-written one."""
    datei = _ueberschreibungen_datei(config)
    datei.parent.mkdir(parents=True, exist_ok=True)
    atomic_file.write(datei, json.dumps(daten, ensure_ascii=False, indent=2) + "\n")


def uebersicht(config: "Config") -> list[dict]:
    """Every location for the settings screen: its name, the folder in force,
    the installed default, and whether it currently sits on the default."""
    ueber = ueberschreibungen(config)
    zeilen = []
    for eintrag in ORTE:
        std = standard(config, eintrag.name)
        gilt = Path(ueber[eintrag.name]).expanduser().resolve() if eintrag.name in ueber else std
        zeilen.append({
            "name": eintrag.name,
            "pfad": str(gilt),
            "standard": str(std),
            "ist_standard": _gleicher_ort(gilt, std),
        })
    return zeilen


def stored_as_written(config: "Config") -> dict | None:
    """The overrides file as it stands, every key kept — also the former
    ones ``ueberschreibungen`` drops. None when it is missing, unreadable
    or not an object."""
    try:
        stored = json.loads(_ueberschreibungen_datei(config).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return stored if isinstance(stored, dict) else None


def keys_renamed(
    config: "Config", stored: dict | None, renamed: dict[str, str] = FORMER_KEYS
) -> None:
    """Carries overrides stored under a location's former key over to its
    current one (app/folder_names.py). ``stored`` is the file as it stands
    (``stored_as_written``), read once at start by the caller, which decides
    more on the same reading; nothing else writes the file that early.
    ``ueberschreibungen`` would not do: it drops every key it no longer
    knows — the very entries this is for. The path is the user's choice and
    stays as it is; a key that already has an entry under its new name
    keeps that one. Nothing is written when nothing was renamed."""
    if stored is None:
        return
    path = _ueberschreibungen_datei(config)
    with _SCHLOSS:
        entries = dict(stored)
        for old, new in renamed.items():
            if old in entries:
                value = entries.pop(old)
                current = entries.get(new)
                # The same rule as reading: an entry under the new key
                # counts only when it names a path.
                if not (isinstance(current, str) and current):
                    entries[new] = value
        if entries != stored:
            try:
                _schreiben(config, entries)
            except OSError as error:
                # Read under the former keys until the next start manages it.
                log.warning("Storage locations not carried over (%s): %s", path, error)
