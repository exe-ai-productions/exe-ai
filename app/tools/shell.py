"""The shell tool — `run_command`.

One generic tool with a free command string, deliberately not a set of small
ones (`create_file`, `move`, `list_dir`). The core cases are opening
folders, creating and moving files — everyday file work. A single command
string covers all of it, including the things nobody thought of in advance.

Why this is built in and not a separate MCP server: the working folders
belong to the chat and change while the program runs. An outside process
would have to be told the folder with every call — and anything passed as an
argument can be forged by the model. Built in, the terminal takes the folder
from the chat itself; the model never gets a say in where it works.

The safety story:

* **The share is the boundary.** Setting a working folder IS the permission.
  Inside it nothing asks again — creating, moving, deleting all run through.
  That was chosen over confirming every single action, which would have made
  the tool useless in practice.
* **Outside it, the model asks.** A command that reaches beyond the shared
  folders triggers the ordinary confirmation prompt above the input field.
* **Without a shared folder the tool stays shut.** No folder, no execution —
  the model is told so plainly.
* **The block list is a tripwire, not a sandbox.** It stops the obviously
  catastrophic (`sudo`, `rm -rf /`, fork bombs, piping the net into a shell).
  It is NOT a security boundary and does not pretend to be one: a container
  or chroot was consciously rejected for build cost and platform dependence.

The command runs through the shell on purpose — pipes and redirection are
half of what file work is. That is the point of the exercise, not an
oversight.
"""

from __future__ import annotations

import asyncio
import contextlib
import glob
import logging
import ntpath
import os
import posixpath
import re
import shlex
import signal
import subprocess
import sys
import threading
from collections.abc import Callable
from functools import partial
from pathlib import Path, PurePath
from typing import Any

from app import aufgaben, ordnerwissen
from app.no_console import no_window
from app.tools import hintergrund, ordnergedaechtnis
from app.tools.grenzen import aufgeloest as _aufgeloest
from app.tools.grenzen import liegt_innerhalb
from app.tools.grenzen import prepare_folders
from app.tools.mcp_client import MCPWerkzeug

log = logging.getLogger(__name__)

SERVER_NAME = "shell"
WERKZEUG_NAME = "run_command"

WINDOWS = sys.platform == "win32"

# How long a command may run before it is stopped, unless the caller says
# otherwise. Long enough for a real build, short enough that a hung process
# does not block the chat forever. This is the DEFAULT, not the law any
# more: the actual limit is a setting (app/befehlszeitwahl.py), resolved by
# the caller and handed to ausfuehren() — whoever sets nothing gets exactly
# this number.
ZEITGRENZE_SEKUNDEN = 120

# How much output goes back to the model. A `find /` would otherwise fill the
# whole context with paths.
MAX_AUSGABE_ZEICHEN = 20_000

# What marks the place where a line was cut. asyncio's stream reader keeps one
# line at a time in a buffer of a fixed size; when a line outgrows it the
# reader throws away what it has collected so far and raises, then carries on
# reading the rest of that same line. Uncaught, that ended the companion task
# of a background run: the run stood at LAEUFT for the life of the process,
# nothing was ever reported into the chat and nothing woke the model — a `cat`
# on one minified file was enough.
#
# Measured on the running service, one 200 000-character line: the note
# appears, part of the line is gone, the rest arrives, and the command runs to
# its end. So this says CUT, not "dropped" — what the user sees is a line with
# a hole in it, and the sentence names the hole.
#
# Said out loud rather than cured with a bigger buffer, which would only move
# the same wall further out and hide it on the way: a line that does not fit
# is a fact, and the user reading the terminal is the one it concerns.
HINWEIS_ZEILE_ZU_LANG = "[A line exceeded the reader's length limit and was truncated here.]"

# The tripwire. Deliberately short: every pattern here has to be worth its
# false positives, otherwise it only trains people to work around it.
#
# These are matched against the raw command string, so they also catch what
# hides in the middle of a pipeline.
GEFAEHRLICH: tuple[tuple[str, str], ...] = (
    (r"(^|[;&|]\s*)sudo\b", "sudo"),
    (r"(^|[;&|]\s*)su\s", "su"),
    (r"\brm\s+(-[a-zA-Z]*\s+)*-?[a-zA-Z]*[rf][a-zA-Z]*\s+/(\s|$|\*)", "rm -rf /"),
    (r"\bmkfs(\.|\s)", "mkfs"),
    (r"\bdd\b[^|]*\bof=/dev/", "dd onto a device"),
    (r":\(\)\s*\{.*\}\s*;?\s*:", "a fork bomb"),
    (r"\bchmod\s+(-[a-zA-Z]+\s+)*777\s+/(\s|$)", "chmod 777 /"),
    (r"\b(shutdown|reboot|halt|poweroff)\b", "shutting the machine down"),
    # curl … | sh — fetching something from the net straight into a shell is
    # how a machine gets taken over, and it is never what file work needs.
    (r"\b(curl|wget)\b[^|]*\|\s*(sudo\s+)?(ba|z|k)?sh\b", "a fetch from the net piped into a shell"),
    (r"\b(launchctl|systemctl)\b", "system services"),
    (r">\s*/dev/(sd|nvme|disk)", "writing to a device"),
)

# The one file a command may not take away: the ``exe.md`` at the top of a
# shared folder — what the user wrote down about that folder, kept up to date
# by the model. The write tool has refused to replace it whole for a while
# (app/tools/datei_schreiben.py), but the refusal sat in that tool alone: a
# plain ``rm exe.md`` walked straight past it and the file was gone.
#
# As narrow as the write tool's own check, and no wider: THIS file, at the
# TOP of a shared folder, and only where the command would remove or
# overwrite it. Reading it, grepping it, copying it somewhere else, appending
# to it with ``>>`` — all untouched. A file of the same name one level down
# is not this file.
#
# Two lists, because position is what decides for half of them. Everything in
# the first takes away every file it is handed; everything in the second only
# takes away its LAST operand, and its first is the source, which survives.
# `mv` is in both: it takes its source away AND replaces its destination.
_NIMMT_WEG = frozenset({"rm", "unlink", "shred", "truncate", "tee", "mv"})
_NIMMT_DAS_ZIEL = frozenset({"cp", "install", "ln", "rsync", "mv"})

# Where one command ends and the next begins, as its own word. Read out of the
# line rather than guessed: `shlex` is asked for punctuation of its own, so
# `ls;rm exe.md` is three words and not two — without that the verb of the
# second command reads as `ls;` and every list above misses it.
# The characters a word is made of when that word ENDS one command and
# begins the next. Read as a set rather than as a list of spellings, because
# `shlex` hands out a whole run of punctuation as ONE word: `;`, `&&` and
# `|&` are three spellings, and so is a blank line between two commands
# (`\n\n\n`), which no list of spellings would ever be long enough for.
# `<` and `>` are deliberately not here — a redirect belongs to its command.
_TRENNZEICHEN = ";|&`()\n"

# The opening of a here-document. Everything from the word after it to the
# line that is only the delimiter is TEXT the command WRITES — a script, a
# note, a block of documentation — and not a command of its own. Without
# this the line break above turns that text into commands: a model writing
# `cat > aufraeumen.sh <<"EOF"` with `rm exe.md` in the body had its FILE
# refused, although nothing was ever going to touch the note.
_HEREDOC = re.compile(r"^\d*<<-?$")

# The same opener with its delimiter glued on. Only the hand split above
# produces it — `shlex` cuts the operator off — and there it matters: the
# body of a here-document must stay TEXT even when an apostrophe in it broke
# the split. `(?!<)` keeps a here-STRING (`<<<`) out of it.
_HEREDOC_KLEBT = re.compile(r"^\d*<<-?(?!<)(.+)$")

# Quoted text, so it can be blanked out before the line is searched for an
# operator. `shlex` takes the quotes off, and after that a literal `"<<"` is
# the same word as the operator — a `grep "<<" notiz.md` opened a phantom
# here-document and swallowed the rest of the line.
_ZITAT = re.compile(r"'[^']*'|\"[^\"]*\"")

# A run of separator characters, for the hand split above.
_TRENNLAUF = re.compile(r"([;|&`()\n]+)")

# A line continued with a backslash. A shell removes the pair before it reads
# anything, so `rm -f \⏎ exe.md` is one command — for the lexer it looked like
# two, and the guard judged `rm -f` alone and let the note go. The lookbehind
# keeps an ESCAPED backslash (`\\` before the break) out of it.
_FORTSETZUNG = re.compile(r"(?<!\\)((?:\\\\)*)\\\n")

# A redirect that opens its target for writing: `>`, `1>`, `2>`, `&>` (both
# streams) and `>|` (past noclobber) — never `>>`, which appends and leaves
# what is there.
_SCHREIBPFEIL = re.compile(r"^\d*&?>\|?$")

# `>&` writes too, when the word after it is a file rather than a stream:
# `tee x >& exe.md` sends both streams into the note and empties it first.
# A stream number (`2>&1`, `>&2`) or a closing dash (`>&-`) names no file.
_DUPLICATING_ARROW = re.compile(r"^\d*>&$")


def _writes_into(arrow: str, target: str) -> bool:
    """Whether the redirect ``arrow`` opens the word ``target`` for writing."""
    if _SCHREIBPFEIL.match(arrow):
        return True
    return bool(_DUPLICATING_ARROW.match(arrow)) and not (target.isdigit() or target == "-")


# Any redirect at all, the appending and the reading kind included. These
# words and the word after them belong to the redirect, not to the verb —
# `cp neu.md exe.md 2>/dev/null` otherwise ends in `/dev/null` as its
# destination and the real one goes unchecked. The duplicating kind (`>&`,
# `<&`) is one too: `cat <<EOF >&2` ends its line there, and `2>&1` behind a
# copy must not stand in for its destination.
_UMLEITWORT = re.compile(r"^\d*&?[<>]{1,2}[|&]?$")

# Letters that swallow the rest of their bundle as a VALUE. Without them the
# `-i` search reads the value: `perl -Ilib` and `perl -MList::Util` carry a
# lowercase `i` in a library name, and every operand of a reading command was
# refused as if the file were being rewritten in place. Per verb, because the
# same letter means different things: `sed -E` is a regex dialect and takes
# nothing, `perl -E` is code. And per platform for one of them: GNU `sed -l N`
# is a line length, while the `sed` of macOS reads `-l` as line-buffered
# output without a value — there `-li` is the in-place switch behind it.
_WERTBUCHSTABEN = {
    "sed": "efl",
    "perl": "IMmeEFxl0",
}
_OHNE_WERT_AUF_MACOS = {"sed": "l"}


