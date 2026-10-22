"""Exe AI's own command line client, as the service sees it.

Two questions about it come up in the service, and both are answered here so
that they cannot drift apart:

  * **Where does its command lie?** The system prompt names that path to the
    model, so the model can run the client with its shell. The service often
    has no ``/usr/local/bin`` on its path, so a bare ``exe`` would not be
    found: the prompt carries the full path instead.
  * **Does a shell command start it?** The client can switch the approval
    mode, change settings and run a model without any question, so a command
    that starts it is judged like a path outside the shared folders
    (app/tools/shell.py).

The client lives in a package of its own and does not import the service,
nor the service the client: the locations of its command are repeated here
from where the installer puts it.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

# What the command is called on the path of a terminal: ``exe`` on a Mac or a
# Linux machine, ``exe.cmd`` (the installer's wrapper) or ``exe.exe`` on
# Windows.
PROGRAM_NAMES = ("exe", "exe.cmd", "exe.exe")

# Where a command of a line begins: at its start, after a separator or a
# subshell, or as the string handed to ``sh -c``. Behind it may stand, in any
# order, variables set for that one command, words that only hand the command
# on and their switches, and then comes the program: quoted whole, or a bare word.
_PROGRAM = re.compile(
    r"""
    (?:^|[;&|\n(`]|\$\(|\s-\w*c\s+["']?)
    \s*
    (?:[A-Za-z_]\w*=\S*\s+|(?:sudo|env|command|exec|nohup|time)\s+|-\S+\s+)*
    (?:"(?P<double>[^"]+)"|'(?P<single>[^']+)'|(?P<bare>[^\s;&|()<>"'`$]+))
    """,
    re.VERBOSE,
)


def _program() -> Path | None:
    """The service program of the installed app — ``None`` where the service
    runs from its source folder."""
    if not getattr(sys, "frozen", False):
        return None
    return Path(sys.executable).resolve()


def path() -> Path | None:
    """The command of the installed program, as a file — ``None`` where the
    service runs from its source folder or the file is not there.

    On a Mac the command lies in the ``bin`` folder beside the folder of the
    service program; on Windows ``exe.exe`` lies next to the service
    program."""
    program = _program()
    if program is None:
        return None
    command = (
        program.parent / "exe.exe"
        if sys.platform == "win32"
        else program.parent.parent / "bin" / "exe"
    )
    return command if command.is_file() else None


def _commands() -> list[Path]:
    """Every file that starts the client: its command, and on Windows the
    wrapper the installer puts on the path (``bin\\exe.cmd`` beside the
    ``resources`` folder)."""
    found = [path()]
    program = _program()
    if program is not None and sys.platform == "win32":
        found.append(program.parent.parent.parent / "bin" / "exe.cmd")
    return [command for command in found if command is not None and command.is_file()]


def _same_file(word: str, commands: list[Path]) -> bool:
    try:
        wanted = str(Path(word).expanduser().resolve()).casefold()
        return any(wanted == str(command.resolve()).casefold() for command in commands)
    except (OSError, RuntimeError):
        return False


def starts(shell_command: str) -> str | None:
    """The program word of the first command in ``shell_command`` that starts
    the client, as it was written — or ``None``.

    A bare ``exe``, ``exe.cmd`` or ``exe.exe`` counts, and so does a path to
    the installed command. A path to some other file named ``exe`` does not:
    it is somebody's own program."""
    commands = _commands()
    for found in _PROGRAM.finditer(shell_command):
        word = found.group("double") or found.group("single") or found.group("bare")
        if "/" in word or "\\" in word or word.startswith("~"):
            if _same_file(word, commands):
                return word
        elif word.lower() in PROGRAM_NAMES:
            return word
    return None


def for_prompt(*, shell_offered: bool, zugriff: tuple[str, str] | None) -> str | None:
    """The command the system prompt names to the model, or ``None`` where
    the prompt says nothing of the client.

    The prompt tells the model to run the client only where it can: the
    program is installed (a run from the source folder has no command), the
    run has a shell, and the rules do not refuse it a command that starts a
    program outside its folders. ``zugriff`` is what the path rules answer
    inside and outside the folders (``berechtigungen.zugriffslage``); ``None``
    is a run without folders, where commands do not run at all."""
    if not shell_offered or zugriff is None or zugriff[1] == "nein":
        return None
    command = path()
    return None if command is None else str(command)
