"""What is actually lying in a folder the user owns.

Three places in this program show a folder the user can open in the file
manager, move with a pencil and drop things into: the pictures, the agents'
delivery shelf, and the scripts. Every one of them used to show something
NARROWER than the folder, and each in its own way — the pictures listed only
names the server had minted itself (``^[a-f0-9]{32}\\.(png|jpg|webp)$``), the
shelf listed only what its record knew about, and the scripts listed nothing
at all. A picture called ``diagramm.png``, a file an agent wrote into the
shelf with a file tool, a script somebody put there by hand: all invisible,
in a folder whose whole point is that it belongs to the person.

So the answer lives once, here: what is in the folder is what is shown.

TWO QUESTIONS, AND THE SECOND IS THE DANGEROUS ONE. Listing cannot give
anything away by itself. Handing a file back by the name a browser sends can
— ``../../etc/passwd`` is a name too, and so is a link inside the folder
pointing anywhere else. ``sicherer_pfad`` is that guard, and it is the same
shape as the one the script runner has carried all along (``geprueft``,
app/skriptlauf.py): the name has to be a plain file name, and the RESOLVED
path has to still be inside the folder, because resolving is what turns a
link back into where it really goes.

THE FIRST QUESTION ANSWERS BY THE SAME RULE. Everything that follows a
listing goes through that guard or its twin in the script runner — the
click on a tile, the picture the wall fetches, the script a schedule fires —
so a listing that showed more than the guard lets through would be showing
tiles nothing behind the wall can open: a delivery that can neither be
fetched nor removed, a picture box that stays broken, a script the wall
calls runnable and the runner refuses at its first firing. ``auflisten``
therefore drops what resolves out of the folder, by the same test, and
listing and using agree by construction instead of by every caller
remembering to check twice.

Deliberately not merged with ``skriptlauf.geprueft``. That one also demands
the executable bit and answers in a script runner's words, through a script
runner's exception; sharing would mean one of the two callers getting
sentences about scripts for a picture, or losing the check that a script
must be runnable at all.
"""

from __future__ import annotations

from pathlib import Path


def auflisten(
    ordner: Path,
    *,
    endungen: frozenset[str] | None = None,
    mindestgroesse: int = 0,
    auslassen: frozenset[str] = frozenset(),
) -> list[Path]:
    """The files in the folder, newest first.

    A missing folder is not an error: it is the state before the first file,
    and the honest answer to it is an empty list — the same answer the
    pictures gave for a folder that had been moved away.

    ``endungen`` filters by suffix, lower-cased and with the dot
    (``{".png"}``). ``mindestgroesse`` drops files too small to be what they
    claim — a stray zero-byte file would otherwise stand as a broken tile.
    ``auslassen`` is for a folder that keeps its own bookkeeping beside the
    files, like the shelf's record.

    Folders inside are skipped rather than listed: none of the three walls
    can show one, and a folder standing among the files as an unopenable
    tile is worse than not being there.

    A link is listed by where it leads, not by where it lies. One pointing
    at a file inside the folder — a second name for it, or a file in a
    subfolder — is as good as that file. One leading out of the folder is
    skipped: ``is_file`` follows it and says yes, ``sicherer_pfad`` resolves
    it and says no, and a tile the guard behind it refuses is the unopenable
    tile again.
    """
    ordner = Path(ordner)
    if not ordner.is_dir():
        return []
    # Resolved once, the way ``sicherer_pfad`` resolves it for every name:
    # the containment test below compares real places, and the folder itself
    # may be reached through a link.
    wurzel = ordner.resolve()
    treffer: list[Path] = []
    for pfad in ordner.iterdir():
        if not pfad.is_file() or pfad.name in auslassen:
            continue
        if endungen is not None and pfad.suffix.lower() not in endungen:
            continue
        try:
            # The same containment test as ``sicherer_pfad``. ``is_file``
            # has already followed a link and said yes; whether it leads out
            # of the folder only shows once it is resolved.
            if not pfad.resolve().is_relative_to(wurzel):
                continue
            if pfad.stat().st_size < mindestgroesse:
                continue
        except OSError:
            # Gone between the listing and the question. Not an error; the
            # next listing simply will not have it either.
            continue
        treffer.append(pfad)
    treffer.sort(key=lambda p: (-_stempel(p), p.name.lower()))
    return treffer


def _stempel(pfad: Path) -> float:
    try:
        return pfad.stat().st_mtime
    except OSError:
        return 0.0


def sicherer_pfad(ordner: Path, name: str) -> Path | None:
    """One file inside the folder, addressed by name — or nothing.

    Nothing, not an exception: every caller answers a missing file with the
    same 404 it answers a refused name with, and a name that tries to leave
    the folder deserves no more detailed reply than a name that is simply not
    there.

    ``resolve`` before the containment test is the whole guard. It follows
    links, so a link lying INSIDE the folder and pointing outside comes out
    with its real path and fails — which is exactly what comparing the given
    string would have waved through.
    """
    roh = str(name or "").strip()
    if not roh or roh in (".", "..") or roh != Path(roh).name:
        return None
    try:
        wurzel = Path(ordner).resolve()
        ziel = (wurzel / roh).resolve()
    except (OSError, RuntimeError):
        # A name that cannot be resolved at all is a name that leads
        # nowhere, and it is answered like every other one that does. The
        # RuntimeError is the one worth naming: a link pointing at itself
        # makes ``resolve`` give up with "Symlink loop", and unguarded that
        # left a request answering 500 where the honest answer is the same
        # 404 a missing file gets. Measured.
        return None
    if ziel == wurzel or not ziel.is_relative_to(wurzel):
        return None
    return ziel if ziel.is_file() else None
