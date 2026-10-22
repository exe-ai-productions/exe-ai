"""The service's questions to the user: may this tool run, and what the
model itself asks — and the selection a command opens for the user to pick
from.

A question stands above the input field for as long as it is open. While it
does, the input field is the answer and not a message: a number takes the
choice of that number, an empty field the marked one, and where the model
asked, any other text is the answer in the user's own words. The arrow keys
move the mark, Escape declines.

Nothing is answered by a single key. A question arrives whenever the service
sends it, possibly in the middle of a sentence being typed — a digit of that
sentence must not grant a permission.

A selection is such a question with the entries of a list for its choices.
It is picked from the same way; the tabulator moves its mark as well, and
Escape closes it with nothing picked. It leaves nothing in the history. The
user opens it, so it gives way to every question of the service and never
takes the place of one.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Callable, Collection, Sequence
from dataclasses import dataclass, field
from typing import Any

from prompt_toolkit.application import get_app_or_none
from prompt_toolkit.filters import Condition
from prompt_toolkit.key_binding import KeyBindings, KeyBindingsBase, KeyPressEvent
from prompt_toolkit.utils import get_cwidth
from rich.text import Text

from cli import glyphs, themes
from cli.interfaces import Asker, Context, Entry, Event, Fragments, Piece
from cli.status import fitting

# How wide a line is taken to be where no terminal says.
_FALLBACK_COLUMNS = 80

# In front of every line that describes what the question is about.
_INDENT = "  "

# What marks a line that was cut at the edge of the window, and stands for
# the lines that were left out where the window is not high enough.
_CUT = "…"

# Between two columns of a selection, and between an entry and its remark.
_GAP = "  "

# What stands between two groups of the line that names the keys. Where the
# window is too narrow for the line, it goes on below at such a place only.
_BETWEEN_GROUPS = " · "

# The rows a selection shows its entries in at the least, however low the
# window is: one entry and a row at each side for the ones left out.
_LEAST_ENTRY_ROWS = 3

# The field of a choice's answer that names the entry picked from a
# selection.
_PICKED = "picked"

# The field of the answer that carries the positions ticked in a checklist.
_CHECKED = "checked"

# How long the typing pauses before a selection that searches asks for its
# entries anew, in seconds.
_SEARCH_PAUSE = 0.22


def build_asker(ctx: Context) -> Asker:
    return TerminalAsker(ctx)


@dataclass
class _Line:
    pieces: list[Piece]
    # Cut at the edge of the window instead of carried on below. Set for
    # what can be of any length — a tool's arguments — so the choices stay
    # in sight whatever a call brings along.
    cut: bool = False


@dataclass
class _Choice:
    label: str
    # The fields of the answer the service is sent when this one is taken.
    answer: dict[str, Any]
    # A quiet remark behind the label.
    note: str = ""


@dataclass
class _Question:
    # The lines above the choices.
    head: list[_Line]
    choices: list[_Choice]
    # What Escape answers with.
    declined: dict[str, Any]
    # The line below the choices; empty for none.
    foot: str = ""
    # Whether text that takes no choice is an answer of its own.
    free_text: bool = False
    # The choice an empty field takes.
    marked: int = 0
    # The answer, once there is one. A question closed without one was
    # withdrawn.
    answer: dict[str, Any] | None = None
    closed: threading.Event = field(default_factory=threading.Event)
    # The entries of a selection, one for every choice; ``None`` for a
    # question of the service.
    entries: list[Entry] | None = None
    # The positions ticked in a checklist, which is a selection that is
    # confirmed instead of picked from; ``None`` for any other question.
    checked: set[int] | None = None
    # What a selection that searches asks with what was typed, the entries
    # it opened with, the sentence for no entry, and which asking is the
    # youngest: an answer of an older one is no answer any more.
    find: Callable[[str], Sequence[Entry]] | None = None
    first_entries: list[Entry] = field(default_factory=list)
    empty: str = ""
    youngest: int = 0
    asked: int = 0
    timer: threading.Timer | None = None
    # A question of a command that asks for a line of text and nothing
    # else, and whether that line is typed hidden. It leaves nothing in the
    # history — a hidden one least of all.
    text: bool = False
    secret: bool = False
    # The value a line of text starts out with: nothing typed takes it.
    # ``None`` where nothing typed closes the question.
    default: str | None = None
    # The first entry of a selection that is in sight, where the window has
    # no room for all of them.
    first: int = 0
    # The question as it was last drawn, and what it was drawn for: the
    # window's width, the marked choice and the rows there are for it. The
    # screen asks many times a second while something runs; the lines are
    # laid out once per change.
    drawn_for: tuple[int, int, int | None] | None = None
    drawn: Fragments = field(default_factory=list)


def _one_line(value: Any) -> str:
    """A value of a tool's arguments on one line."""
    if isinstance(value, str):
        return " ".join(value.split())
    return json.dumps(value, ensure_ascii=False)


