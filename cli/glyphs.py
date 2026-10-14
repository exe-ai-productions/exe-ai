"""The signs the client draws: who speaks, what a tool did, how something
stands, the cells of the context bar — and the frames of the spinner.

Every sign is asked for by its name, so a module never writes a character
of its own. Which character a name stands for depends on what the output
can carry: plain Unicode characters where it speaks UTF-8, ASCII everywhere
else — so nothing is ever written that the terminal would show as a
question mark. No sign needs a font of its own. Where the user has said
that the terminal's font is a Nerd Font, the signs that have an icon there
use it instead.
"""

from __future__ import annotations

import codecs
import sys

from rich.console import OverflowMethod

# How long one frame of the spinner stays, in seconds.
SPINNER_INTERVAL = 0.1

# A star that swells from a point and shrinks back — and, for every output
# that does not speak UTF-8, the four strokes of a turning line.
_STAR_FRAMES = ("·", "✢", "✦", "✶", "✸", "✹", "✺", "✹", "✸", "✶", "✦", "✢")
_ASCII_FRAMES = ("-", "\\", "|", "/")

# Each sign as (Unicode, ASCII, Nerd Font). An empty third entry means the
# sign has no icon of its own and keeps its Unicode character.
_GLYPHS: dict[str, tuple[str, str, str]] = {
    # In front of the input field.
    "prompt": ("❯", ">", ""),
    # In front of what the user sent — the same mark the line was typed at.
    "user": ("❯", ">", ""),
    # The character the two lines around the input field are drawn with.
    "rule": ("─", "-", ""),
    "assistant": ("✦", "*", ""),
    "thinking": ("✧", "~", ""),
    # A tool the catalogue below has no sign of its own for.
    "tool": ("▸", "+", ""),
    "ok": ("✓", "ok", ""),
    "error": ("✗", "!", ""),
    "warning": ("▲", "!", ""),
    "waiting": ("◌", "...", ""),
    "connected": ("●", "o", ""),
    "disconnected": ("○", "x", ""),
    # In front of the name of the entry of a selection that is in use.
    "in_use": ("●", "*", ""),
    # Between two parts of one line.
    "separator": ("·", "|", ""),
    # In front of an item of a list, and down the side of a quotation.
    "bullet": ("•", "*", ""),
    "quote": ("▌", "|", ""),
    # Down the side of a block of code.
    "gutter": ("│", "|", ""),
    # Where something was cut short.
    "more": ("…", "...", ""),
    # Between what a value was and what it is now.
    "arrow": ("→", "->", ""),
    # Behind how often a model was downloaded.
    "download": ("↓", "v", ""),
    # In front of the two status lines below the input field: the one about
    # the chat, and the one about how the next message will be answered.
    "line_chat": ("◆", "*", ""),
    "line_mode": ("▶▶", ">>", ""),
    # The cells of the context bar in the third status line: a full block
    # for one that is used, a shaded block of the same height for one that
    # is still free — so the bar shows as a bar while nothing is used yet.
    "bar_used": ("█", "#", ""),
    "bar_free": ("░", ".", ""),
}

# The signs of the tools as (Unicode, Nerd Font), named after what they show.
_TOOL_SIGNS: dict[str, tuple[str, str]] = {
    "globe": ("⊕", ""),
    "shell": ("$", ""),
    "page": ("▤", ""),
    "search": ("⌕", ""),
    "pencil": ("✎", ""),
    "edit": ("✐", ""),
    "folder": ("▣", ""),
    "question": ("?", ""),
    "picture": ("◩", ""),
    "cutout": ("◪", ""),
    "memory": ("◈", ""),
    "book": ("▥", ""),
    "branch": ("⎇", ""),
    "mail": ("@", ""),
    "shapes": ("◧", ""),
    "package": ("⬡", ""),
    "speech": ("❝", ""),
    "clock": ("◷", ""),
    "palette": ("◐", ""),
    "music": ("♪", ""),
    "check": ("✓", ""),
    "grid": ("▦", ""),
    "bell": ("◬", ""),
}

# Which sign a tool wears: its own name decides first.
_SIGN_BY_TOOL = {
    "web_search": "globe",
    "read_webpage": "globe",
    "run_command": "shell",
    "read_file": "page",
    "deliver_file": "page",
    "search_files": "search",
    "write_file": "pencil",
    "edit_file": "edit",
    "list_dir": "folder",
    "create_folder": "folder",
    "ask_user": "question",
    "draw_image": "picture",
    "generate_image": "picture",
    "image_to_image": "picture",
    "inpaint_image": "picture",
    "remove_background": "cutout",
    "memory_save": "memory",
}

# Then the server it came from: every tool of a server wears that server's
# sign, whatever it is called.
_SIGN_BY_SERVER = {
    "shell": "shell",
    "memory": "memory",
    "skills": "book",
    "websuche": "globe",
    "searxng": "globe",
    "notion": "page",
    "recraft": "picture",
    "github": "branch",
    "gmail": "mail",
    "figma": "shapes",
    "huggingface": "package",
    "slack": "speech",
    "calendar": "clock",
    "drive": "folder",
    "canva": "palette",
    "spotify": "music",
    "todoist": "check",
    "asana": "check",
    "clickup": "check",
    "trello": "grid",
    "airtable": "grid",
    "linear": "folder",
    "vercel": "memory",
    "sentry": "bell",
}

# Whether the signs that have a Nerd Font icon use it. Off until the user
# says the terminal's font has them: no terminal tells its font.
_nerd = False


def use_nerd(enabled: bool) -> None:
    """Switches the Nerd Font signs on or off, for every sign drawn from
    now on."""
    global _nerd
    _nerd = enabled


def _encoding() -> str:
    """The encoding of what the client writes to, under its one canonical
    name — an empty string where there is none or nobody knows it."""
    name = getattr(sys.stdout, "encoding", None)
    if not isinstance(name, str) or not name:
        return ""
    try:
        canonical = codecs.lookup(name).name
    except LookupError:
        return ""
    # With or without a mark at the start of the stream, it is UTF-8.
    return "utf-8" if canonical == "utf-8-sig" else canonical


def speaks_unicode() -> bool:
    """Whether the output carries the Unicode signs."""
    return _encoding() == "utf-8"


def glyph(name: str) -> str:
    """The sign of that name; an empty string for a name without one."""
    sign = _GLYPHS.get(name)
    if sign is None:
        return ""
    plain, ascii_sign, icon = sign
    if not speaks_unicode():
        return ascii_sign
    return icon if _nerd and icon else plain


def tool_glyph(tool_name: str, server: str = "") -> str:
    """The sign in front of a line about that tool. A tool nobody has given
    a sign wears the general one."""
    if not speaks_unicode():
        return glyph("tool")
    sign = _TOOL_SIGNS.get(_SIGN_BY_TOOL.get(tool_name) or _SIGN_BY_SERVER.get(server) or "")
    if sign is None:
        return glyph("tool")
    plain, icon = sign
    return icon if _nerd else plain


def spinner_frames() -> tuple[str, ...]:
    """The frames the spinner runs through, in order: the star where the
    output speaks UTF-8, the ASCII strokes everywhere else."""
    return _STAR_FRAMES if speaks_unicode() else _ASCII_FRAMES


def overflow() -> OverflowMethod:
    """How a line that is too long for the window ends: with the mark that
    says so where the output carries it, cut short everywhere else — the
    mark the console writes is no ASCII character."""
    return "ellipsis" if speaks_unicode() else "crop"
