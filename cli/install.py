"""``install``: the command ``exe`` on the path, placed again at any time.

The app places the link on its first start; this is the way to place it by
hand — after a move of the app, on a machine whose first start declined the
password window, or simply to see where it lies. A link, not a copy: it
points at the command inside the installed program, so an update of the
program is an update of the command.
"""

from __future__ import annotations

import errno
import os
import sys
from pathlib import Path

from cli.texts import Texts

# Where the link lies: the folder every terminal of the machine looks in.
LINK = Path("/usr/local/bin/exe")

# The outcomes of placing it.
PLACED = "placed"
KEPT = "kept"
DENIED = "denied"
FAILED = "failed"


def target() -> Path | None:
    """The command inside the installed program — ``None`` where the program
    is not installed but run from its source folder, which has no command
    a link could point at."""
    if not getattr(sys, "frozen", False):
        return None
    # Packaged, the program lies in a folder of its own, and a bin folder
    # beside that folder holds the command: Resources/exe-ai-terminal/Exe AI
    # and Resources/bin/exe.
    return Path(sys.executable).resolve().parent.parent / "bin" / "exe"


def place(link: Path, target: Path) -> tuple[str, OSError | None]:
    """Places ``link`` pointing at ``target``: ``KEPT`` where it already does
    — nothing is touched then —, ``PLACED`` once it does, ``DENIED`` where
    the folder is not ours to write, ``FAILED`` with the error for anything
    else. A link pointing elsewhere is replaced; a file that is no link is
    not — it is somebody else's, and the error says so. Nor is a link
    placed to a command that is not there: it would point at nothing."""
    if not target.is_file():
        return FAILED, FileNotFoundError(errno.ENOENT, os.strerror(errno.ENOENT), str(target))
    try:
        if link.is_symlink() and os.readlink(link) == str(target):
            return KEPT, None
        link.parent.mkdir(parents=True, exist_ok=True)
        if link.is_symlink():
            link.unlink()
        link.symlink_to(target)
    except PermissionError as error:
        return DENIED, error
    except OSError as error:
        return FAILED, error
    return PLACED, None


def run(texts: Texts) -> int:
    """``exe install``: places the link and says where it lies — or why not.
    The return value is the exit code. On Windows there is nothing to place:
    the installer put the command on the path."""
    if sys.platform == "win32":
        print(texts.t("cli.install_windows"))
        return 0
    wanted = target()
    if wanted is None:
        print(texts.t("cli.install_source"), file=sys.stderr)
        return 1
    outcome, error = place(LINK, wanted)
    if outcome == KEPT:
        print(texts.t("cli.install_kept", path=LINK))
        return 0
    if outcome == PLACED:
        print(texts.t("cli.install_placed", path=LINK))
        return 0
    if outcome == DENIED:
        print(texts.t("cli.install_denied", path=LINK, program=wanted), file=sys.stderr)
        return 1
    print(texts.t("cli.install_failed", path=LINK, error=error), file=sys.stderr)
    return 1