def _wertbuchstaben(verb: str) -> str:
    """The letters of ``verb`` that swallow a value on THIS platform.

    Asked at every call rather than fixed at import, so the platform the
    command really runs on decides.
    """
    werte = _WERTBUCHSTABEN.get(verb, "")
    if sys.platform == "darwin":
        for buchstabe in _OHNE_WERT_AUF_MACOS.get(verb, ""):
            werte = werte.replace(buchstabe, "")
    return werte

# Where the destination of a copy or a move can hide instead of standing at
# the end: `-t <folder>` and `--target-directory` turn every operand into a
# source. Both directions went wrong without this — `mv -t .` refused a
# harmless move, `cp -t . unten/exe.md` replaced the note unseen. All four
# spellings GNU accepts are read, bundled short ones included (`cp -rt .`).
#
# Only for the verbs where `-t` MEANS that. `rsync` is the exception in this
# very list: its `-t` is `--times`, and reading its neighbour as a
# destination swapped source and target — `rsync -t unten/ .` went through
# and `rsync -t . unten/` was refused, each exactly the wrong way round.
# Per verb, and the same shape as `_WERTBUCHSTABEN` above, because it is the
# same question: which letter of a bundle swallows the rest as its VALUE.
# Without it `install -oroot` — the standard line of every Makefile — read as
# a bundle ending in `-t` and took the SOURCE for a destination folder, while
# the real destination went unchecked.
_ZIELWERTE = {
    "install": "gmoSt",
    "cp": "St",
    "mv": "St",
    "ln": "St",
}
_ZIELSCHALTER_LANG = "--target-directory"


def _ist_zielschalter_lang(wort: str) -> bool:
    """Whether ``wort`` is ``--target-directory`` or an abbreviation of it.

    GNU accepts every unambiguous abbreviation of a long option, and no
    other long option of these verbs begins with ``--t``, so `--target-dir=.`
    and even `--t .` name the destination exactly as the full spelling does.
    """
    name = wort.partition("=")[0]
    return len(name) > 2 and _ZIELSCHALTER_LANG.startswith(name)

# What a word has to carry to be a pattern rather than a name. A pattern is
# expanded against the folder before it is judged: `rm *.md` is typed, not
# built at runtime, and it takes the notes with it.
_MUSTERZEICHEN = "*?["

# Where a command may reach without asking: the shared folders. Everything
# else needs the user's yes. What counts as "reaching outside" is a
# heuristic, not a proof — see `greift_nach_draussen`.
# The look-behind excludes the dot so "./run_tests.sh" stays one relative
# path instead of yielding the stump "/run_tests.sh".
_PFAD_MUSTER = re.compile(r"(?<![\w.-])(~[/\w.-]*|/[\w./-]+)")

# A search pattern is not a path. `grep '/'` looks for a slash, `sed
# 's|/old|/new|g'` rewrites text — neither opens a folder. Reading those
# arguments as paths made five out of ten everyday commands ask for nothing,
# which is what killed unattended work in a shared folder.
#
# The list is the price of the accuracy: it has to be kept, and a tool that
# is missing from it falls back to the old, cautious reading. That is the
# right way round — a gap here costs a false alarm, never a silent reach.
_MUSTER_WERKZEUGE = frozenset({"grep", "egrep", "fgrep", "rg", "sed", "awk", "find"})

# Options whose VALUE is the pattern rather than a file. Given one of these,
# the command has no positional pattern left — its operands are all files.
_MUSTER_OPTIONEN = frozenset({
    "-e", "--regexp", "--expression",
    "-name", "-iname", "-path", "-ipath", "-wholename", "-regex", "-iregex",
})

# The opposite case: the pattern is READ FROM a file, so that argument is a
# real path and stays checked — and there is no positional pattern either.
_DATEI_OPTIONEN = frozenset({"-f", "--file"})

# Where one command ends and the next begins. Every command in a pipeline
# gets its own look at which of its words is the pattern.
_BEFEHLSTRENNER = frozenset({"|", "||", "&&", ";", "&"})

# A regex anchor at the edge settles it on its own, without any list: no path
# starts with `^`, none ends with `$`. The whole word is a pattern.
_ANKER_ANFANG = "^"
_ANKER_ENDE = "$"

# Wildcards are the awkward half of the same idea: they belong to a regex AND
# to a glob, so the word cannot simply be voided — `rm /tmp/*` really does
# reach outside. Only the literal part in front of the first one is judged,
# which keeps that catch and still drops `^/(usr|bin)`.
_PLATZHALTER = "*[]|"

# A URL reaches into the net, not into a folder. It still has to be
# confirmed — it is only announced as what it is, instead of being reported
# as the folder "/beispiel.de/api". `file://` is deliberately left out: that
# one IS a local path and stays with the folder check.
_NETZ_MUSTER = re.compile(
    r"""(?<![\w.-])(?!file://)([a-z][a-z0-9+.-]*)://([^\s"'`;|&()<>]+)""",
    re.IGNORECASE,
)


def _muster_eines_befehls(name: str, teile: list[str], von: int, bis: int) -> set[int]:
    """Indexes of the words THIS single command uses as a search pattern.

    Two ways in: named by an option (`grep -e X`, `find -name X`), or the
    first operand (`grep X datei`, `sed X datei`). Only one of them applies —
    once an option carried the pattern, the operands are all files again.

    ``find`` is the exception that proves it: its first operand is the folder
    to search, so it never gives up a positional word.
    """
    treffer: set[int] = set()
    aus_option = False
    erster_operand: int | None = None
    optionen_zuende = False
    j = von
    while j < bis:
        wort = teile[j]
        if not optionen_zuende and wort == "--":
            optionen_zuende = True
            j += 1
            continue
        if not optionen_zuende and wort.startswith("-") and len(wort) > 1:
            schluessel, trenner, wert = wort.partition("=")
            if schluessel in _MUSTER_OPTIONEN:
                if trenner:
                    treffer.add(j)
                elif j + 1 < bis:
                    treffer.add(j + 1)
                    j += 1
                aus_option = True
            elif schluessel in _DATEI_OPTIONEN:
                # The value is a path on purpose — skip it WITHOUT marking
                # it, so it stays in the folder check.
                if not trenner and j + 1 < bis:
                    j += 1
                aus_option = True
            j += 1
            continue
        if erster_operand is None:
            erster_operand = j
        j += 1
    if name != "find" and erster_operand is not None and not aus_option:
        treffer.add(erster_operand)
    return treffer


def _musterworte(teile: list[str]) -> set[int]:
    """Indexes of every word in the line that is a pattern, not a path."""
    muster: set[int] = set()
    i = 0
    anzahl = len(teile)
    while i < anzahl:
        while i < anzahl and teile[i] in _BEFEHLSTRENNER:
            i += 1
        if i >= anzahl:
            break
        name = teile[i].rsplit("/", 1)[-1]
        ende = i + 1
        while ende < anzahl and teile[ende] not in _BEFEHLSTRENNER:
            ende += 1
        if name in _MUSTER_WERKZEUGE:
            muster |= _muster_eines_befehls(name, teile, i + 1, ende)
        i = ende
    return muster


def netzziel(befehl: str) -> str | None:
    """The address on the net this command reaches, or None.

    Scheme and host only. That is what the decision hangs on — everything
    after the host says what is fetched, not from whom.
    """
    treffer = _NETZ_MUSTER.search(befehl)
    if not treffer:
        return None
    gastgeber = treffer.group(2).split("/", 1)[0]
    if not gastgeber:
        return None
    return f"{treffer.group(1).lower()}://{gastgeber}"



class ShellVerboten(Exception):
    """The command hit the tripwire, or there is no shared folder."""


def werkzeug_beschreibung(zeitgrenze: int | None = None) -> MCPWerkzeug:
    """The tool as the model sees it.

    The description says what it can do AND where — a model that does not
    know its boundary writes paths that then trigger a prompt for no reason.

    ``zeitgrenze`` is the limit that actually applies to this run, resolved
    by the caller (app/befehlszeitwahl.py). The sentence about it must name
    that value, not the shipped default — a model told 120 while 600 apply
    reaches for the background for no reason, and the other way round it
    walks into the wall it was promised was not there.

    The background lane is named as chat-only in both places that mention
    it. Everything except the time limit is the same text for every caller,
    while the lane itself is not: a job refuses ``background=true`` outright
    (``ausfuehren``, ``hintergrund_erlaubt``), because the result would have
    no conversation to land in. A description that offers it anyway walks a
    job's model into exactly the wall the paragraph above is about — and the
    reason travels with the restriction, so a model that reads it spends the
    next round on the task instead of on a way round the refusal.
    """
    grenze = zeitgrenze if zeitgrenze and zeitgrenze >= 1 else ZEITGRENZE_SEKUNDEN
    return MCPWerkzeug(
        name=WERKZEUG_NAME,
        beschreibung=(
            "Runs a shell command on the user's computer and returns its output. "
            "Use it for what the file tools cannot do: running programs such "
            "as builds, tests and git; moving, renaming and deleting files; "
            "opening a folder or file in the desktop UI. Where you have "
            "read_file, write_file, edit_file, search_files, list_dir or "
            "create_folder, use those for reading, writing, editing, searching "
            "and listing files and for making folders. Where you have a tool "
            "for web searches or for reading web pages, use it for those "
            "instead of curl or wget.\n"
            "It runs in the user's own shell, so pipes, redirection and globs "
            "work, inside the shared folders — relative paths resolve against "
            "the first one, or against a private working folder when none is "
            "shared.\n"
            "A `cd` persists to the next call, as long as the folder stays "
            "inside the shared ones.\n"
            f"Nothing is interactive: a command that waits for input hangs until "
            f"it is stopped after {grenze} seconds. Use the "
            "non-interactive flags (-y, --yes, --no-pager). In a chat, anything "
            "that takes longer belongs in the background: set background to "
            "true, the call returns at once and the result appears in the chat "
            "by itself when it is done — and a new answer of yours starts from "
            "that result on its own, so do not ask the user to report back. "
            "In a job the background is refused, "
            "because its result would have no conversation to appear in — run "
            "the command normally there.\n"
            f"Output is cut off at {MAX_AUSGABE_ZEICHEN:,} characters — narrow the "
            "command down rather than asking for everything and reading the "
            "first part of it.\n"
            "A few commands are refused outright, among them sudo, wiping a "
            "disk, and piping something off the net straight into a shell. That "
            "is not a permission question and rephrasing will not help; say so "
            "and suggest another way."
        ),
        schema={
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": 'Shell command to execute, e.g. "git status" or "npm run '
                                   'build".',
                },
                "background": {
                    "type": "boolean",
                    "description": (
                        "Start the command and return immediately. When it finishes, the "
                        "result appears in the chat and prompts you to continue. Use for "
                        "builds, downloads, and other tasks that take minutes. Available only "
                        "in a chat; jobs reject it because no conversation can receive the "
                        "result."
                    ),
                },
            },
            "required": ["command"],
        },
        server=SERVER_NAME,
    )


