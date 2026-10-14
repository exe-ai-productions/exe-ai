"""The front matter of a skill or an agent file: where it ends, and how a text
value is written into it.

Three readers (skills, agents, the agent form) and two writers (the skill
file, the agent form) all deal with the same shape — a header between two
``---`` lines, then the body. Each of them used to cut at the first three
hyphens it found, so a value like ``A---B`` ended the header in the middle of
a line. The cut and the escape of a value stand here once.
"""

from __future__ import annotations

import json
import re

MARKER = "---"

# What a double-quoted YAML scalar has to carry as an escape although JSON
# writes it raw: the characters YAML does not accept in a file at all (DEL,
# the C1 controls except NEL, the two non-characters), and a run of three
# hyphens, which a reader of an older program version still takes for the end
# of the header wherever it stands. A lone surrogate is deliberately NOT
# escaped: read back, it would be a text no response can encode as UTF-8, and
# writing it raw fails the way it always has.
_YAML_ESCAPE = re.compile(r"[\x7f-\x84\x86-\x9f￾￿]|-{3,}")


class FrontMatterError(ValueError):
    """The text has no header to read. Each caller turns the two kinds below
    into the refusal of its own kind of file."""


class NoFrontMatter(FrontMatterError):
    """The first line is not the marker."""


class NoClosingLine(FrontMatterError):
    """No later line is the marker."""


def split(text: str) -> tuple[str, str]:
    """The header and the body of a file text, both raw. Raises
    ``NoFrontMatter`` or ``NoClosingLine`` where there is no header.

    The header starts with the first line, which holds the marker alone, and
    ends at the next line that holds the marker alone. White space at the end
    of such a line and both line endings (``\\n``, ``\\r\\n``) do not count;
    three hyphens inside a value end nothing. A byte order mark in front of
    the first line is not part of the text.

    What comes back is cut exactly where the two markers stand: the header is
    everything after the opening marker's three characters up to the closing
    marker, the body everything after the closing marker's three characters.
    A caller that writes the file back puts ``---`` in front of the header
    and in front of the body and loses nothing.
    """
    if text.startswith("﻿"):
        text = text[1:]
    first_end = text.find("\n")
    first = text if first_end < 0 else text[:first_end]
    if first.rstrip() != MARKER:
        raise NoFrontMatter("the first line is not the marker")
    position = len(text) if first_end < 0 else first_end + 1
    while position < len(text):
        line_end = text.find("\n", position)
        line = text[position:] if line_end < 0 else text[position:line_end]
        if line.rstrip() == MARKER:
            return text[len(MARKER):position], text[position + len(MARKER):]
        if line_end < 0:
            break
        position = line_end + 1
    raise NoClosingLine("no later line is the marker")


def _escape(match: re.Match[str]) -> str:
    return "".join(f"\\u{ord(char):04x}" for char in match.group())


def yaml_quoted(text: str) -> str:
    """``text`` as a double-quoted YAML scalar that survives every character.

    A JSON string is a valid double-quoted YAML scalar, so a colon, a ``#``
    or a word like ``yes`` reads back exactly as it was written. What JSON
    leaves raw and YAML or the header cut cannot take goes in as an escape.
    """
    return _YAML_ESCAPE.sub(_escape, json.dumps(text, ensure_ascii=False))
