"""The text editor of the computer, for a text too long to type in a line.

One module for every command with a long text: the text goes into a file of
its own, the editor opens it where the terminal is, and what the person
saved comes back — or nothing, where there is nothing to take over.

The editor is never started through a shell: its name is split into words
the way a shell would split it, and the file is the last word.
"""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable, Mapping
from pathlib import Path

from cli.interfaces import Context

# The editors tried in this order where neither VISUAL nor EDITOR names one.
_FALLBACKS = ("editor", "nano", "pico", "vi", "emacs")

# The last resort: every system that has any editor has this one.
_LAST_RESORT = "vi"
_WINDOWS_EDITOR = "notepad"


def _without_quotes(word: str) -> str:
    """A word of a Windows command line, with the double quotes around it
    taken off — the splitter keeps them there."""
    if len(word) > 1 and word[0] == word[-1] == '"':
        return word[1:-1]
    return word


def command(
    environ: Mapping[str, str] | None = None,
    *,
    windows: bool | None = None,
    which: Callable[[str], str | None] = shutil.which,
) -> list[str]:
    """The words that start the editor, without the file: VISUAL, else
    EDITOR (a value with switches, such as ``code --wait``, is split into its
    words); else on Windows the notepad; else the first of the usual editors
    that is on the path; else ``vi``."""
    variables = os.environ if environ is None else environ
    on_windows = (sys.platform == "win32") if windows is None else windows
    for name in ("VISUAL", "EDITOR"):
        value = variables.get(name, "").strip()
        if not value:
            continue
        try:
            # Where the separator of a path is a backslash, a shell's rules
            # would eat it; the words keep their quotes there and lose them
            # here.
            words = shlex.split(value, posix=not on_windows)
        except ValueError:
            # Quotes that never close: this variable names no editor.
            continue
        if on_windows:
            words = [_without_quotes(word) for word in words]
        if words:
            return words
    if on_windows:
        return [_WINDOWS_EDITOR]
    for name in _FALLBACKS:
        if which(name):
            return [name]
    return [_LAST_RESORT]


def edit(ctx: Context, text: str) -> str | None:
    """Opens ``text`` in the editor and returns what the person saved — or
    ``None`` where there is nothing to take over: the editor ended with an
    error code, or the text is the same but for the blanks at its edges. An
    editor that cannot be started is said in the system's own words.

    The file lives in a folder of its own, gone again whatever happened. As
    long as the editor is open nothing is said and nothing is added to the
    history: the screen steps aside and comes back after it."""
    folder = tempfile.mkdtemp(prefix="exe-edit-")
    try:
        path = Path(folder) / "text.md"
        path.write_text(text, encoding="utf-8")
        words = [*command(), str(path)]

        def run() -> int:
            return subprocess.run(words, check=False).returncode

        try:
            code = ctx.screen.hand_over(run)
            if code != 0:
                return None
            edited = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as error:
            ctx.renderer.error(str(error))
            return None
    finally:
        shutil.rmtree(folder, ignore_errors=True)
    if edited.strip() == text.strip():
        return None
    return edited