def blockiert(befehl: str) -> str | None:
    """Name of the pattern that stops this command, or None."""
    for muster, benennung in GEFAEHRLICH:
        if re.search(muster, befehl, re.IGNORECASE):
            return benennung
    return None


def _worte(befehl: str) -> list[str]:
    """The line split the way a shell reads it, operators as words of their own.

    ``shlex.split`` leaves `;` and `>` glued to their neighbours, so
    ``ls;rm exe.md`` came out as two words with the verb ``ls;`` — the
    commonest way of typing a second command walked straight past every list
    above it. ``punctuation_chars`` is what makes the operator its own word.
    A line that cannot be split at all (unbalanced quotes) falls back to the
    plain split, exactly as the neighbour function does.
    """
    # The shell takes a backslash-and-break out of the line before it reads a
    # single word of it. Done here for the same reason and in the same place.
    befehl = _FORTSETZUNG.sub(r"\1", befehl)
    try:
        # The default punctuation set plus the backtick and the line break.
        # The backtick because the old spelling of a command substitution is
        # the one way past every list otherwise (`` `rm exe.md` `` came out as
        # the verb `` `rm ``), and the line break because a NEW LINE ends a
        # command exactly as `;` does — and a block of several lines is the
        # commonest shape a model writes. It only becomes a word once it stops
        # counting as whitespace, which is what the line below does; inside
        # quotes it stays part of its word either way.
        leser = shlex.shlex(befehl, posix=True, punctuation_chars="();<>|&`\n")
        leser.whitespace = " \t\r"
        leser.whitespace_split = True
        # `shlex.split` turns comments off; the class does not, and its `#`
        # would swallow the rest of the line — while a shell only reads `#`
        # as a comment at the START of a word. `echo x#y; rm exe.md` really
        # does delete the file.
        leser.commenters = ""
        return list(leser)
    except ValueError:
        # An unbalanced quote — and English prose in a here-document body
        # produces one constantly ("Here's the plan"). Handing the whole
        # line back as ONE command is the least safe reading there is: no
        # `;`, no line break would separate anything, and everything behind
        # the body would be invisible. So the separators are cut by hand.
        stuecke = _TRENNLAUF.split(befehl)
        zurueck: list[str] = []
        for nr, stueck in enumerate(stuecke):
            if nr % 2:                 # a run of separators, kept whole
                zurueck.append(stueck)
            else:
                zurueck.extend(stueck.split())
        return zurueck


def _zitierte(befehl: str, worte: list[str]) -> set[int]:
    """Which of these words stood in quotes.

    ``shlex`` takes the quotes off in POSIX mode, and after that a literal
    ``"<<"`` is the same word as the operator. Read a second time WITHOUT
    the POSIX rule the quotes are still on, and the two readings hand out
    the same words in the same order — so the mark travels by index. Where
    the two disagree (a line neither can split), nothing is marked and the
    caller falls back to asking the line as a whole.
    """
    try:
        leser = shlex.shlex(befehl, posix=False, punctuation_chars="();<>|&`\n")
        leser.whitespace = " \t\r"
        leser.whitespace_split = True
        leser.commenters = ""
        roh = list(leser)
    except ValueError:
        return set()
    if len(roh) != len(worte):
        return set()
    return {nr for nr, wort in enumerate(roh) if wort[:1] in ("'", '"')}


def _wertstelle(bund: str, werte: str) -> int:
    """Where the first switch of this bundle swallows the rest as its value.

    Read left to right, because that is how a bundle works: everything after
    such a letter is its argument, not another switch. This is what tells
    `perl -pi` (in place) from `perl -Ilib` (a library path that happens to
    carry an `i`), and `cp -rt .` (a destination folder) from
    `install -oroot` (an owner whose name happens to end in `t`).
    """
    for nr, zeichen in enumerate(bund):
        if zeichen in werte:
            return nr
    return -1


def _heredoc_openers(line: str) -> list[tuple[str, bool, bool]]:
    """Every here-document this line opens, in order, as (delimiter, tabs
    stripped, body literal) — read the way the shell reads the line.

    Outside quotes and before a comment only; ``<<<`` is a here-string and
    opens nothing. The delimiter is the word after ``<<`` or ``<<-`` with its
    quoting taken off, and the body is literal where ANY part of that word
    was quoted — ``<<'EOF'``, ``<<"EOF"``, ``<<\\EOF`` and ``<<E'OF'`` alike.
    """
    openers: list[tuple[str, bool, bool]] = []
    i, n = 0, len(line)
    quote: str | None = None
    while i < n:
        char = line[i]
        if quote is not None:
            if char == quote:
                quote = None
            elif char == "\\" and quote == '"':
                i += 1
            i += 1
            continue
        if char == "\\":
            i += 2
            continue
        if char in "'\"":
            quote = char
            i += 1
            continue
        if char == "#" and (i == 0 or line[i - 1] in " \t;|&("):
            break
        if line.startswith("<<", i) and not line.startswith("<<<", i):
            j = i + 2
            strip = j < n and line[j] == "-"
            j += 1 if strip else 0
            while j < n and line[j] in " \t":
                j += 1
            word: list[str] = []
            literal = False
            inner: str | None = None
            while j < n:
                char = line[j]
                if inner is not None:
                    if char == inner:
                        inner = None
                    else:
                        word.append(char)
                    j += 1
                    continue
                if char in "'\"":
                    inner, literal = char, True
                    j += 1
                    continue
                if char == "\\" and j + 1 < n:
                    literal = True
                    word.append(line[j + 1])
                    j += 2
                    continue
                if char in " \t;|&<>()":
                    break
                word.append(char)
                j += 1
            if word:
                openers.append(("".join(word), strip, literal))
            i = j
            continue
        i += 1
    return openers


def _literal_bodies_kept(command: str) -> str:
    """The command with the body of every LITERAL here-document kept apart
    from the line joining the reading below does.

    That reading joins a backslash and a line break before it reads a word,
    as the shell does on a command line. In the body of a here-document
    whose delimiter is quoted the shell joins nothing: `x\\` stays a line of
    its own, and the delimiter on the next line ends the body. Joined, the
    delimiter disappeared into `xEOF` and everything behind it was read as
    body — a command after it went unseen. So a blank goes behind such a
    backslash, which the join does not take, and the body ends where the
    shell ends it.

    The one place the line structure of here-documents is read: every
    opener of a line, in order (several bodies follow one another), the
    bodies of unquoted ones left as they are — their backslashes do join,
    and a delimiter joined to the line before it ends nothing. A command
    that opens none comes back unchanged.
    """
    out: list[str] = []
    pending: list[tuple[str, bool, bool]] = []
    queue: list[tuple[str, bool, bool]] = []
    joined = False  # the line before ended in a joining backslash
    for line in command.split("\n"):
        ends_joined = (len(line) - len(line.rstrip("\\"))) % 2 == 1
        if queue:
            delimiter, strip, literal = queue[0]
            if not joined and (line.lstrip("\t") if strip else line) == delimiter:
                queue.pop(0)
                joined = False
            elif literal:
                if line.endswith("\\"):
                    line += " "
                joined = False
            else:
                joined = ends_joined
            out.append(line)
            continue
        # A command line: what it opens begins after the whole logical
        # line, the backslash-joined lines after it included.
        pending.extend(_heredoc_openers(line))
        joined = ends_joined
        if not joined:
            queue, pending = pending, []
        out.append(line)
    return "\n".join(out)