def _fit(text: str, columns: int) -> str:
    """``text`` cut to ``columns`` cells, with a mark where something is
    missing. Only as much of it is looked at as can stand in the line at
    all, however long the rest is."""
    if len(text) <= columns and get_cwidth(text) <= columns:
        return text
    return fitting(text[:columns], max(0, columns - get_cwidth(_CUT))) + _CUT


def _in_sight(lines: list[_Line], room: int | None) -> list[_Line]:
    """The lines that fit into the ``room`` rows the screen has above its
    fixed block — ``None`` for as many as it takes.

    Where there are more, the lines that may be cut go first, from the last
    one upwards — a tool's arguments — and one mark stands in their place.
    The question itself and its choices always stay.
    """
    if room is None:
        return lines
    room = max(1, room)
    if len(lines) <= room:
        return lines
    # One more goes than there is too much: the mark needs a line too.
    going = [number for number, line in enumerate(lines) if line.cut][-(len(lines) - room + 1) :]
    if len(going) < 2:
        # A mark in place of a single line wins nothing.
        return lines
    kept = [line for number, line in enumerate(lines) if number not in going]
    kept.insert(going[0], _Line([("muted", _INDENT + _CUT)]))
    return kept


def _padded(text: str, columns: int) -> str:
    """``text`` filled with blanks to ``columns`` cells."""
    return text + " " * max(0, columns - get_cwidth(text))


def _wrapped(text: str, columns: int, between: str = " ") -> list[str]:
    """``text`` in lines of at most ``columns`` cells, broken only where
    ``between`` stands — which is left out at a break. A part that is wider
    than a line stands on a line of its own."""
    lines: list[str] = []
    for part in text.split(between):
        if lines and get_cwidth(lines[-1] + between + part) <= columns:
            lines[-1] += between + part
        else:
            lines.append(part)
    return lines


def _section(heights: list[int], marked: int, first: int, rows: int) -> tuple[int, int]:
    """Which entries of a selection stand in ``rows`` rows, as the first and
    the one behind the last: from ``first`` on as many as fit, a row kept
    free at each side where entries are left out, and moved no further than
    it takes for the marked one to be among them. ``heights`` says how many
    rows each entry takes."""
    count = len(heights)

    def end_from(start: int) -> int:
        room = rows - (1 if start else 0)
        end = start
        while end < count:
            left = room - heights[end]
            # The entry goes in where the row for the ones below it still
            # stays free, or where it is the last. The first always does.
            if end > start and left < (0 if end + 1 == count else 1):
                break
            room, end = left, end + 1
        return end

    first = max(0, min(first, marked))
    while end_from(first) <= marked:
        first += 1
    # At the end of the list no row stays empty that an entry above could
    # stand in.
    while first > 0 and end_from(first - 1) == count:
        first -= 1
    return first, end_from(first)