def notiz_in_gefahr(befehl: str, wurzel: Path | str, ordner: list[str]) -> str | None:
    """The folder note this command would remove or overwrite, or None.

    The same heuristic reading ``greift_nach_draussen`` uses, and honest
    about being one: it reads the words of the line and asks which of them a
    destroying verb was handed. A path built at runtime (``rm $(cat x)``) is
    beyond it, exactly as it is beyond the block list — this closes the way
    the file actually dies, which is somebody typing its name.

    Three things a name can be, all of them typed rather than built:

    * a path — resolved against ``wurzel``, the folder this chat stands in,
      because that is what the command itself will do;
    * a pattern — expanded against that folder, since ``rm *.md`` takes the
      note with it just as surely as ``rm exe.md``;
    * a folder — which counts only where the verb takes folders away
      (``rm -r``, ``mv``), and as a DESTINATION, where the real target is
      ``<folder>/<name of the source>``: ``cp neu/exe.md .`` replaces the
      note without ever spelling its path.

    What it does NOT see, said plainly rather than left to be found: a name
    carried inside another tool's arguments (``find . -name exe.md
    -delete``), a command handed to an interpreter (``bash -c 'rm exe.md'``
    and the same thing as a here-document, ``bash <<EOF``), and a folder
    changed mid-line (``cd unten && rm exe.md`` reads as the note of the
    folder the chat stands in, and is refused for a file one level down that
    nobody protects). Both kinds are the price of a tripwire over a shell
    state machine, and the module said from the start that this is the first
    and not the second.
    """
    if not ordner:
        return None
    # The bodies of literal here-documents kept apart from the line joining
    # below, as the shell keeps them (`_literal_bodies_kept`).
    befehl = _literal_bodies_kept(befehl)
    # Only a note that is REALLY THERE. The write tool guards the same file
    # the same way (`ziel.exists() and ordnerwissen.ist_notiz(...)`,
    # app/tools/datei_schreiben.py), and the two must not disagree: in a
    # folder whose note was never created, `echo "# Notes" > exe.md` is how
    # somebody WRITES one, and refusing it over a file that does not exist
    # would be a guard talking about nothing.
    notizen: list[Path] = []
    for eintrag in ordner:
        try:
            kandidat = ordnerwissen.datei(eintrag)
            if kandidat.is_file():
                notizen.append(kandidat.resolve())
        except OSError:
            continue
    if not notizen:
        return None

    def wege(wort: str) -> list[Path]:
        """Everything this word points at, resolved."""
        if not wort:
            return []
        roh = os.path.expanduser(wort)
        namen = [roh]
        if any(zeichen in roh for zeichen in _MUSTERZEICHEN):
            try:
                namen = glob.glob(roh, root_dir=str(wurzel))
            except (OSError, ValueError):
                namen = []
        aufgeloest: list[Path] = []
        for name in namen:
            pfad = Path(name)
            if not pfad.is_absolute():
                pfad = Path(wurzel) / pfad
            try:
                aufgeloest.append(pfad.resolve())
            except OSError:
                continue
        return aufgeloest

    def getroffen(pfade: list[Path], *, mit_ordner: bool) -> str | None:
        for pfad in pfade:
            for notiz in notizen:
                if pfad == notiz:
                    return str(notiz)
                if mit_ordner and notiz.is_relative_to(pfad) and notiz != pfad:
                    return str(notiz)
        return None

    # One line can be several commands, and each of them has its own verb.
    worte = _worte(befehl)

    def trennt(wort: str) -> bool:
        return bool(wort) and all(zeichen in _TRENNZEICHEN for zeichen in wort)

    def allein_auf_der_zeile(nr: int) -> bool:
        """Is the word at ``nr`` the only thing on its line?

        A here-document ends at a line that is EXACTLY the delimiter, so
        `echo EOF` inside the body does not end it. The scanner thinks in
        words where the rule speaks in lines; this is where the two meet.
        """
        # The break has to sit right against the word on both sides, for the
        # reason `bis_zeilenende_nur_umleitung` gives: a run of punctuation
        # arrives as ONE word, so `))\n` is a line that ends AFTER something
        # else, and `;\n` is a line that ends after a semicolon.
        vorher = nr == 0 or worte[nr - 1].endswith("\n")
        danach = nr + 1 >= len(worte) or worte[nr + 1].startswith("\n")
        return vorher and danach

    def bis_zeilenende_nur_umleitung(nr: int) -> bool:
        """Is there nothing but redirects between ``nr`` and the line's end?

        What tells a here-document from a left shift. `cat >n.sh <<"EOF"` and
        `cat <<EOF >n.sh` both end their line after the delimiter — but in
        `$((1<<2))` the delimiter is followed by `))`, so that `<<` opens
        nothing. Read wrongly, ONE such `<<` made the rest of the line
        invisible to this guard.
        """
        while nr < len(worte):
            wort = worte[nr]
            if trennt(wort):
                # A separator carrying a `)` closes a `$((` — that is a left
                # shift, and the line goes on. Anything else ENDS the command,
                # and a here-document may open in front of any of them:
                # `cat <<EOF | grep x`, `cat <<EOF;`, `cat <<EOF && echo ok`
                # are all legal. The break itself is the clearest case, and it
                # has to come FIRST: `shlex` melts a whole run of punctuation
                # into one word, so the `))` closing a shift arrives as
                # `))\n` — a line that ends, but not right here.
                return wort.startswith("\n") or ")" not in wort
            if _UMLEITWORT.match(wort):
                nr += 2      # the arrow and the file it points at
                continue
            # `2>/dev/null` comes out of the split as `2`, `>`, `/dev/null`:
            # the file descriptor belongs to the redirect, the same way
            # `weg_damit` reads it further down.
            if (
                wort.isdigit()
                and nr + 1 < len(worte)
                and _UMLEITWORT.match(worte[nr + 1])
            ):
                nr += 3
                continue
            return False
        return True

    # Which words stood in quotes — a quoted `"<<"` is text, not an opener.
    # Asked per WORD, because a line can carry both: `echo $((1<<2)); grep
    # "<<" a.md` has an unquoted shift and a quoted literal, and a flag for
    # the whole line would let the literal through on the strength of the
    # shift. Where the second reading cannot be lined up, the line as a
    # whole is asked instead — the older, coarser answer.
    zitiert = _zitierte(befehl, worte)
    kann_heredoc = bool(zitiert) or "<<" in _ZITAT.sub(" ", befehl)

    # The lines as the shell reads them, and the line each word stands on —
    # the split drops the blanks in front of a word, and with a plain `<<`
    # they decide: only a line that is EXACTLY the delimiter ends the body,
    # an indented one is body. `<<-` strips leading tabs first, and only
    # tabs — a blank in front still makes the line body.
    zeilen = _FORTSETZUNG.sub(r"\1", befehl).split("\n")
    zeile_von: list[int] = []
    gezaehlt = 0
    for wort in worte:
        zeile_von.append(gezaehlt)
        gezaehlt += wort.count("\n")

    def eingerueckt(nr: int, strich: bool) -> bool:
        zeile = zeile_von[nr]
        if zeile >= len(zeilen):
            return False
        text = zeilen[zeile].lstrip("\t") if strich else zeilen[zeile]
        return text[:1] in (" ", "\t")

    befehle: list[list[str]] = [[]]
    marke: str | None = None      # the delimiter of an OPEN here-document
    wartet: str | None = None     # its delimiter, while the opener line runs on
    mit_strich = False            # opened with `<<-`, so tabs may stand before it
    nr = 0
    while nr < len(worte):
        wort = worte[nr]
        if marke is not None:
            # Inside a here-document. Its body is text the command WRITES,
            # not commands of its own.
            if (
                wort == marke
                and allein_auf_der_zeile(nr)
                and not eingerueckt(nr, mit_strich)
            ):
                marke = None
            nr += 1
            continue
        klebt = (
            _HEREDOC_KLEBT.match(wort)
            if kann_heredoc and nr not in zitiert
            else None
        )
        if klebt and bis_zeilenende_nur_umleitung(nr + 1):
            # `<<EOF` as ONE word — the hand split's shape. Its body is text
            # exactly as in the ordinary case, and reading it as commands
            # refused every script whose text happens to name the note.
            wartet = klebt.group(1).strip("\"'").lstrip("-")
            mit_strich = "<<-" in wort
            nr += 1
            continue
        # With `punctuation_chars` set, `shlex` counts `-` as a word letter,
        # so `<<- EOF` arrives as three words and the dash stands alone.
        strich = 1 if wort.endswith("<<") and worte[nr + 1 : nr + 2] == ["-"] else 0
        if (
            kann_heredoc
            and nr not in zitiert
            and _HEREDOC.match(wort)
            and nr + 1 + strich < len(worte)
            # A delimiter carrying a closing bracket is none: `$[1<<2]` is
            # the retired spelling of an arithmetic expansion, and `shlex`
            # does not know `[`, so the word after the shift reads as `2]`.
            # Same family as the `)` rule below — a bracket closes a sum.
            and not set(worte[nr + 1 + strich]) & {")", "]"}
            and bis_zeilenende_nur_umleitung(nr + 2 + strich)
        ):
            # Noted, not entered. The BODY starts at the end of this line,
            # and what still stands on it belongs to the line: `cat <<EOF >
            # exe.md` names the note AFTER the delimiter, and jumping into
            # the body here threw exactly that half away.
            # The delimiter stands behind the dash when `shlex` handed the
            # dash over as a word of its own; read in its place, the
            # delimiter was empty and the body never ended.
            wartet = worte[nr + 1 + strich].lstrip("-")
            mit_strich = bool(strich) or worte[nr + 1].startswith("-")
            nr += 2 + strich
            continue
        if trennt(wort):
            befehle.append([])
            if wartet is not None and "\n" in wort:
                marke, wartet = wartet, None
        else:
            befehle[-1].append(wort)
        nr += 1

    for teil in befehle:
        if not teil:
            continue
        # A redirect belongs to no verb: `echo x > exe.md` replaces the file
        # whichever command stands in front of it.
        for nr, wort in enumerate(teil[:-1]):
            if not _writes_into(wort, teil[nr + 1]):
                continue
            if (pfad := getroffen(wege(teil[nr + 1]), mit_ordner=False)) is not None:
                return pfad

        verb = PurePath(teil[0]).name
        # `dd` names its destination in an argument of its own shape. The
        # block list above only stops it from writing onto a DEVICE.
        if verb == "dd":
            for wort in teil[1:]:
                if not wort.startswith("of="):
                    continue
                if (pfad := getroffen(wege(wort[3:]), mit_ordner=False)) is not None:
                    return pfad
        schalter = [w for w in teil[1:] if w.startswith("-") and w != "-"]
        # A redirect word and the word after it belong to the redirect. Left
        # in, `cp neu.md exe.md 2>/dev/null` would be judged by `/dev/null`.
        weg_damit: set[int] = set()
        for nr, wort in enumerate(teil):
            if not _UMLEITWORT.match(wort):
                continue
            weg_damit.update((nr, nr + 1))
            # `2>` comes out of the split as `2` and `>`: the file descriptor
            # in front of the arrow belongs to the redirect too.
            if nr and teil[nr - 1].isdigit():
                weg_damit.add(nr - 1)
        # A destination hidden in a switch: `-t <folder>` eats the word after
        # it, `--target-directory=<folder>` carries it itself.
        zielschalter: str | None = None
        zielwerte = _ZIELWERTE.get(PurePath(teil[0]).name)
        if zielwerte is not None:
            for nr, wort in enumerate(teil):
                folgt = teil[nr + 1] if nr + 1 < len(teil) else None
                if _ist_zielschalter_lang(wort):
                    rest = wort.partition("=")[2]
                elif wort.startswith("-") and not wort.startswith("--"):
                    stelle = _wertstelle(wort[1:], zielwerte)
                    if stelle < 0 or wort[1 + stelle] != "t":
                        continue
                    rest = wort[2 + stelle :]
                else:
                    continue
                # The folder is glued to the switch, or it is the next word.
                if rest:
                    zielschalter = rest
                elif folgt is not None:
                    zielschalter = folgt
                    weg_damit.add(nr + 1)
        operanden = [
            w
            for nr, w in enumerate(teil)
            if nr > 0 and nr not in weg_damit and not w.startswith("-")
        ]
        if not operanden:
            continue
        # `tee -a` appends. That is the `>>` case, and `>>` is untouched here.
        if verb == "tee" and any(s in ("-a", "--append") for s in schalter):
            continue
        # `sed -i`, `sed -i.bak`, `sed --in-place`, `perl -pi -e` rewrite the
        # file they are given instead of printing it. Bundled short switches
        # count: `-pi` is the canonical Perl spelling.
        werte = _wertbuchstaben(verb)
        in_place = verb in _WERTBUCHSTABEN and any(
            s.startswith("--in-place")
            or (
                not s.startswith("--")
                and (stelle := _wertstelle(s[1:], werte + "i")) >= 0
                and s[1 + stelle] == "i"
            )
            for s in schalter
        )
        # Only a recursive `rm` and a `mv` take a whole folder away; for
        # everything else a folder named here is not the note's undoing.
        # `-R` is the documented spelling on this platform and bundles the
        # same way `-rf` does.
        rekursiv = verb == "rm" and any(
            s == "--recursive"
            or (not s.startswith("--") and any(c in "rR" for c in s[1:]))
            for s in schalter
        )
        # With a `-t` the destination is not the last operand, and every
        # operand is a source.
        hat_ziel = verb in _NIMMT_DAS_ZIEL and (
            zielschalter is not None or len(operanden) >= 2
        )
        if verb in _NIMMT_WEG or in_place:
            # Only the SOURCES are taken away. The destination of a `mv` is
            # judged below, where a folder means "moved INTO" — treating it
            # as a folder taken away refused every `mv something .`, the
            # commonest form there is, over a file the line never named.
            quellen = (
                operanden
                if zielschalter is not None or not hat_ziel
                else operanden[:-1]
            )
            alle = [pfad for wort in quellen for pfad in wege(wort)]
            if (pfad := getroffen(
                alle, mit_ordner=rekursiv or verb == "mv"
            )) is not None:
                return pfad
        if hat_ziel:
            quellen = operanden if zielschalter is not None else operanden[:-1]
            ziele = wege(zielschalter if zielschalter is not None else operanden[-1])
            if (pfad := getroffen(ziele, mit_ordner=False)) is not None:
                return pfad
            for ordnerziel in ziele:
                if not ordnerziel.is_dir():
                    continue
                for quelle in quellen:
                    # `rsync quelle/ ziel` copies the CONTENTS of quelle, so
                    # the note is reached by the name of a file INSIDE it.
                    inhalt = verb == "rsync" and quelle.endswith("/")
                    darin: list[Path] = []
                    for qpfad in wege(quelle.rstrip("/") if inhalt else quelle):
                        if inhalt and qpfad.is_dir():
                            try:
                                darin += [ordnerziel / k.name for k in qpfad.iterdir()]
                            except OSError:
                                continue
                        else:
                            darin.append(ordnerziel / qpfad.name)
                    if (pfad := getroffen(darin, mit_ordner=False)) is not None:
                        return pfad
    return None


def _points_outside(word: str) -> bool:
    """Whether a word is shaped like a way out of the shared folders.

    Three shapes, and the first is the system's own rule rather than a list
    of spellings: an absolute path as THIS system writes one (a leading
    slash; on Windows a drive letter or a server name as well, `C:\\…`,
    `\\\\server\\…`), the home folder, or a step up. A drive path on a Mac
    is a plain file name there and is not caught, which is right: it leads
    nowhere on that disk.
    """
    rule = ntpath if WINDOWS else posixpath
    return rule.isabs(word) or word.startswith("~") or ".." in word


def _split_command(command: str) -> list[str]:
    """The command split like its shell would split it, quoted paths in one
    piece, quotes taken off.

    A backslash is an escape only where the shell reads it as one. On
    Windows it is the path separator, and reading it as an escape turned
    the unquoted `C:\\Users\\x` into the harmless-looking word `C:Usersx`
    before anything could judge it. An unbalanced quote raises ValueError,
    as ``shlex.split`` does; the caller falls back to the plain split.
    """
    reader = shlex.shlex(command, posix=True)
    reader.whitespace_split = True
    reader.commenters = ""
    if WINDOWS:
        reader.escape = ""
    return list(reader)


def greift_nach_draussen(
    befehl: str, ordner: list[str], private: Callable[[Path], bool] | None = None
) -> str | None:
    """The path in the command that leaves the shared folders, or None.

    A heuristic on purpose. It reads every path-shaped word out of the
    command and checks whether it still lands inside a shared folder — `~`
    and `..` included, since those are the two ordinary ways out. What it
    cannot see is a path built at runtime (`$(cat file)`); that is the honest
    limit of a tripwire and the reason the share, not this function, is the
    actual boundary.

    With ``private`` the same reading answers another question: which word
    of the command names a private place of the program. Every word then
    counts, a bare name resolved in the first shared folder too, and the
    answer is the first one ``private`` says yes to — inside the shared
    folders or not.
    """
    if not ordner:
        return None
    wurzeln = [Path(o).resolve() for o in ordner]
    wurzel = wurzeln[0]

    # Split like a shell would, so quoted paths stay in one piece. A command
    # that cannot be split (unbalanced quotes) falls back to the raw scan.
    try:
        teile = _split_command(befehl)
    except ValueError:
        teile = befehl.split()

    # Which words this line uses as a search pattern, and which addresses it
    # reaches on the net. Both are read once, up front: the raw scan below
    # works on the untouched string and has to be able to tell whether a
    # match it finds sits inside one of them.
    muster_stellen = _musterworte(teile)
    musterworte = {teile[nr] for nr in muster_stellen if teile[nr]}
    netzstellen = [t.group(0) for t in _NETZ_MUSTER.finditer(befehl)]

    kandidaten: list[str] = []
    for nr, teil in enumerate(teile):
        if teil.startswith("-"):
            continue
        if nr in muster_stellen:
            continue
        # Judged without its quotes: the plain split of a line no shell could
        # split (an unbalanced quote) leaves them on the word, and the raw
        # scan below would still find `/etc` in it but never `C:\Users`.
        if private is not None or _points_outside(teil.strip("\"'")):
            kandidaten.append(teil)
    for treffer in _PFAD_MUSTER.findall(befehl):
        if treffer in kandidaten:
            continue
        # A pattern keeps its slashes even after the split threw the quotes
        # away: `sed 's|/old|/new|g'` leaves `/old` and `/new` lying in the
        # raw string. They belong to the pattern word, not to the line.
        if any(treffer in wort for wort in musterworte):
            continue
        # Same for a URL: `https://beispiel.de/api` is not the folder
        # `/beispiel.de/api`. It is reported by `netzziel` instead.
        if any(treffer in adresse for adresse in netzstellen):
            continue
        # The raw scan cannot see quoting, so a path with spaces comes out
        # cut off at the first blank. If a properly split word carries on
        # where the match stops, the match is that word's stump, not a path
        # of its own.
        if any(t.startswith(treffer) and len(t) > len(treffer) for t in teile):
            continue
        kandidaten.append(treffer)

    for kandidat in kandidaten:
        # An anchor at the edge is a regex, whole and entire: `'/$'` says
        # "line ends in a slash", it does not name the root folder.
        if kandidat.startswith(_ANKER_ANFANG) or kandidat.endswith(_ANKER_ENDE):
            continue
        # A wildcard may not void the word — `rm /tmp/*` DOES reach outside,
        # and dropping it here would be the one thing this change must not
        # do. Only the literal part in front of the wildcard is judged; what
        # is left of `^/(usr|bin)` after the anchor is nothing at all.
        platz = min(
            (kandidat.find(z) for z in _PLATZHALTER if z in kandidat), default=-1
        )
        if platz >= 0:
            kandidat = kandidat[:platz]
            # The stump has to still look like a way out on its own, by the
            # same marks as above — `rm ../*` stays caught by its `..`.
            if private is None and not _points_outside(kandidat):
                continue
        # Strip what the shell would treat as syntax, not as part of the path.
        sauber = kandidat.strip("\"'`;|&()<>")
        if not sauber:
            continue
        # A shared folder with a blank in its name, written without quotes:
        # the split cuts the path at the blank, and the stump looks like an
        # escape. If the command carries the folder's full name, the stump is
        # our own folder cut short, not a path of its own.
        if any(
            " " in str(w) and str(w).startswith(sauber) and str(w) in befehl
            for w in wurzeln
        ):
            continue
        # Redirection targets under /dev are shell plumbing, not a reach:
        # "2>/dev/null" silences a command, it does not touch a file. Writing
        # to a raw device stays caught by the tripwire above.
        #
        # Judged on what was written, not on what it resolves to: Windows has
        # no /dev, so resolving turns the everyday "2>/dev/null" into a
        # real-looking C:\dev\null and every second command would be reported
        # as reaching outside. NUL is what the same plumbing is called there.
        geschrieben = sauber.replace("\\", "/")
        if (
            geschrieben == "/dev/null"
            or geschrieben.startswith(("/dev/std", "/dev/fd/", "/dev/tty"))
            or sauber.upper() == "NUL"
        ):
            continue
        try:
            # `$HOME/...` is a path the shell makes of it; read the same way
            # when the question is which private place the line names.
            ziel = _aufgeloest(os.path.expandvars(sauber) if private else sauber, wurzel)
        except (OSError, RuntimeError):
            continue
        if private is not None:
            if private(ziel):
                return str(ziel)
        elif not liegt_innerhalb(ziel, wurzeln):
            return str(ziel)
    return None


# Which sentence explains this tool's confirmation, and what fills its
# placeholder. The tool knows its own reason; a caller that guessed one for
# everybody wrote "Reaches <a memory entry> — outside the shared folders".
GRUND_SCHLUESSEL = "werkzeug.grund_ausserhalb"

# The same question with the other answer: a URL is not a folder. It is still
# confirmed — only the sentence changes, never whether it is asked.
GRUND_SCHLUESSEL_NETZ = "werkzeug.grund_netz"
GRUND_PLATZHALTER = "pfad"


def aussenpfad(argumente: dict[str, Any], ordner: list[str]) -> str | None:
    """The path this call reaches to outside the shared folders, or None.

    This is both the reason to ask and the answer to "why am I being asked?".
    The prompt shows it, so the decision rests on something visible instead of
    on trust.
    """
    befehl = str(argumente.get("command") or "").strip()
    if not befehl or not ordner:
        return None
    # A folder outside is the weightier fact and wins when both are in the
    # line. The net comes second so that a `curl` with no path at all still
    # answers "yes, ask" — dropping it here would turn a fixed reason into a
    # silently skipped prompt.
    return greift_nach_draussen(befehl, ordner) or netzziel(befehl)


def private_target(
    argumente: dict[str, Any], ordner: list[str], private: Callable[[Path], bool]
) -> str | None:
    """The private place of the program this command names, or None."""
    befehl = str(argumente.get("command") or "").strip()
    if not befehl or not ordner:
        return None
    return greift_nach_draussen(befehl, ordner, private)


def grundschluessel(argumente: dict[str, Any], ordner: list[str]) -> str:
    """Which of the two sentences explains THIS call's confirmation.

    Text only. Whether it is asked was settled by ``braucht_bestaetigung``
    and is not touched here; anything this cannot place falls back to the
    folder sentence, which is the cautious one.
    """
    befehl = str(argumente.get("command") or "").strip()
    if not befehl or not ordner:
        return GRUND_SCHLUESSEL
    if greift_nach_draussen(befehl, ordner) is None and netzziel(befehl):
        return GRUND_SCHLUESSEL_NETZ
    return GRUND_SCHLUESSEL


def braucht_bestaetigung(argumente: dict[str, Any], ordner: list[str]) -> bool:
    """Whether this call has to be confirmed by the user.

    Inside the shared folders: no. Outside: yes. Without any shared folder
    the tool does not run at all, so there is nothing to confirm either.
    """
    return aussenpfad(argumente, ordner) is not None


# The note that stands where a long output was cut; its room is reserved from
# this one wording, so a changed sentence can never push the result past the
# ceiling.
KUERZUNGSNOTIZ = "\n… [{n} additional characters omitted]"