class TerminalAsker(Asker):
    """Shows one question at a time and hands its answer back to whoever
    waits for it."""

    def __init__(self, ctx: Context) -> None:
        self._ctx = ctx
        self._lock = threading.Lock()
        self._open: _Question | None = None
        # True once the client leaves. Nothing is asked from then on:
        # nobody is left to answer, and whoever asked would wait for good.
        self._left = False
        self._keys = self._bindings()

    # --- The two questions of the service -------------------------------------

    def confirm_tool(self, event: Event) -> dict[str, Any] | None:
        texts = self._ctx.texts
        model = self._ctx.session.model() or {}
        asking = str(model.get("name") or self._ctx.session.endpoint_id or "")
        head = [
            _Line([("yellow", texts.t("werkzeug.permission_label"))]),
            _Line(
                [
                    ("text", f"{asking} {texts.t('werkzeug.wants_to_run_before')}".lstrip()),
                    ("tool", str(event.get("name") or "")),
                    ("text", texts.t("werkzeug.wants_to_run_after")),
                ]
            ),
        ]
        arguments = event.get("argumente")
        if isinstance(arguments, dict):
            for key, value in arguments.items():
                head.append(_Line([("muted", f"{_INDENT}{key}: {_one_line(value)}")], cut=True))
        reason = " ".join(str(event.get("grund") or "").split())
        # The sentence names no place; the place follows it after a colon, as
        # the window does where its command does not carry it.
        place = " ".join(str(event.get("grund_wert") or "").split())
        if reason and place:
            reason = f"{reason}: {place}"
        if reason:
            head.append(_Line([("muted", _INDENT + reason)]))
        head.append(_Line([("text", texts.t("werkzeug.permission_question"))]))
        declined = {"erlaubt": False, "dauerhaft": False}
        return self._ask(
            _Question(
                head=head,
                choices=[
                    _Choice(
                        texts.t("werkzeug.just_this_once"),
                        {"erlaubt": True, "dauerhaft": False},
                    ),
                    _Choice(
                        texts.t("werkzeug.yes_dont_ask_again"),
                        {"erlaubt": True, "dauerhaft": True},
                    ),
                    _Choice(texts.t("app.nein"), declined),
                ],
                declined=declined,
            )
        )

    def ask_user(self, event: Event) -> dict[str, Any] | None:
        choices: list[_Choice] = []
        options = event.get("optionen")
        for option in options if isinstance(options, list) else []:
            # An option is a label with a remark; a bare word is a label.
            described = option if isinstance(option, dict) else {"label": option}
            label = str(described.get("label") or "").strip()
            if label:
                note = str(described.get("description") or "").strip()
                choices.append(_Choice(label, {"antwort": label}, note))
        asked = str(event.get("frage") or "").splitlines() or [""]
        return self._ask(
            _Question(
                head=[_Line([("text", line)]) for line in asked],
                choices=choices,
                # An empty answer closes the question: the model is told that
                # none came and goes on, instead of waiting out the service's
                # own patience.
                declined={"erlaubt": False, "antwort": ""},
                foot=self._ctx.texts.t("benutzerfrage.frei"),
                free_text=True,
            )
        )

    # --- What a command lets the user pick from --------------------------------

    def choose(self, entries: Sequence[Entry], head: str = "") -> int | None:
        listed = list(entries)
        if not listed:
            return None
        in_use = [number for number, entry in enumerate(listed) if entry.in_use]
        answer = self._ask(
            _Question(
                head=[_Line([("text", line)]) for line in head.splitlines()],
                choices=[_Choice("", {_PICKED: number}) for number in range(len(listed))],
                # Closed with nothing picked.
                declined={},
                foot=self._ctx.texts.t("cli.select_keys"),
                marked=in_use[0] if in_use else 0,
                entries=listed,
            )
        )
        return answer.get(_PICKED) if answer else None

    def check(
        self, entries: Sequence[Entry], head: str = "", checked: Collection[int] = ()
    ) -> list[int] | None:
        listed = list(entries)
        if not listed:
            return None
        answer = self._ask(
            _Question(
                head=[_Line([("text", line)]) for line in head.splitlines()],
                choices=[_Choice("", {_PICKED: number}) for number in range(len(listed))],
                # Closed with nothing confirmed.
                declined={},
                foot=self._ctx.texts.t("cli.select_keys_check"),
                entries=listed,
                checked={number for number in checked if 0 <= number < len(listed)},
            )
        )
        confirmed = answer.get(_CHECKED) if answer else None
        return list(confirmed) if isinstance(confirmed, list) else None

    def search(
        self,
        entries: Sequence[Entry],
        find: Callable[[str], Sequence[Entry]],
        head: str = "",
        empty: str = "",
    ) -> Entry | None:
        listed = list(entries)
        question = _Question(
            head=[_Line([("text", line)]) for line in head.splitlines()],
            choices=[_Choice("", {_PICKED: number}) for number in range(len(listed))],
            # Closed with nothing picked.
            declined={},
            foot=self._ctx.texts.t("cli.select_keys_search"),
            entries=listed,
            find=find,
            first_entries=listed,
            empty=empty,
        )
        answer = self._ask(question)
        picked = answer.get(_PICKED) if answer else None
        current = question.entries or []
        if isinstance(picked, int) and 0 <= picked < len(current):
            return current[picked]
        return None

    def typed(self, text: str) -> None:
        """What the input field holds now. A selection that searches runs
        its search a moment after the typing paused; a number, or nothing,
        shows the entries it opened with again at once."""
        question = self._open
        if question is None or question.find is None:
            return
        word = text.strip()
        with self._lock:
            if question.timer is not None:
                question.timer.cancel()
                question.timer = None
            question.asked += 1
            asked = question.asked
        if not word or word.isdecimal():
            self._show(question, asked, question.first_entries)
            return
        timer = threading.Timer(_SEARCH_PAUSE, self._search, args=(question, asked, word))
        timer.daemon = True
        with self._lock:
            if question.asked != asked:
                return
            question.timer = timer
        timer.start()

    def _search(self, question: _Question, asked: int, word: str) -> None:
        find = question.find
        if find is None:
            return
        try:
            found = list(find(word))
        except Exception:  # noqa: BLE001 - a search that fails changes nothing
            return
        self._show(question, asked, found)

    def _show(self, question: _Question, asked: int, entries: Sequence[Entry]) -> None:
        """Puts ``entries`` in the place of the selection's — unless a
        younger asking came meanwhile or the selection is gone."""
        listed = list(entries)
        with self._lock:
            if self._open is not question or question.asked != asked:
                return
            question.entries = listed
            question.choices = [_Choice("", {_PICKED: number}) for number in range(len(listed))]
            question.marked = 0
            question.first = 0
            question.youngest = asked
            question.drawn_for = None
        self._ctx.screen.invalidate()

    def ask_text(
        self, head: str, *, secret: bool = False, default: str | None = None
    ) -> str | None:
        answer = self._ask(
            _Question(
                head=[_Line([("text", line)]) for line in head.splitlines()],
                choices=[],
                # Closed with nothing typed.
                declined={},
                free_text=True,
                text=True,
                secret=secret,
                default=default,
            )
        )
        typed = answer.get("antwort") if answer else None
        if not isinstance(typed, str):
            return None
        return typed if typed or default is not None else None

    def secret(self) -> bool:
        question = self._open
        return question is not None and question.secret

    def _ask(self, question: _Question) -> dict[str, Any] | None:
        with self._lock:
            previous = self._open
            if self._left or (previous is not None and question.entries is not None):
                # A selection never takes the place of what stands above
                # the field: a question of the service stays answerable.
                # And a client that leaves asks nothing any more.
                return None
            self._open = question
        if previous is not None:
            # Only one question can stand above the field. The older one is
            # withdrawn; whoever waits for it gets no answer.
            previous.closed.set()
        self._ctx.screen.invalidate()
        question.closed.wait()
        return question.answer

    def cancel(self) -> None:
        with self._lock:
            question = self._open
            if question is None or question.entries is not None:
                # A selection is the user's own: the end of an answer does
                # not take it away.
                return
            self._open = None
        question.closed.set()
        self._ctx.screen.invalidate()

    def close(self) -> None:
        with self._lock:
            self._left = True
            question, self._open = self._open, None
        if question is None:
            return
        question.closed.set()
        self._ctx.screen.invalidate()

    # --- What the screen asks -------------------------------------------------

    def pending(self) -> bool:
        return self._open is not None

    def fragments(self) -> Fragments:
        question = self._open
        if question is None:
            return []
        app = get_app_or_none()
        size = app.output.get_size() if app is not None else None
        columns = size.columns if size is not None else _FALLBACK_COLUMNS
        # Both take the rows the screen has for them right now, above its
        # fixed block as that stands at this moment.
        free = self._ctx.screen.rows_for_question()
        drawn_for = (columns, question.marked, free)
        if question.drawn_for == drawn_for:
            return question.drawn
        lines = (
            _in_sight(self._lines(question, question.marked), free)
            if question.entries is None
            else self._selection(question, columns, free)
        )
        fragments: Fragments = []
        for line in lines:
            if fragments:
                fragments.append(("", "\n"))
            room = columns
            for style, text in line.pieces:
                shown = _fit(text, room) if line.cut else text
                room = max(0, room - get_cwidth(shown))
                fragments.append((f"class:{style}", shown))
        question.drawn_for, question.drawn = drawn_for, fragments
        return fragments

    def key_bindings(self) -> KeyBindingsBase:
        return self._keys

    # --- Drawing --------------------------------------------------------------

    def _lines(self, question: _Question, marked: int | None) -> list[_Line]:
        """The question line by line; ``marked`` is the choice that carries
        the mark, ``None`` for none of them."""
        mark = glyphs.glyph("prompt")
        lines = list(question.head)
        if question.text and question.default:
            # The value that stands, as the line a typed answer replaces.
            lines.append(_Line([("accent", mark + " "), ("text", question.default)]))
        for number, choice in enumerate(question.choices):
            chosen = number == marked
            pieces: list[Piece] = [
                ("accent", (mark if chosen else " " * get_cwidth(mark)) + " "),
                ("accent" if chosen else "text", f"{number + 1}. {choice.label}"),
            ]
            if choice.note:
                pieces.append(("muted", f"  {choice.note}"))
            lines.append(_Line(pieces))
        if question.foot:
            lines.append(_Line([("muted", question.foot)]))
        return lines

    def _selection(self, question: _Question, columns: int, room: int | None) -> list[_Line]:
        """A selection line by line, for a window ``columns`` wide that has
        ``room`` rows for it — ``None`` for as many as it takes.

        Every entry is a line: the mark where it is the marked one, its
        number, the sign where it is the one in use, then its columns, each
        below the same column of the other entries. A name too long for the
        window is cut; a remark is carried on below its own beginning.
        Below the entries stands the line that names the keys. Where the
        rows do not take all entries, the ones around the marked one are
        shown, and a sign stands at each side where entries are left out —
        in as many rows as before, whichever entries they are."""
        entries = question.entries or []
        head = question.head
        if not entries:
            # A search that found nothing: the sentence for it stands where
            # the entries stood, and the keys below.
            lines = list(head)
            if question.empty:
                lines.append(_Line([("muted", question.empty)]))
            lines.extend(
                _Line([("muted", line)]) for line in _wrapped(question.foot, columns, _BETWEEN_GROUPS)
            )
            return lines
        mark = glyphs.glyph("prompt")
        ticked, unticked = glyphs.glyph("checked"), glyphs.glyph("unchecked")
        in_use = glyphs.glyph("in_use")
        checklist = question.checked is not None
        # The sign stands in the place of the one of the entry in use: in a
        # checklist it says whether the entry is ticked.
        sign = max(get_cwidth(ticked), get_cwidth(unticked)) if checklist else get_cwidth(in_use)
        digits = len(str(len(entries)))
        # In front of the columns: the mark, the number with its full stop,
        # and the sign, each with a blank behind it.
        lead = get_cwidth(mark) + 1 + digits + 2 + sign + 1
        widths = [
            max(get_cwidth(entry.cells[column][1]) for entry in entries if column < len(entry.cells))
            for column in range(max(len(entry.cells) for entry in entries))
        ]
        if widths:
            # The names give way to the columns behind them.
            behind = sum(widths[1:]) + get_cwidth(_GAP) * (len(widths) - 1)
            widths[0] = max(1, min(widths[0], columns - lead - behind))
        # Where a remark begins, and how wide it may run.
        remark_at = lead + sum(widths) + get_cwidth(_GAP) * len(widths)
        remark_room = max(1, columns - remark_at)

        def lines_of(number: int) -> list[_Line]:
            entry = entries[number]
            marked = number == question.marked
            if checklist:
                shown = ticked if number in (question.checked or ()) else unticked
            else:
                shown = in_use if entry.in_use else " " * sign
            pieces: list[Piece] = [
                ("accent", (mark if marked else " " * get_cwidth(mark)) + " "),
                ("accent" if marked else "text", f"{number + 1:>{digits}}. "),
                ("accent", _padded(shown, sign) + " "),
            ]
            remark = _wrapped(entry.note, remark_room) if entry.note else []
            cells = [*entry.cells, *[("text", "")] * (len(widths) - len(entry.cells))]
            # The last column that says something ends the line, unless a
            # remark follows: that one begins behind all columns.
            last = max((column for column, cell in enumerate(cells) if cell[1]), default=-1)
            for column, (style, text) in enumerate(cells):
                if column == 0:
                    style, text = ("accent" if marked else style), _fit(text, widths[0])
                if remark or column < last:
                    pieces.append((style, _padded(text, widths[column]) + _GAP))
                elif column == last:
                    pieces.append((style, text))
            if remark:
                pieces.append(("muted", remark[0]))
            further = [_Line([("muted", " " * remark_at + line)]) for line in remark[1:]]
            return [_Line(pieces), *further]

        def taken(lines: list[_Line]) -> int:
            """The rows the window draws these lines in. A line it has no
            room for — a word wider than the window — goes on in the next
            row, and takes that row too."""
            widths = (sum(get_cwidth(text) for _, text in line.pieces) for line in lines)
            return sum(max(1, -(-width // columns)) for width in widths)

        shown = [lines_of(number) for number in range(len(entries))]
        heights = [taken(lines) for lines in shown]
        foot = [_Line([("muted", line)]) for line in _wrapped(question.foot, columns, _BETWEEN_GROUPS)]
        # What stands above and below the entries takes its rows first.
        kept = taken(head) + taken(foot)
        if room is None or sum(heights) + kept <= room:
            question.first = 0
            return head + [line for lines in shown for line in lines] + foot
        rows = max(_LEAST_ENTRY_ROWS, room - kept)
        first, end = _section(heights, question.marked, question.first, rows)
        question.first = first
        left_out = _Line([("muted", " " * (get_cwidth(mark) + 1) + glyphs.glyph("more"))])
        section = [line for lines in shown[first:end] for line in lines]
        if first:
            section.insert(0, left_out)
        if end < len(entries):
            section.append(left_out)
        # Entries of more than one row may leave a row over; it stays the
        # selection's, so the block below it does not move with the mark.
        section += [_Line([("text", "")])] * (rows - taken(section))
        return head + section + foot

    def _record(self, question: _Question, marked: int | None, typed: str) -> None:
        """Writes the answered question into the history: what was asked,
        what could be chosen and what was. The lines above the input field
        are gone with the answer; this is what stays."""
        lines = self._lines(question, marked)
        if marked is None and typed:
            lines.append(_Line([("accent", glyphs.glyph("prompt") + " "), ("text", typed)]))
        record: list[Text] = []
        for line in lines:
            written = (
                Text(no_wrap=True, overflow="ellipsis") if line.cut else Text()
            )
            for style, text in line.pieces:
                written.append(text, style=themes.RICH_PREFIX + style)
            record.append(written)
        self._ctx.screen.print_above(*record)

    # --- Keys -----------------------------------------------------------------

    def _bindings(self) -> KeyBindingsBase:
        keys = KeyBindings()
        keys.add("enter")(self._on_enter)
        keys.add("up")(lambda event: self._move(-1))
        keys.add("down")(lambda event: self._move(1))
        # In a selection the tabulator moves the mark as well. Under a
        # question of the service it keeps what it does in the input field.
        selecting = Condition(self._selecting)
        keys.add("tab", filter=selecting)(lambda event: self._move(1))
        keys.add("s-tab", filter=selecting)(lambda event: self._move(-1))
        # Not at once: a terminal sends Escape in front of every key held
        # with Alt, and such a key must not decline a question on its way.
        # Escape by itself counts once nothing has followed it.
        keys.add("escape")(self._on_escape)
        # In a checklist the space bar ticks the marked entry — and writes
        # no blank into the input field.
        checking = Condition(self._checking)
        keys.add("space", filter=checking, eager=True)(lambda event: self._tick())
        # An open selection is the first thing Ctrl+C closes, like Escape,
        # and the client stays. Under a question of the service the key keeps
        # what the screen gives it: it stops the answer that is running.
        keys.add("c-c", filter=selecting)(self._on_escape)
        return keys

    def _selecting(self) -> bool:
        question = self._open
        return question is not None and question.entries is not None

    def _checking(self) -> bool:
        question = self._open
        return question is not None and question.checked is not None

    def _tick(self) -> None:
        question = self._open
        if question is None or question.checked is None:
            return
        question.checked ^= {question.marked}
        # The lines are laid out again for the new signs.
        question.drawn_for = None
        self._ctx.screen.invalidate()

    def _move(self, step: int) -> None:
        question = self._open
        if question is None or not question.choices:
            return
        question.marked = (question.marked + step) % len(question.choices)
        self._ctx.screen.invalidate()

    def _on_enter(self, event: KeyPressEvent) -> None:
        question = self._open
        if question is None:
            return
        buffer = event.current_buffer
        if question.checked is not None:
            # A checklist is confirmed as it stands; what was typed is no
            # answer to it.
            buffer.reset()
            self._settle(question, {_CHECKED: sorted(question.checked)}, None, "")
            return
        typed = buffer.text.strip()
        taken: int | None = None
        if question.find is not None and typed and not typed.isdecimal():
            # A word typed in a selection that searches: what was found so
            # far — or, where the pause is not over yet, what is found for
            # it now — is picked from, the marked entry first.
            self._settle_search(question, typed)
            if question.choices:
                taken = question.marked
                buffer.reset()
                self._settle(question, question.choices[taken].answer, taken, typed)
            return
        if not typed and question.text:
            buffer.reset()
            if question.default is not None:
                # Nothing typed keeps the value that stands.
                self._settle(question, {"antwort": question.default}, None, "")
                return
            # Nothing typed answers a question for text with nothing: it
            # is closed, and what the command asks about stays as it was.
            self._settle(question, question.declined, None, "")
            return
        if not typed:
            taken = question.marked if question.choices else None
        elif typed.isdecimal() and 1 <= int(typed) <= len(question.choices):
            taken = int(typed) - 1
        if taken is not None:
            answer = question.choices[taken].answer
        elif typed and question.free_text:
            answer = {"antwort": typed}
        else:
            # Nothing that answers this question. The field keeps what it
            # holds — it may be a message that was being typed when the
            # question came.
            return
        buffer.reset()
        self._settle(question, answer, taken, typed)

    def _settle_search(self, question: _Question, word: str) -> None:
        """Brings a search that is still waiting for its pause to its end
        now, for ``word`` as it stands in the field."""
        with self._lock:
            waiting = question.timer
            question.timer = None
            if question.youngest == question.asked and waiting is None:
                return
        if waiting is not None:
            waiting.cancel()
        find = question.find
        if find is None:
            return
        try:
            found = list(find(word))
        except Exception:  # noqa: BLE001 - a search that fails changes nothing
            return
        self._show(question, question.asked, found)

    def _on_escape(self, event: KeyPressEvent) -> None:
        question = self._open
        if question is None:
            return
        if question.find is not None:
            # What was typed was a search and no message: it goes with the
            # selection.
            event.current_buffer.reset()
        declining = [
            number
            for number, choice in enumerate(question.choices)
            if choice.answer == question.declined
        ]
        self._settle(question, question.declined, declining[0] if declining else None, "")

    def _settle(
        self, question: _Question, answer: dict[str, Any], marked: int | None, typed: str
    ) -> None:
        with self._lock:
            if self._open is not question:
                # Withdrawn in the meantime; nobody waits for this answer.
                return
            self._open = None
        if question.timer is not None:
            question.timer.cancel()
        question.answer = dict(answer)
        if question.entries is None and not question.text:
            # A selection leaves nothing behind: what was picked shows in
            # what the command then does. A line of text asked for by a
            # command does not either.
            self._record(question, marked, typed)
        question.closed.set()
        self._ctx.screen.invalidate()