def _kuerzen(text: str, anhang: str = "") -> str:
    """The text, cut to the ceiling — with a note saying what is missing.

    ``anhang`` rides behind the cut and is never cut itself: what the reader
    has to know about the run (the exit code) belongs after the output, and a
    long output must not take it with it.

    The note travels with the output it describes, so it is English like
    every other word the program writes for the model — and it is counted
    INTO the ceiling rather than added on top of it: this same figure is the
    ceiling a tool result is cut to on its way out (``WERKZEUGERGEBNIS_GRENZE``,
    app/api/v1/generierung.py), and a note that made the result one line
    longer was cut off every single time and reached nobody.

    Its figure is what the reader LOSES: measured against the text as it
    came, not against the room the note itself takes. The room the note will
    take is worked out, not written out: its digits are those of the loss,
    and the loss is at most the whole text — so counting them from
    ``len(text)`` can only over-reserve, never overflow.
    """
    grenze = MAX_AUSGABE_ZEICHEN - len(anhang)
    if len(text) <= grenze:
        return text + anhang
    platz = len(KUERZUNGSNOTIZ.format(n="")) + len(str(len(text)))
    behalten = grenze - platz
    return text[:behalten] + KUERZUNGSNOTIZ.format(n=len(text) - behalten) + anhang


# The shell reports its working folder on this marker after every command, so
# a `cd` can persist to the next call without a lasting shell process. Record
# separator: it never appears in ordinary output.
MARKE = "\x1e"


# Windows' command processor cannot echo a control character, so there the
# folder line carries a word instead. Long and unlikely enough that ordinary
# output never starts a line with it.
MARKE_WIN = "__exe_ai_ordner__"


def ordnermarke() -> str:
    """Whichever marker this system's shell can actually write."""
    return MARKE_WIN if WINDOWS else MARKE


def _mit_ordnermarke(befehl: str) -> str:
    """The command, followed by a line that names the folder it ended in.

    Both shells do the same three things: run the command, keep its exit
    code, then write the folder they ended up in. Only the spelling differs.

    Windows needs delayed expansion for the exit code and the folder —
    everything on one line is expanded before the first command runs, so
    %ERRORLEVEL% and %CD% would still hold the values from before, while
    !ERRORLEVEL! and !CD! are read after the command. And not one double
    quote in this part of the line: the command processor is handed the line
    as it stands (``_starten``), and a quote of ours would be the one thing in
    it that the processor could read differently from the way it was written.
    """
    if WINDOWS:
        return (
            f"({befehl}) & set __exe_rc=!ERRORLEVEL!& "
            f"echo {MARKE_WIN}!CD!& exit /b !__exe_rc!"
        )
    return (
        "{ " + befehl + "\n} ; __exe_rc=$? ; "
        "printf '\\n\\036%s' \"$PWD\" ; exit $__exe_rc"
    )


async def _mitlesen(strom, lauf, sammlung: list[str], name: str) -> str | None:
    """Reads one output stream line by line. Returns the folder marker if it
    came past — that is the last line of stdout and belongs to nobody else."""
    ordner_danach: str | None = None
    # The marker is printed on a line of its own, so it brings an empty line
    # with it that the command never wrote. Empty lines are therefore held
    # back until something follows them; the last one before the marker is
    # ours and goes.
    zurueckgehalten = 0

    def ausgeben(text: str) -> None:
        sammlung.append(text)
        if lauf is not None:
            hintergrund.laeufe.zeile(lauf, text, name)

    # True while consecutive reads keep running into the same over-long line:
    # asyncio refuses it once per bufferful, and one note for the line is the
    # message — one per refusal would be the flood the line already is.
    zu_lang = False

    while True:
        try:
            roh = await strom.readline()
        except ValueError:
            for _ in range(zurueckgehalten):
                ausgeben("")
            zurueckgehalten = 0
            if not zu_lang:
                ausgeben(HINWEIS_ZEILE_ZU_LANG)
            zu_lang = True
            continue
        zu_lang = False
        if not roh:
            for _ in range(zurueckgehalten):
                ausgeben("")
            return ordner_danach
        text = roh.decode("utf-8", errors="replace").rstrip("\r\n")
        marke = ordnermarke()
        if text.startswith(marke):
            ordner_danach = text[len(marke) :]
            zurueckgehalten = max(0, zurueckgehalten - 1)
            continue
        if not text:
            zurueckgehalten += 1
            continue
        for _ in range(zurueckgehalten):
            ausgeben("")
        zurueckgehalten = 0
        ausgeben(text)


def _antwort_bauen(ausgabe: list[str], fehler: list[str], code: int | None) -> str:
    teile: list[str] = []
    if ausgabe:
        teile.append("\n".join(ausgabe).rstrip())
    if fehler:
        teile.append(("stderr:\n" if ausgabe else "") + "\n".join(fehler).rstrip())
    rumpf = "\n".join(teile)
    # The exit code is not output — it is what the reader has to know about
    # the run, so it rides BEHIND the cut instead of standing inside the text
    # being cut (a long output took it with it).
    anhang = f"\n[exit code {code}]" if code not in (0, None) else ""
    if not rumpf:
        # A successful `mkdir` says nothing at all. Silence would read like a
        # failure to the model, so say plainly that it worked.
        return anhang.lstrip("\n") or "(completed without output)"
    # Cut ONCE, on the whole answer. Cut per part, two parts that each just
    # fit are a full answer over the ceiling when they are joined — and the
    # caller cuts again at exactly that figure, so the note itself would go
    # over the edge and arrive torn.
    return _kuerzen(rumpf, anhang)


# The companion tasks of background runs. Held on purpose, for the reason
# ``EventBus.veroeffentlichen_ohne_warten`` spells out (app/events.py): the
# loop keeps only a weak reference to a task, so one that nobody holds may be
# collected mid-flight and simply never finish.
#
# It matters more here than almost anywhere, because ``_begleiten`` is the
# ONLY path to ``laeufe.beenden`` and ``laeufe.abschluss`` for a background
# run: lose it and the run stands at LAEUFT for the life of the process, no
# report is ever written into the chat, and nothing wakes the model
# (app/hintergrundmeldung.py, app/hintergrundwecken.py) — after the tool has
# already promised the user "the result appears in the terminal".
#
# Measured on the shipped interpreter: a task of this shape survives a forced
# collection today, because the loop's selector holds the pipe transport, the
# transport the stream reader, and the reader the future this task is waiting
# on. That is an implementation detail, not a promise — asyncio's own
# documentation says the reference is ours to keep — so it is kept.
_begleiter: set[asyncio.Task] = set()


def _begleiter_loslassen(lauf, aufgabe: asyncio.Task) -> None:
    """Lets a finished companion go, and refuses to let it die in silence.

    Two jobs in one callback because the second only exists once the first
    does: an unheld task that raises is reported by asyncio itself, but only
    as "Task exception was never retrieved" at some later collection — a line
    with no run number, no command and no chat on it. A held task whose
    exception nobody retrieves logs exactly the same thing. So it is
    retrieved here, where the run is still in hand to name.

    And a failure here is not academic. The one that was measured was a
    line longer than the stream reader's own buffer: ``readline`` raised
    ``ValueError``, and everything after it in ``_begleiten`` was skipped,
    ``beenden`` included. ``_mitlesen`` answers that one itself now —
    this stays for every other way the companion can die,
    which is the reason it was written as a net and not as a cure.

    So the state is closed here instead: a run that ends in error is what the
    terminal window draws from ``lauf_ende``, and a spinner that never stops
    is what it drew before. Only ``beenden``, deliberately not ``abschluss``:
    that one writes the command's OUTPUT into the chat and wakes the model on
    it, and there is no output — the companion never got that far.

    Guarded on LAEUFT because ``_begleiten`` can also fail AFTER it closed the
    run (the ``abschluss`` handler is the last thing it calls), and a run that
    already carries its exit code must not be overwritten with a failure. The
    kill switch reaches the same guard: ``alle_toeten`` sets FEHLER itself and
    marks the run forgotten before its companion ever wakes.

    And the process goes first, before the record is closed. Nobody is
    reading its output any more, so what is left of it is a command running
    unwatched in the folder the user shared — the very "walking away"
    ``gruppe_toeten`` was written against. The order is not cosmetic:
    ``beenden`` clears ``lauf.prozess``, and that field is the only place a
    live process is reachable from, so a run closed first is a process the
    kill switch can no longer find at shutdown.
    """
    # Already let go of by `aufgaben.halten` when this runs.
    # Cancelled is not failed, and it carries nothing to retrieve.
    if aufgabe.cancelled() or aufgabe.exception() is None:
        return
    log.error(
        "The companion of background run #%s in chat %s failed: %s",
        lauf.nummer if lauf is not None else "?",
        lauf.chat_id if lauf is not None else "?",
        lauf.befehl if lauf is not None else "?",
        exc_info=aufgabe.exception(),
    )
    if lauf is None or lauf.zustand != hintergrund.LAEUFT:
        return
    if lauf.prozess is not None:
        try:
            lauf.prozess.kill()
        except Exception:  # noqa: BLE001 - a process already gone is not a second fault
            log.debug("The process of run #%s was gone", lauf.nummer)
    hintergrund.laeufe.beenden(lauf, None, zustand=hintergrund.FEHLER)


async def ausfuehren(
    argumente: dict[str, Any], ordner: list[str], chat_id: str | None = None,
    zeitgrenze: int | None = None, hintergrund_erlaubt: bool = True,
    data_dir: Path | str | None = None, abbruch: asyncio.Event | None = None,
) -> str:
    """Runs the command and returns output the way a terminal would show it.

    ``abbruch`` is the stop signal of the answer or the job that calls
    (app/generationen.py): a command in the foreground ends with it, tree
    and all, and its result says so (``STOPPED_BY_USER``). A run in the
    background is not tied to it — it belongs to the terminal and reports
    for itself when it is done.

    ``data_dir`` is the program's data folder: it tells a chat's own folder
    apart, which is made here when the command runs and it is missing
    (``grenzen.prepare_folders``).

    ``chat_id`` is what makes a run belong somewhere: the remembered folder,
    the live lines in the terminal window and the message a background run
    leaves behind are all tied to the chat, never to the model's arguments.

    ``zeitgrenze`` is how many seconds a foreground command may run before
    it is stopped — resolved by the caller from the settings cascade
    (app/befehlszeitwahl.py). ``None`` means the shipped default, so every
    caller that says nothing gets exactly the old behaviour.

    ``hintergrund_erlaubt`` is whether ``background=true`` may be honoured
    here. A job run passes ``False``: its background results have no chat to
    land in, so the run would start, finish, and report to nobody — the
    agent then waits forever on "run #7". Refusing plainly, with the actual
    time limit in the answer, is what the model can act on. The refusal is
    a normal tool result, not an error: the tool answered, and the answer
    says what to do instead.
    """
    grenze = zeitgrenze if zeitgrenze and zeitgrenze >= 1 else ZEITGRENZE_SEKUNDEN
    befehl = str(argumente.get("command") or "").strip()
    if not befehl:
        raise ShellVerboten("No command provided.")
    if not ordner:
        raise ShellVerboten(
            "No working folder is shared with this chat. Ask the user to share one using the "
            "folder icon in the input bar. Commands cannot run until then."
        )

    if (grund := blockiert(befehl)) is not None:
        log.warning("Shell command refused (%s): %s", grund, befehl)
        raise ShellVerboten(
            f"The command was rejected because it matches a blocked pattern ({grund}). This "
            "restriction applies regardless of permissions."
        )

    if (grund := prepare_folders(ordner, data_dir)) is not None:
        raise ShellVerboten(grund)
    wurzel = ordnergedaechtnis.start_ordner(chat_id, ordner)

    # After the folder is known, because a bare `exe.md` means the folder the
    # chat is standing in. Refused as an ordinary tool result with a reason
    # and the tool that CAN do the job, the same shape the write tool uses
    # for the same file (app/tools/datei_schreiben.py).
    if (notiz := notiz_in_gefahr(befehl, wurzel, ordner)) is not None:
        log.warning("Shell command refused (folder note): %s", befehl)
        raise ShellVerboten(
            f"'{notiz}' contains the folder's own notes. It cannot be removed or overwritten "
            "here, because that would discard its contents. Use edit_file to change a passage "
            "or write to a different file."
        )

    im_hintergrund = bool(argumente.get("background"))
    if im_hintergrund and not hintergrund_erlaubt:
        # Before anything starts: a run that cannot deliver must not exist.
        return (
            "Background execution is unavailable in a job. Run the command in the foreground. "
            f"The limit for a single command is {int(grenze)} seconds."
        )
    lauf = (
        hintergrund.laeufe.anlegen(chat_id, befehl, im_hintergrund, folder=str(wurzel))
        if chat_id
        else None
    )

    log.info("Shell: %s (in %s)", befehl, wurzel)
    prozess = await _starten(befehl, wurzel)
    if lauf is not None:
        # As a group, not as a single process: what the record is FOR is the
        # kill switch when the service goes down, and that switch has to reach
        # the command, not only the shell around it.
        lauf.prozess = Prozessgruppe(prozess)

    if im_hintergrund:
        # Deliberately not awaited: the call returns now, the run reports for
        # itself when it is done. Not let go of, though — the reference lives
        # in `_begleiter` until the task is over, and the callback that drops
        # it is also the one that looks at how it ended.
        nummer = lauf.nummer if lauf else 1
        aufgaben.halten(
            _begleiten(
                prozess,
                lauf,
                chat_id,
                ordner,
                hintergrund.HINTERGRUND_GRENZE_SEKUNDEN,
            ),
            name=f"begleiter-{nummer}",
            menge=_begleiter,
            bei_ende=partial(_begleiter_loslassen, lauf),
        )
        return (
            f"Started in the background as run #{nummer}. The result will appear in the "
            "terminal when complete."
        )

    ergebnis, abgelaufen = await _begleiten(
        prozess, lauf, chat_id, ordner, grenze, abbruch=abbruch
    )
    # A stop that ran into the time limit is still the user's stop, and the
    # answer says so rather than advising a longer run.
    if abgelaufen and not (lauf is not None and lauf.stop_requested):
        rat = (
            "If the command is expected to take this long, start it with background set to "
            "true."
            if hintergrund_erlaubt
            # A job has no background to offer — the honest advice is the
            # setting that governs this limit, not a door that is shut here.
            else "For longer commands, increase the time limit in the settings or the agent's "
                 "max_command_seconds."
        )
        return (
            f"Stopped after {int(grenze)} seconds because the command was still running.\n"
            + rat
        )
    return ergebnis


def gruppe_toeten(prozess) -> None:
    """Kills a process AND everything it started, not just the process.

    Killing the process alone is what the time limit used to do, and it is
    not a stop: because of the folder marker the shell can never optimise
    itself away, so the command a person actually asked for is ALWAYS a
    child of that shell. ``prozess.kill()`` ends the shell, the build or the
    rsync underneath it goes on running with the user's full rights and keeps
    writing into the shared folder — while the chat says "Stopped after N
    seconds". Measured, not assumed.

    ``killpg`` on the process id itself, not on ``os.getpgid(pid)``. Both name
    the same group — ``start_new_session`` makes the process its own group
    leader, so the group id IS the process id — but only one of the two still
    works in the case that matters: a script whose child holds the output pipe
    open while the script itself has already ended and been reaped. Asking
    ``getpgid`` for a reaped process raises ``ProcessLookupError``, the old
    fallback ``prozess.kill()`` then went to the same dead process and raised
    nothing at all, and the child that was the whole problem lived on. The
    group, meanwhile, exists as long as one member does. Measured: with
    ``getpgid`` the child survived, with the process id it dies.

    Windows has no process groups of this shape and no ``killpg``, but it has
    ``taskkill /T``, which walks the children itself — and it is needed for
    the same reason: the shell is the real command's parent there too, so
    ending the shell alone leaves the build running. ``/F`` because a console
    process without a window ignores the polite request. The single kill
    stays behind it as the last resort.
    """
    if hasattr(os, "killpg") and gruppe_ist_noch_unsere(prozess):
        try:
            os.killpg(prozess.pid, signal.SIGKILL)
            return
        except (ProcessLookupError, PermissionError, OSError):
            pass
    elif WINDOWS:
        # In a thread of its own, and not waited for: taskkill walks the
        # tree and takes its time, and this is called from the event loop —
        # the time limit, a stop, a cancel — where it held every stream and
        # request of the service for as long as it took. The callers do not
        # need its answer; they watch the process end (``ernten``,
        # ``prozessstopp.stop_watched``), which is the one thing that
        # matters. Not a daemon thread: a shutdown that kills the runs
        # (app/main.py) then still waits for the kill to land.
        threading.Thread(
            target=_taskkill, args=(prozess,), name=f"taskkill-{prozess.pid}"
        ).start()
        return
    try:
        prozess.kill()
    except (ProcessLookupError, OSError):
        pass


def _taskkill(prozess) -> None:
    """``taskkill /T /F`` on the process, and the single kill as the last
    resort when it could not run or found nothing to end — the same two
    steps the event loop used to take in place."""
    try:
        ergebnis = subprocess.run(
            ["taskkill", "/T", "/F", "/PID", str(prozess.pid)],
            check=False,
            capture_output=True,
            **no_window(),
        )
        if ergebnis.returncode == 0:
            return
    except (OSError, ValueError):
        pass
    try:
        prozess.kill()
    except (ProcessLookupError, OSError):
        pass


def gruppe_ist_noch_unsere(prozess) -> bool:
    """Whether that group number still belongs to the process we started.

    The guard in front of ``killpg``, and it exists because the number is only
    borrowed. A process group id stays reserved while the group has a member —
    that is what makes killing by the reaped leader's id right in the first
    place. The moment the LAST member is gone the number is free again, and
    after some hundred thousand process starts the system hands it to somebody
    else. Send SIGKILL then, with the user's full rights, and it lands on a
    stranger's whole group: a terminal's foreground group, or one of this
    program's own servers, which run in sessions of their own.

    Rare, and catastrophic when it happens — a kill that arrives hours after
    the start (a backup's time limit, the shutdown switch) is exactly the case
    where the group has had time to empty out.

    Three questions, and only the third one costs anything:

    * **A number that could never be ours.** ``killpg(0)`` is "my own group" —
      the service, this very process, and every command it is currently
      running. ``killpg(1)`` is init's. Neither can be a child of ours, and
      neither may be signalled by accident.
    * **Has the leader been reaped?** While it has not — alive, or a zombie
      not yet collected — the id is occupied by our own process and the number
      cannot have moved on. Nothing to check.
    * **Does a LIVE process hold that number?** Once our leader is reaped, no
      process of ours can carry that id any more. So if some process does, it
      is somebody else's, and the number was recycled — which also means our
      group had run empty and there is nothing of ours left in it to kill.
      Refused. If nothing holds it, the only members that number can still
      reach are the children we started ourselves (a stranger's group would
      need a leader with that id), and the kill goes ahead — which is the
      case the time limit was fixed for and must keep working.
    """
    pid = getattr(prozess, "pid", None)
    if not isinstance(pid, int) or pid <= 1:
        return False
    if getattr(prozess, "returncode", None) is None:
        return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    except OSError:
        # It exists and belongs to someone we may not signal — a stranger for
        # certain.
        pass
    log.warning(
        "Process group %s not killed: the number now belongs to a "
        "foreign process",
        pid,
        extra={"ereignis": "prozessgruppe_fremd", "pid": pid},
    )
    return False


# How long ``ernten`` waits for an exit status that has been signalled but not
# yet collected. Never reached in practice — a SIGKILL is collected within
# milliseconds — it is the ceiling for the case where it is not.
ERNTE_SEKUNDEN = 5.0


async def ernten(prozess, frist: float = ERNTE_SEKUNDEN) -> int | None:
    """The exit status of a killed process, without waiting on its pipes.

    ``await prozess.wait()`` is the obvious line here and it is a trap. In
    asyncio a waiter registered by ``wait()`` is woken by
    ``_call_connection_lost``, and that runs only once EVERY pipe of the
    process is closed — ``_process_exited``, which knows the status, wakes
    nobody. A child that escaped the group (a script calling ``setsid``) holds
    the output pipe open, and for a service it holds it open forever. So the
    run hung after the kill: the job stayed on "running", the schedule's
    "one at a time" rule blocked every following due time, and the stop button
    reached nothing. Measured on Python 3.11.15: ``returncode`` is ``-9`` and
    ``wait()`` never returns.

    ``wait()`` returns straight away when the status is ALREADY known — the
    whole difference is the moment of asking. So this waits for the status
    itself to appear rather than for a waiter nobody will wake: a short poll,
    because there is nothing in asyncio to be notified by here. It costs a
    handful of milliseconds after a kill and answers the moment the status is
    in, instead of never.

    ``None`` back means the status did not arrive within ``frist`` — the
    caller books what it books for a killed run either way.

    Then the pipes are let go of. Whatever is still in them was abandoned one
    line earlier — every caller of this has just killed the process and
    dropped the read — and holding them costs two file descriptors and the
    whole transport for as long as the escaped child lives, which for a
    service is forever. It also leaves a torn-down loop to trip over them
    later: ``Event loop is closed`` out of a destructor, at shutdown, with no
    hint of where it came from.
    """
    if prozess.returncode is None:
        schleife = asyncio.get_running_loop()
        ende = schleife.time() + frist
        while prozess.returncode is None and schleife.time() < ende:
            await asyncio.sleep(0.02)
    _pipes_loslassen(prozess)
    return prozess.returncode


def _pipes_loslassen(prozess) -> None:
    """Closes the process's pipes, ours being the read ends.

    Reaches for ``_transport`` because asyncio offers no other way to say
    "done with this process" — ``Process`` hands out the streams but nothing
    that closes them. Guarded on every side rather than trusted: a missing
    attribute or a raise here must never be what ends a run.
    """
    transport = getattr(prozess, "_transport", None)
    if transport is None:
        return
    try:
        transport.close()
    except Exception:  # noqa: BLE001 - releasing pipes may not cost a run
        log.debug("Pipes of %s could not be closed", prozess.pid, exc_info=True)


class Prozessgruppe:
    """A command's process, seen as the whole tree it started.

    Handed to the run record (app/tools/hintergrund.py) in place of the bare
    process, because the kill switch there — "nothing outlives the program" —
    calls ``kill()`` on whatever it finds and would otherwise take down the
    shell and leave the build. Same reasoning as the time limit above, at the
    other end of the run's life.

    ``beim_toeten`` is how the run itself gets to hear about that switch. The
    switch is the only caller of ``kill()`` that is not the run's own doing,
    and a run that does not notice it books its own killing as an ordinary
    failure — see app/skriptlauf.py, where a restart during the nightly backup
    used to cost the schedule a failed run and an announcement to match.
    Called once the kill is on its way — on Windows taskkill lands a moment
    later, in its own thread (``gruppe_toeten``) — on the event loop's own
    thread (the shutdown runs there), so an ``asyncio.Event.set`` is a valid
    thing to hand in.
    """

    def __init__(self, prozess, beim_toeten=None) -> None:
        self.prozess = prozess
        self._beim_toeten = beim_toeten

    @property
    def pid(self) -> int:
        return self.prozess.pid

    def kill(self) -> None:
        gruppe_toeten(self.prozess)
        if self._beim_toeten is not None:
            self._beim_toeten()

    def terminate(self) -> None:
        """The polite half of ``kill``: a term signal to the whole group,
        behind the same guard, so a program may still clean up after
        itself. Windows has no polite signal for a tree — ``taskkill /T``
        needs ``/F`` for a console process — so there it is the kill."""
        if hasattr(os, "killpg"):
            if gruppe_ist_noch_unsere(self.prozess):
                try:
                    os.killpg(self.prozess.pid, signal.SIGTERM)
                except (ProcessLookupError, PermissionError, OSError):
                    pass
            return
        self.kill()


# What asyncio's own stream readers keep as the limit of one line; written out
# because the constant is private there.
_STREAM_LIMIT = 2**16


async def _process_from_line(line: str, **popen_arguments):
    """A process started from one command-line string, with no shell around it.

    asyncio knows two ways to start a process: a list (joined by the C
    runtime's quoting) and a shell (which wraps the string in a command
    processor of its own). Neither hands a string to the system as it is, and
    on Windows that is what the command line needs. The pipe transport is the
    same one ``create_subprocess_exec`` uses; only the program is given as the
    whole line, so Popen takes it unchanged as the command line.

    The transport's start is a private method of the event loop. The program
    ships its own interpreter, so it changes only with a deliberate upgrade,
    and a test pins the signature it is called with.
    """
    loop = asyncio.get_running_loop()
    protocol = asyncio.subprocess.SubprocessStreamProtocol(limit=_STREAM_LIMIT, loop=loop)
    transport = await loop._make_subprocess_transport(  # noqa: SLF001
        protocol, line, False, None, asyncio.subprocess.PIPE, asyncio.subprocess.PIPE, 0,
        **popen_arguments,
    )
    return asyncio.subprocess.Process(transport, protocol, loop)


async def _starten(befehl: str, wurzel: Path):
    """The process for one command.

    The shell is the point: pipes and redirection are half of file work.

    The USER'S shell, not /bin/sh: the model writes commands for the shell
    people actually have, and asked to write "HALLO" it produced
    `echo -n HALLO`. Under /bin/sh the built-in `echo` does not know -n and
    wrote "-n HALLO" into the file. Whatever the user would get in their own
    terminal, they get here.

    Windows has no /bin/sh, and its command processor reads /c where a POSIX
    shell reads -c. Handed the wrong switch it ignores the command entirely
    and opens an interactive session instead: the caller then gets a version
    banner back and nothing was ever run. COMSPEC names whichever processor
    the system actually uses, and /v:on turns on the delayed expansion the
    folder marker needs to read the exit code after the command, not before.

    PYTHONUNBUFFERED keeps a python one-liner from withholding its output.
    """
    environment = {**os.environ, "PYTHONUNBUFFERED": "1"}
    if WINDOWS:
        # As ONE STRING, never as a list of arguments, and with no shell
        # around it. A list is joined into a command line by the rules of the
        # MS C runtime, which writes every double quote as \" — and cmd.exe
        # does not read \": the folder marker arrived as
        # \"__exe_ai_ordner__\"C:\…, the exit code was lost and a cd
        # forgotten (measured in a Windows VM). Handed to asyncio's shell
        # start the string would be wrapped a second time, as
        # `cmd.exe /c "cmd.exe /v:on /c "…""`, and the OUTER cmd reads the
        # user's quotes the other way round: a `<` or `>` inside "…" stands
        # outside them for it and becomes a redirection, so the file was
        # never written. Here the string goes to the system unchanged, and
        # the one cmd strips its own outer pair by its own rule for /c: more
        # than two quotes, or a special character between them, and the
        # first and the last quote go.
        # Delayed expansion is a switch of cmd itself, so the string starts
        # that cmd with /v:on, and the command inside arrives as it was
        # written, quotes and all.
        programm = os.environ.get("COMSPEC") or "cmd.exe"
        return await _process_from_line(
            f'{programm} /v:on /c "{_mit_ordnermarke(befehl)}"',
            cwd=str(wurzel),
            env=environment,
            **no_window(),
        )

    return await asyncio.create_subprocess_exec(
        os.environ.get("SHELL") or "/bin/sh",
        "-c",
        _mit_ordnermarke(befehl),
        cwd=str(wurzel),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=environment,
        # Its own session, so the whole tree can be taken down at once
        # (gruppe_toeten above). Without it the shell shares the service's own
        # process group and there is no group to kill that would not take the
        # service with it — which is why the time limit only ever killed the
        # shell, and why the command underneath it survived every "Stopped
        # after N seconds" the chat ever printed.
        start_new_session=True,
        **no_window(),
    )


# What the model reads when somebody pressed stop on a command's run in the
# terminal.
STOPPED_BY_USER = "The user stopped this command before it finished."


async def _begleiten(
    prozess,
    lauf,
    chat_id: str | None,
    ordner: list[str],
    grenze: float,
    abbruch: asyncio.Event | None = None,
) -> tuple[str, bool]:
    """Follows a running command to its end. Returns (answer, timed out).

    Both kinds go through here: the foreground call awaits it, a background
    run leaves it to itself and lets the result find its way into the chat.

    ``abbruch`` is the stop signal of the answer or the job the command
    belongs to. Set while the command runs, the command ends with its whole
    tree — the way the time limit and the stop in the terminal end it — and
    the run reads "stopped". Only the foreground call hands it in.
    """
    ausgabe: list[str] = []
    fehler: list[str] = []
    abgelaufen = False
    cancelled = False
    reading = asyncio.gather(
        _mitlesen(prozess.stdout, lauf, ausgabe, "stdout"),
        _mitlesen(prozess.stderr, lauf, fehler, "stderr"),
    )
    # Waited for BESIDE the output, not instead of it: asyncio.wait knows
    # several things at once where wait_for knows one (app/skriptlauf.py
    # waits for a script the same way). The waiter is a task of the
    # program's own holder (app/aufgaben.py), as every task here is.
    stop = (
        aufgaben.halten(abbruch.wait(), name=f"run_command-stop-{prozess.pid}")
        if abbruch is not None
        else None
    )
    pending: list[asyncio.Future[Any]] = [reading]
    if stop is not None:
        pending.append(stop)
    try:
        done, _ = await asyncio.wait(
            pending, timeout=grenze, return_when=asyncio.FIRST_COMPLETED
        )
    except BaseException:
        # The task awaiting this was cancelled (a loop tearing down): the
        # read is let go of, as wait_for let go of it — a read left on the
        # pipes would outlive its run.
        reading.cancel()
        raise
    finally:
        if stop is not None and not stop.done():
            stop.cancel()
    if reading in done:
        # The output is complete, so the command has ended — also when the
        # stop came in the same moment: a command that finished as the stop
        # arrived finished.
        ordner_danach, _ = reading.result()
        await prozess.wait()
        ordnergedaechtnis.merken(chat_id, ordner_danach or "", ordner)
    else:
        # Kill, don't just walk away: an abandoned process keeps writing into
        # the folder the user shared. The whole group, not the shell alone —
        # the command is always a child of that shell, so killing the shell
        # is exactly the "walking away" this line was written against.
        cancelled = stop is not None and stop in done
        abgelaufen = not cancelled
        if cancelled and lauf is not None:
            # The run reads "stopped", as it does for the stop in the
            # terminal: the answer's stop is the user's stop — and it is in
            # the log as that one is (hintergrund.Laeufe.stop).
            lauf.stop_requested = True
            log.info(
                "Run #%s in chat %s stopped with its answer: %s",
                lauf.nummer, chat_id, lauf.befehl,
            )
        gruppe_toeten(prozess)
        # The read is let go of by hand, the way wait_for let it go at the
        # time limit: a child that escaped the group holds the output pipe,
        # and a read left waiting on it would keep the run's buffers alive
        # for the rest of the program's life.
        reading.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await reading
        # Not ``prozess.wait()``: a child that escaped the group holds the
        # output pipe, and a waiter registered here would then never be woken
        # — the chat would hang on the tool call for good. ``ernten`` takes
        # the exit status that is already there. See its docstring.
        await ernten(prozess)

    if abgelaufen:
        antwort = (
            f"Stopped after {int(grenze)} seconds because the command was still running."
        )
    else:
        antwort = _antwort_bauen(ausgabe, fehler, prozess.returncode)
    # Said first, so the exit code of a killed shell below it is not read as
    # the command failing by itself — and only where the stop cut it short:
    # a command that finished cleanly as the button was pressed finished.
    if cancelled or (
        lauf is not None and lauf.stop_requested and (abgelaufen or prozess.returncode != 0)
    ):
        antwort = f"{STOPPED_BY_USER}\n{antwort}"

    if lauf is not None:
        hintergrund.laeufe.beenden(
            lauf, None if abgelaufen or cancelled else prozess.returncode
        )
        if lauf.hintergrund and hintergrund.laeufe.abschluss is not None:
            hintergrund.laeufe.abschluss(lauf, antwort)
    return antwort, abgelaufen
